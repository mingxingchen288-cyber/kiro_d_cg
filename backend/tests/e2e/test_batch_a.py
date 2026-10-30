"""T-AS-4 批次 A 真实联调（d_cg + Redis，经真实的 HTTP 和 WebSocket；架构 10.1、10.6、10.7）。

两个后端进程（默认 8086、8087）共用一个 Redis 命名空间（servers.py），记为 A、B：

1. admin / admin123.. 在 A、B 上都能登录，选定角色为 ADMIN。
2. admin 在 A 保存成本核算的页面配置（主表"备注"列宽改为 321）：连在 A、B 上、打开了成本核算页的 WebSocket 都收到
   同一条 config.changed（pages 含 COST_PINGGU，version 为新的配置代号）；A、B 响应头的 X-Config-Version 都变大；
   B 上的页面视图中备注列宽为 321。最后保存回原来的内容，B 上的列宽恢复。
3. admin 在 A 停用 chengben01：chengben01 连在 A、B 上的 WebSocket 都先收到 session.revoked（accountDisabled），
   再被关闭（关闭码 4401）；chengben01 在 A、B 上的下一次请求都返回 401 SESSION_REQUIRED。最后恢复启用，
   chengben01 能重新登录。

配置写入 PF_CONFIG_ITEM 是全局的：用户和别的组的平台由各自命名空间的配置恢复任务（5 秒一次），也会看到这次的列宽
变化和改回。chengben01 停用期间（几秒）不能登录。
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed

from .servers import Backend, Browser, Socket

pytestmark = [pytest.mark.oracle, pytest.mark.redis]

PAGE = "COST_PINGGU"
ADMIN = ("admin", "admin123..")
ACCOUNTANT = ("chengben01", "Abc123..")
CLOSE_SESSION_ENDED = 4401


@pytest.fixture(scope="module")
def admins(servers: list[Backend]) -> Iterator[tuple[Browser, Browser]]:
    a, b = Browser(servers[0], *ADMIN), Browser(servers[1], *ADMIN)
    yield a, b
    a.close()
    b.close()


def memo_width(browser: Browser) -> Any:
    view = browser.ok(browser.get(f"/api/pages/{PAGE}/view"))
    return next(f for f in view["master"]["fields"] if f["name"] == "MEMO")["width"]


def config_changed(after: int) -> Any:
    return lambda m: (m.get("topic") == "config.changed" and PAGE in m["payload"]["pages"]
                      and m["payload"]["version"] > after)


def save_page(admin: Browser, item: dict[str, Any]) -> None:
    admin.ok(admin.put(f"/api/config/items/page/{PAGE}", {"name": item["name"], "content": item["content"]}))


def test_admin_logs_in_on_both_processes(admins: tuple[Browser, Browser]) -> None:
    for admin in admins:
        assert admin.login["user"]["username"] == "admin"
        assert admin.login["selectedRole"]["code"] == "ADMIN"
        me = admin.ok(admin.get("/api/me"))
        assert me["role"]["code"] == "ADMIN" and me["menus"]


def test_config_save_reaches_websockets_on_both_processes(admins: tuple[Browser, Browser]) -> None:
    a, b = admins
    original = a.ok(a.get(f"/api/config/items/page/{PAGE}"))
    width_before = memo_width(b)
    width = 322 if width_before == 321 else 321
    changed = copy.deepcopy(original)
    changed["content"]["master"]["fields"].setdefault("MEMO", {})["width"] = width
    with a.ws([PAGE]) as ws_a, b.ws([PAGE]) as ws_b:
        before = a.config_version()
        try:
            save_page(a, changed)
            event_a = ws_a.wait(config_changed(before))
            event_b = ws_b.wait(lambda m: m.get("eventId") == event_a["eventId"])
            assert event_b == event_a
            saved = event_a["payload"]["version"]
            assert a.config_version() >= saved > before
            assert b.config_version() >= saved
            assert memo_width(b) == width
        finally:
            save_page(a, original)
        restored = ws_b.wait(config_changed(saved))
        assert ws_a.wait(lambda m: m.get("eventId") == restored["eventId"]) == restored
    assert memo_width(b) == width_before
    assert a.ok(a.get(f"/api/config/items/page/{PAGE}"))["content"] == original["content"]


def closed_after_revoked(ws: Socket) -> int:
    """先收到 session.revoked，再被服务端关闭；返回关闭码。"""
    revoked = ws.wait(lambda m: m.get("topic") == "session.revoked")
    assert revoked["payload"] == {"reason": "accountDisabled"}
    with pytest.raises(ConnectionClosed) as closed:
        ws.wait(lambda m: False)
    assert closed.value.rcvd is not None
    return closed.value.rcvd.code


def test_disabled_account_websockets_closed_and_requests_401(servers: list[Backend],
                                                             admins: tuple[Browser, Browser]) -> None:
    a, _ = admins
    rows = a.ok(a.get("/api/admin/accounts", params={"keyword": ACCOUNTANT[0]}))["rows"]
    account = next(r for r in rows if r["username"] == ACCOUNTANT[0])
    assert account["enabled"] is True
    restore = {k: account[k] for k in ("displayName", "departmentId", "roleCodes")}
    on_a, on_b = Browser(servers[0], *ACCOUNTANT), Browser(servers[1], *ACCOUNTANT)
    try:
        with on_a.ws([PAGE]) as ws_a, on_b.ws([PAGE]) as ws_b:
            try:
                a.ok(a.put(f"/api/admin/accounts/{account['userId']}", {**restore, "enabled": False}))
                assert closed_after_revoked(ws_a) == CLOSE_SESSION_ENDED
                assert closed_after_revoked(ws_b) == CLOSE_SESSION_ENDED
                for browser in (on_b, on_a):
                    response = browser.get("/api/me")
                    assert response.status_code == 401, response.text
                    assert response.json()["code"] == "SESSION_REQUIRED"
            finally:
                a.ok(a.put(f"/api/admin/accounts/{account['userId']}", {**restore, "enabled": True}))
    finally:
        on_a.close()
        on_b.close()
    again = Browser(servers[1], *ACCOUNTANT)
    assert again.ok(again.get("/api/me"))["user"]["username"] == ACCOUNTANT[0]
    again.close()
    rows = a.ok(a.get("/api/admin/accounts", params={"keyword": ACCOUNTANT[0]}))["rows"]
    assert next(r for r in rows if r["username"] == ACCOUNTANT[0]) == account
