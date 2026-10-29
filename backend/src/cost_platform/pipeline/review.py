"""命令审查（WP-17、C09 第 7a 节）：管理员开启后，每个命令结束时（提交或回滚之后）记录一条，与旧系统的操作日志相同。

- 记录写入 Redis 列表 `{ns}:cmdlog`（最新的在前），最多保留最近 10000 条，不写数据库；开关为 Redis 键
  `{ns}:cmdlog:enabled`，所有进程共用。关闭时删除这个列表和开关。
- 写入失败只记应用日志，不影响命令。
- `RedisCommandMonitor`（端口 `CommandMonitor`）由 orchestration 包在整个命令事务外面（判重 → 各阶段 → 完成 → 提交或
  回滚），用 `SqlTracer` 记下期间的每条 SQL；投递在它之后，不算在命令里。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from fastapi import APIRouter, Query, Request, Response
from pydantic import ValidationError

from cost_platform.contracts.ports import Clock
from cost_platform.contracts.types import (
    Command,
    CommandLog,
    CommandReviewList,
    CommandReviewToggle,
    ErrorCode,
    ExecutionContext,
    PlatformError,
    dump_wire,
    parse_wire,
)

from .tracing import SqlTracer

_log = logging.getLogger(__name__)
LIMIT = 10000


class RedisClient(Protocol):
    """用到的 redis-py 方法。"""

    def get(self, name: str) -> Any: ...

    def set(self, name: str, value: str) -> Any: ...

    def delete(self, *names: str) -> Any: ...

    def lrange(self, name: str, start: int, end: int) -> list[Any]: ...

    def pipeline(self, transaction: bool = True) -> Any: ...


class RedisCommandReview:
    def __init__(self, redis: RedisClient, namespace: str, limit: int = LIMIT) -> None:
        self._redis = redis
        self._list = f"{namespace}:cmdlog"
        self._switch = f"{namespace}:cmdlog:enabled"
        self._limit = limit

    def enabled(self) -> bool:
        return self._redis.get(self._switch) is not None

    def set_enabled(self, enabled: bool) -> None:
        """开启时写开关；关闭时删除全部已记录的内容和开关（C09 第 7a 节）。"""
        if enabled:
            self._redis.set(self._switch, "1")
        else:
            self._redis.delete(self._list, self._switch)

    def record(self, log: CommandLog) -> None:
        pipe = self._redis.pipeline(transaction=True)
        pipe.lpush(self._list, json.dumps(dump_wire(CommandLog, log), ensure_ascii=False))
        pipe.ltrim(self._list, 0, self._limit - 1)
        pipe.execute()

    def list(self, start_row: int, end_row: int, user: str | None = None, result: str | None = None) -> CommandReviewList:
        """最新的在前；`user`、`result` 为空时不过滤。"""
        logs = [parse_wire(CommandLog, json.loads(raw)) for raw in self._redis.lrange(self._list, 0, -1)]
        logs = [entry for entry in logs if (not user or entry.user == user) and (not result or entry.result == result)]
        return CommandReviewList(enabled=self.enabled(), rows=logs[start_row:end_row], total=len(logs))


def _outcome(error: BaseException | None) -> tuple[str, ErrorCode | None, str | None]:
    """记录的结果：成功为 saved；业务上的拒绝（4xx）为 rejected；数据库、内部错误为 failed。"""
    if error is None:
        return "saved", None, None
    if isinstance(error, PlatformError):
        return ("failed" if error.http_status >= 500 else "rejected"), error.code, error.message
    return "failed", ErrorCode.INTERNAL_ERROR, str(error).splitlines()[0][:2000] if str(error) else type(error).__name__


class RedisCommandMonitor:
    """`CommandMonitor`（C08 第 5a 节）：开关打开时记下 `watch` 期间的每条 SQL，退出时（命令已提交或回滚）写一条记录；
    关闭时什么都不做，不追踪 SQL。异常照常抛出。"""

    def __init__(self, review: RedisCommandReview, tracer: SqlTracer, clock: Clock) -> None:
        self._review = review
        self._tracer = tracer
        self._clock = clock

    def _enabled(self) -> bool:
        try:
            return self._review.enabled()
        except Exception as exc:  # Redis 不可用时不审查，命令照常执行
            _log.warning("读取命令审查开关失败：%s", exc)
            return False

    @contextmanager
    def watch(self, command: Command, ctx: ExecutionContext) -> Iterator[None]:
        if not self._enabled():
            yield
            return
        started_at = self._clock.now()
        started = time.perf_counter()
        error: BaseException | None = None
        with self._tracer.capture() as trace:
            try:
                yield
            except BaseException as exc:
                error = exc
                raise
            finally:
                result, code, message = _outcome(error)
                self._write(CommandLog(
                    request_key=command.request_key, user=ctx.identity.username, page=command.page,
                    operation=command.operation, result=result, error_code=code, message=message,  # type: ignore[arg-type]
                    started_at=started_at, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    sql_count=trace.count, sql_ms=trace.total_ms, sql=trace.to_wire()))

    def _write(self, log: CommandLog) -> None:
        try:
            self._review.record(log)
        except Exception as exc:
            _log.warning("写入命令审查记录失败：%s", exc)


ContextOf = Callable[[Request, bool], ExecutionContext]
"""assembly 的请求上下文（会话、CSRF、配置快照，架构 10.1）：参数为请求和是否写请求。"""


def command_review_router(review: RedisCommandReview, context: ContextOf) -> APIRouter:
    """C09 第 7a 节的两个接口，只有管理员可以使用。"""
    router = APIRouter()

    def admin(request: Request, is_write: bool) -> None:
        if not context(request, is_write).config.role().admin:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, "只有管理员可以使用命令审查")

    @router.get("/api/admin/command-review")
    def list_logs(request: Request, start_row: int = Query(0, alias="startRow"), end_row: int = Query(50, alias="endRow"),
                  user: str = Query(""), result: str = Query("")) -> Any:
        admin(request, False)
        return dump_wire(CommandReviewList, review.list(start_row, end_row, user or None, result or None))

    @router.put("/api/admin/command-review", status_code=204)
    async def toggle(request: Request) -> Response:
        admin(request, True)
        try:
            body: CommandReviewToggle = parse_wire(CommandReviewToggle, json.loads(await request.body()))
        except (ValueError, ValidationError):
            raise PlatformError(ErrorCode.VALIDATION_FAILED, "请求内容不符合接口约定") from None
        review.set_enabled(body.enabled)
        return Response(status_code=204)

    return router
