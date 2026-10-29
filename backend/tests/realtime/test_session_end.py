"""RT-04 和心跳：会话撤销或过期后关闭连接。

- 收到 `session.revoked`：先把事件推给对应的连接，再关闭连接（关闭码 4401，见 contract-gaps.md）。
- 心跳（`{"type": "ping"}`）以 `touch=False` 检查会话：会话有效回 `pong`；会话已过期时关闭连接，不回 `pong`。
"""

from __future__ import annotations

from datetime import timedelta

from cost_platform.realtime import CLOSE_SESSION_ENDED

from .support import (
    ADMIN,
    CHENG,
    Env,
    connect,
    event_id,
    notification,
    ping,
    recv_close,
    recv_json,
    revoked_sessions,
    revoked_users,
)


def test_disabled_account_gets_event_then_connection_closes() -> None:
    """管理员停用程苏慧的账号：她开着的两个页签都收到会话撤销并被关闭；系统管理员的连接不受影响。"""
    env = Env()
    admin, cheng = env.login(ADMIN), env.login(CHENG)
    with env.process() as (rt, client), connect(client, cheng.session_id) as tab1, \
            connect(client, cheng.session_id) as tab2, connect(client, admin.session_id) as other:
        rt.publisher.publish(revoked_users(1, [cheng.user_id], "accountDisabled"))
        rt.publisher.publish(notification(2, [admin.user_id], "您有来自于物料清单及成本页面，业务单据为115的审批"))

        for ws in (tab1, tab2):
            assert recv_json(ws) == {"topic": "session.revoked", "eventId": event_id(1),
                                     "payload": {"reason": "accountDisabled"}}
            assert recv_close(ws) == CLOSE_SESSION_ENDED
        assert recv_json(other)["eventId"] == event_id(2)


def test_logout_closes_only_that_session() -> None:
    """系统管理员在两台电脑上登录，在其中一台注销：只有这个会话的连接被关闭，另一台照常收到通知。"""
    env = Env()
    office = env.login(ADMIN, session_id="1.office")
    laptop = env.login(ADMIN, session_id="1.laptop")
    with env.process() as (rt, client), connect(client, office.session_id) as ws_office, \
            connect(client, laptop.session_id) as ws_laptop:
        rt.publisher.publish(revoked_sessions(1, [office.session_id]))
        rt.publisher.publish(notification(2, [ADMIN.user_id], "您有来自于物料清单及成本页面，业务单据为115的审批"))

        assert recv_json(ws_office) == {"topic": "session.revoked", "eventId": event_id(1),
                                        "payload": {"reason": "loggedOut"}}
        assert recv_close(ws_office) == CLOSE_SESSION_ENDED
        assert recv_json(ws_laptop)["eventId"] == event_id(2)


def test_heartbeat_does_not_extend_session_and_expired_session_closes() -> None:
    """E19：程苏慧 10:00 登录后不再查询和保存，页面每次心跳都不顺延会话；12:01 的心跳发现会话已过期，连接被关闭。"""
    env = Env()
    cheng = env.login(CHENG)
    with env.process() as (_rt, client), connect(client, cheng.session_id) as ws:
        env.clock.advance(timedelta(minutes=60))
        ping(ws)                                    # 11:00 会话有效
        env.clock.advance(timedelta(minutes=61))
        ws.send_json({"type": "ping"})              # 12:01：如果 11:00 的心跳顺延了会话，这时还有效
        assert recv_close(ws) == CLOSE_SESSION_ENDED
