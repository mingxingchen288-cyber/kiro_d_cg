"""配置的 Redis 副本（`cache.ConfigCache` 的 Redis 实现，键 `{ns}:cfg:*`，模块说明第 2 节）。

| 键 | 类型 | 内容 |
|---|---|---|
| `{ns}:cfg:gen` | 字符串 | 当前配置代号 |
| `{ns}:cfg:index` | 哈希 | 配置项编号 → `版本:代号` |
| `{ns}:cfg:item:<编号>` | 字符串 | 配置项（`ItemRecord.to_json()`） |
| `{ns}:cfg:pending` | 哈希 | 待生效登记：代号 → `{"items": [...], "at": "..."}` |
| `{ns}:cfg:deleted` | 哈希 | 删除墓碑：配置项编号 → 删除时的代号 |

读取（READ）和写入切换（APPLY）各是一个 Lua 脚本，在 Redis 中原子执行：读取只往返一次，读到的代号、索引和内容属于
同一时刻；切换时一批配置项一起生效，读不到新旧混合的版本。脚本按配置项的代号比较，不会把新版本改回旧版本。
内容键由脚本按前缀拼出（不在 KEYS 中声明），只适用于单机 Redis，不适用于 Redis Cluster。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any, TypeVar

import redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .cache import CacheRead, CacheUnavailable, PendingEntry, SyncBatch, SyncResult
from .records import ItemRecord

_T = TypeVar("_T")

READ_SCRIPT = """
local gen = tonumber(redis.call('GET', KEYS[1]) or '0')
local pending = redis.call('HGETALL', KEYS[3])
local known = tonumber(ARGV[3])
if gen == known then return {gen, pending} end
local index = redis.call('HGETALL', KEYS[2])
local role = ARGV[2]
local suffix = '|' .. role
local out_index, contents = {}, {}
for i = 1, #index, 2 do
  local id = index[i]
  local keep = true
  if string.sub(id, 1, 5) == 'role/' then
    keep = (id == 'role/' .. role)
  elseif string.sub(id, 1, 9) == 'pageView/' then
    keep = (#id >= #suffix and string.sub(id, -#suffix) == suffix)
  end
  if keep then
    out_index[#out_index + 1] = id
    out_index[#out_index + 1] = index[i + 1]
    local g = tonumber(string.match(index[i + 1], ':(%-?%d+)$'))
    if g > known then
      contents[#contents + 1] = id
      contents[#contents + 1] = redis.call('GET', ARGV[1] .. id) or ''
    end
  end
end
return {gen, pending, out_index, contents}
"""

APPLY_SCRIPT = """
local prefix = ARGV[1]
local target = tonumber(ARGV[2])
local full = ARGV[3] == '1'
local pos = 4
local written, deleted, removed, present = {}, {}, {}, {}
local function entry_gen(id)
  local v = redis.call('HGET', KEYS[2], id)
  if v then return tonumber(string.match(v, ':(%-?%d+)$')) end
  return 0
end
local function tomb(id) return tonumber(redis.call('HGET', KEYS[4], id) or '0') end
local n = tonumber(ARGV[pos]); pos = pos + 1
for i = 1, n do
  local id, ver, g, body = ARGV[pos], ARGV[pos + 1], tonumber(ARGV[pos + 2]), ARGV[pos + 3]
  pos = pos + 4
  present[id] = true
  local has = redis.call('HEXISTS', KEYS[2], id) == 1
  if g > math.max(entry_gen(id), tomb(id)) or (has and redis.call('EXISTS', prefix .. id) == 0) then
    redis.call('HSET', KEYS[2], id, ver .. ':' .. g)
    redis.call('SET', prefix .. id, body)
    redis.call('HDEL', KEYS[4], id)
    written[#written + 1] = id
  end
end
n = tonumber(ARGV[pos]); pos = pos + 1
for i = 1, n do
  local id, g = ARGV[pos], tonumber(ARGV[pos + 1])
  pos = pos + 2
  local has = redis.call('HEXISTS', KEYS[2], id) == 1
  if has and entry_gen(id) < g then
    redis.call('HDEL', KEYS[2], id)
    redis.call('DEL', prefix .. id)
    deleted[#deleted + 1] = id
    has = false
  end
  if (not has) and g > tomb(id) then redis.call('HSET', KEYS[4], id, g) end
end
if full then
  local index = redis.call('HGETALL', KEYS[2])
  for i = 1, #index, 2 do
    local id = index[i]
    local g = tonumber(string.match(index[i + 1], ':(%-?%d+)$'))
    if (not present[id]) and g <= target then
      redis.call('HDEL', KEYS[2], id)
      redis.call('DEL', prefix .. id)
      if target > tomb(id) then redis.call('HSET', KEYS[4], id, target) end
      deleted[#deleted + 1] = id
    end
  end
end
n = tonumber(ARGV[pos]); pos = pos + 1
local done = {}
for i = 1, n do done[ARGV[pos]] = true; pos = pos + 1 end
if full then
  local fields = redis.call('HKEYS', KEYS[3])
  for i = 1, #fields do
    if tonumber(fields[i]) <= target then done[fields[i]] = true end
  end
end
for g, _ in pairs(done) do
  if redis.call('HDEL', KEYS[3], g) == 1 then removed[#removed + 1] = tonumber(g) end
end
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
if target > cur then
  redis.call('SET', KEYS[1], target)
  cur = target
end
return {cur, written, deleted, removed}
"""


def _pending(raw: list[Any]) -> dict[int, PendingEntry]:
    found = {}
    for i in range(0, len(raw), 2):
        data = json.loads(raw[i + 1])
        generation = int(raw[i])
        found[generation] = PendingEntry(generation, tuple(data["items"]),
                                         datetime.strptime(data["at"], "%Y-%m-%dT%H:%M:%S"))
    return found


class RedisConfigCache:
    def __init__(self, client: redis.Redis, namespace: str) -> None:
        """`client` 用 `decode_responses=True` 创建。"""
        self._client = client
        base = f"{namespace}:cfg"
        self.keys = {"gen": f"{base}:gen", "index": f"{base}:index", "pending": f"{base}:pending",
                     "deleted": f"{base}:deleted", "item": f"{base}:item:"}
        self._read = client.register_script(READ_SCRIPT)
        self._apply = client.register_script(APPLY_SCRIPT)

    def _call(self, action: Callable[[], _T]) -> _T:
        try:
            return action()
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise CacheUnavailable(str(exc)) from None

    def read(self, role_code: str, known_generation: int) -> CacheRead:
        k = self.keys
        reply = self._call(lambda: self._read(keys=[k["gen"], k["index"], k["pending"]],
                                              args=[k["item"], role_code, known_generation]))
        generation, pending = int(reply[0]), _pending(reply[1])
        if len(reply) == 2:
            return CacheRead(generation, pending, None, {})
        raw_index, raw_contents = reply[2], reply[3]
        index = {}
        for i in range(0, len(raw_index), 2):
            version, _, gen = str(raw_index[i + 1]).partition(":")
            index[raw_index[i]] = (int(version), int(gen))
        contents = {raw_contents[i]: (ItemRecord.from_json(raw_contents[i + 1]) if raw_contents[i + 1] else None)
                    for i in range(0, len(raw_contents), 2)}
        return CacheRead(generation, pending, index, contents)

    def status(self) -> tuple[int, dict[int, PendingEntry]]:
        def run() -> list[Any]:
            pipe = self._client.pipeline(transaction=True)
            pipe.get(self.keys["gen"])
            pipe.hgetall(self.keys["pending"])
            return pipe.execute()

        generation, pending = self._call(run)
        flat = [x for pair in (pending or {}).items() for x in pair]
        return int(generation or 0), _pending(flat)

    def register_pending(self, entry: PendingEntry) -> None:
        body = json.dumps({"items": list(entry.items), "at": entry.registered_at.strftime("%Y-%m-%dT%H:%M:%S")},
                          ensure_ascii=False)
        self._call(lambda: self._client.hset(self.keys["pending"], str(entry.generation), body))

    def remove_pending(self, generations: Iterable[int]) -> None:
        fields = [str(g) for g in generations]
        if fields:
            self._call(lambda: self._client.hdel(self.keys["pending"], *fields))

    def apply(self, batch: SyncBatch) -> SyncResult:
        k = self.keys
        args: list[Any] = [k["item"], batch.generation, "1" if batch.full else "0", len(batch.upserts)]
        for record in batch.upserts:
            args += [record.id, record.version, record.generation, record.to_json()]
        args.append(len(batch.deletes))
        for value, gen in batch.deletes:
            args += [value, gen]
        args.append(len(batch.pending_done))
        args += [str(g) for g in batch.pending_done]
        reply = self._call(lambda: self._apply(keys=[k["gen"], k["index"], k["pending"], k["deleted"]], args=args))
        return SyncResult(int(reply[0]), list(reply[1]), list(reply[2]), sorted(int(g) for g in reply[3]))
