"""RT-01：握手时以 `touch=False` 认证；会话无效或 Origin 不在 `PLATFORM_ALLOWED_ORIGINS` 中时拒绝握手。

拒绝握手时返回 C03 的错误响应（HTTP 状态和错误体），浏览器只看到连接失败。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from starlette.testclient import WebSocketDenialResponse

from .support import CHENG, Env, connect, ping


def test_valid_session_connects_and_does_not_extend_session() -> None:
    env = Env()
    session = env.login(CHENG)
    with env.process() as (_rt, client), connect(client, session.session_id) as ws:
        ping(ws)
    calls = env.auth.calls_to("authenticate")
    # 握手、心跳各一次：会话 Cookie，不是写请求，不顺延会话
    assert [c.args for c in calls] == [(session.session_id, None, False, False)] * 2


def test_origin_not_allowed_is_rejected() -> None:
    env = Env()
    session = env.login(CHENG)
    with env.process() as (_rt, client):
        with pytest.raises(WebSocketDenialResponse) as denied:
            with connect(client, session.session_id, origin="http://evil.example"):
                pass
    assert denied.value.status_code == 403
    assert denied.value.json()["code"] == "ORIGIN_REJECTED"


@pytest.mark.parametrize("case", ["no-cookie", "expired"])
def test_invalid_session_is_rejected(case: str) -> None:
    """没有会话 Cookie；用户 120 分钟没有操作，会话已过期（E19）。"""
    env = Env()
    session = env.login(CHENG)
    if case == "expired":
        env.clock.advance(timedelta(minutes=120))
    with env.process() as (_rt, client):
        with pytest.raises(WebSocketDenialResponse) as denied:
            with connect(client, None if case == "no-cookie" else session.session_id):
                pass
    assert denied.value.status_code == 401
    assert denied.value.json()["code"] == "SESSION_REQUIRED"
