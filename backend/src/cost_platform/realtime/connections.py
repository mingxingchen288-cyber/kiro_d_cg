"""本进程的连接登记（模块说明第 2 节"每个进程内的连接表"）。

每个连接记着用户、会话和订阅的页面，并按这三项建索引，供分发按 audience 查找（RT-03）：
- `pages`：订阅了其中任一页面的连接；
- `users`：这些用户的连接；
- `sessions`：这些会话的连接。

连接表只在事件循环的线程里读写（`/ws` 的处理和订阅任务都在同一个事件循环中），不加锁。
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass

from cost_platform.contracts.types import Identity, PagesAudience, SessionsAudience, UsersAudience

CLOSE_SESSION_ENDED = 4401
"""会话撤销或过期后服务端关闭连接用的关闭码（C10 没有规定，见 .reports/modules/realtime/contract-gaps.md）。"""


@dataclass(frozen=True)
class End:
    """发送队列中的关闭指令：发完前面的消息后，用这个关闭码关闭连接。"""

    code: int
    reason: str


class Connection:
    """一个浏览器连接。要发给它的消息放进发送队列，由这个连接自己的发送任务按顺序发送（router.py）。"""

    _seq = itertools.count(1)

    def __init__(self, identity: Identity) -> None:
        self.number = next(Connection._seq)
        self.user_id = identity.user_id
        self.session_id = identity.session_id
        self.pages: set[str] = set()
        self.ended = False
        self._outbox: asyncio.Queue[str | End] = asyncio.Queue()

    def send(self, text: str) -> None:
        """放进发送队列；连接已经要关闭时不再发送。"""
        if not self.ended:
            self._outbox.put_nowait(text)

    def end(self, code: int = CLOSE_SESSION_ENDED, reason: str = "session ended") -> None:
        """发完队列中已有的消息后关闭连接；之后的 `send` 都不再发送。"""
        if not self.ended:
            self.ended = True
            self._outbox.put_nowait(End(code, reason))

    async def next_outgoing(self) -> str | End:
        return await self._outbox.get()


class ConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[int, Connection] = {}
        self._by_user: dict[str, set[int]] = {}
        self._by_session: dict[str, set[int]] = {}
        self._by_page: dict[str, set[int]] = {}

    def __len__(self) -> int:
        return len(self._connections)

    def add(self, identity: Identity) -> Connection:
        conn = Connection(identity)
        self._connections[conn.number] = conn
        self._by_user.setdefault(conn.user_id, set()).add(conn.number)
        self._by_session.setdefault(conn.session_id, set()).add(conn.number)
        return conn

    def remove(self, conn: Connection) -> None:
        if self._connections.pop(conn.number, None) is None:
            return
        _discard(self._by_user, conn.user_id, conn.number)
        _discard(self._by_session, conn.session_id, conn.number)
        for page in conn.pages:
            _discard(self._by_page, page, conn.number)

    def subscribe(self, conn: Connection, pages: list[str]) -> None:
        if conn.number not in self._connections:
            return
        for page in pages:
            conn.pages.add(page)
            self._by_page.setdefault(page, set()).add(conn.number)

    def unsubscribe(self, conn: Connection, pages: list[str]) -> None:
        for page in pages:
            conn.pages.discard(page)
            _discard(self._by_page, page, conn.number)

    def matching(self, audience: PagesAudience | UsersAudience | SessionsAudience) -> list[Connection]:
        """audience 匹配的连接，每个连接只出现一次，按连接建立的先后排列。"""
        if isinstance(audience, PagesAudience):
            index, keys = self._by_page, audience.pages
        elif isinstance(audience, UsersAudience):
            index, keys = self._by_user, audience.users
        else:
            index, keys = self._by_session, audience.sessions
        numbers = set().union(*(index.get(key, set()) for key in keys))
        return [self._connections[n] for n in sorted(numbers)]


def _discard(index: dict[str, set[int]], key: str, number: int) -> None:
    found = index.get(key)
    if found is not None:
        found.discard(number)
        if not found:
            del index[key]
