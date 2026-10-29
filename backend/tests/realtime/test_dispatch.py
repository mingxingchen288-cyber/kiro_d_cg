"""RT-03 和 C10 第 3 节：只把事件推给 audience 匹配的连接。

- `pages`：订阅了该页面的连接；
- `users`：该用户的连接（同一个用户开了几个页签就有几个连接）；
- `sessions`：该会话的连接（见 test_session_end.py）。

推送消息的格式见 C10 第 2 节：`topic`、`eventId`、`payload`，不带 audience。
"""

from __future__ import annotations

from .support import (
    ADMIN,
    CHENG,
    COST_MATERIAL,
    COST_PINGGU,
    Env,
    config_changed,
    connect,
    event_id,
    notification,
    ping,
    recv_json,
    subscribe,
)

APPROVAL_TITLE = "您有来自于物料清单及成本页面，业务单据为115的审批"   # E23


def test_config_changed_reaches_connections_that_opened_the_page() -> None:
    """E18：管理员改了成本核算页的配置，已打开成本核算页的连接收到配置变更；只开着物料清单页的连接收不到。"""
    env = Env()
    admin, cheng = env.login(ADMIN), env.login(CHENG)
    with env.process() as (rt, client), connect(client, cheng.session_id) as pinggu, \
            connect(client, admin.session_id) as material:
        subscribe(pinggu, COST_PINGGU)
        subscribe(material, COST_MATERIAL)

        rt.publisher.publish(config_changed(1, [COST_PINGGU], 13))
        rt.publisher.publish(config_changed(2, [COST_MATERIAL], 14))

        assert recv_json(pinggu) == {"topic": "config.changed", "eventId": event_id(1),
                                     "payload": {"pages": [COST_PINGGU], "version": 13}}
        assert recv_json(material) == {"topic": "config.changed", "eventId": event_id(2),
                                       "payload": {"pages": [COST_MATERIAL], "version": 14}}


def test_event_for_several_pages_is_pushed_once_per_connection() -> None:
    """一次保存影响两个页面，同时开着两个页面的连接只收到一条。"""
    env = Env()
    cheng = env.login(CHENG)
    with env.process() as (rt, client), connect(client, cheng.session_id) as ws:
        subscribe(ws, COST_PINGGU, COST_MATERIAL)
        rt.publisher.publish(config_changed(1, [COST_PINGGU, COST_MATERIAL], 13))
        rt.publisher.publish(config_changed(2, [COST_MATERIAL], 14))
        assert recv_json(ws)["eventId"] == event_id(1)
        assert recv_json(ws)["eventId"] == event_id(2)


def test_unsubscribed_page_no_longer_receives_config_changed() -> None:
    """关掉成本核算页签后（unsubscribe），这个页面的配置变更不再推给它。"""
    env = Env()
    cheng = env.login(CHENG)
    with env.process() as (rt, client), connect(client, cheng.session_id) as ws:
        subscribe(ws, COST_PINGGU, COST_MATERIAL)
        ws.send_json({"type": "unsubscribe", "pages": [COST_PINGGU]})
        ping(ws)

        rt.publisher.publish(config_changed(1, [COST_PINGGU], 13))
        rt.publisher.publish(config_changed(2, [COST_MATERIAL], 14))
        assert recv_json(ws)["eventId"] == event_id(2)


def test_notification_reaches_every_connection_of_the_recipient() -> None:
    """E23：系统管理员开着两个页签，收到审批通知；程苏慧收不到发给系统管理员的通知。"""
    env = Env()
    admin, cheng = env.login(ADMIN), env.login(CHENG)
    with env.process() as (rt, client), connect(client, admin.session_id) as tab1, \
            connect(client, admin.session_id) as tab2, connect(client, cheng.session_id) as other:
        rt.publisher.publish(notification(1, [admin.user_id], APPROVAL_TITLE))
        rt.publisher.publish(notification(2, [cheng.user_id], f"{APPROVAL_TITLE}已通过"))

        expected = {"topic": "notification", "eventId": event_id(1),
                    "payload": {"deliveryId": event_id(1001), "title": APPROVAL_TITLE, "body": "",
                                "link": "/approval/203"}}
        assert recv_json(tab1) == expected
        assert recv_json(tab2) == expected
        assert recv_json(other)["eventId"] == event_id(2)


def test_notification_does_not_need_page_subscription() -> None:
    """通知按用户推送，和打开了哪些页面无关。"""
    env = Env()
    admin = env.login(ADMIN)
    with env.process() as (rt, client), connect(client, admin.session_id) as ws:
        rt.publisher.publish(notification(1, [admin.user_id], APPROVAL_TITLE, link=None))
        assert recv_json(ws)["payload"] == {"deliveryId": event_id(1001), "title": APPROVAL_TITLE, "body": "",
                                            "link": None}
