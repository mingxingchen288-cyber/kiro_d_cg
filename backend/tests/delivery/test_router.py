"""C09 第 7 节的接口：路径、方法、请求和响应字段与契约一致。APIRouter 挂在测试用的 FastAPI 应用上，
执行上下文由测试给出（代替 assembly 的会话校验）：`as_user` 指定当前登录的用户。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from cost_platform.contracts.types import ErrorResponse, ExecutionContext, PlatformError, dump_wire
from cost_platform.delivery import delivery_router

from .support import ADMIN, APPROVAL_LINK, PASSED_TITLE, SUBMITTED_TITLE, T0, YANG_NA, World, commit_registration, context
from .support import passed, state, submitted, world


@dataclass
class Api:
    client: TestClient
    w: World
    user: str = ADMIN
    writes: list[bool] = field(default_factory=list)

    def as_user(self, user_id: str) -> Api:
        self.user = user_id
        return self


@pytest.fixture
def api() -> Iterator[Api]:
    w = world()
    holder: dict[str, Api] = {}

    def ctx(_request: Request, is_write: bool) -> ExecutionContext:
        holder["api"].writes.append(is_write)
        return context(holder["api"].user, now=w.clock.now())

    app = FastAPI()
    app.include_router(delivery_router(w.service, ctx))

    @app.exception_handler(PlatformError)
    async def platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(dump_wire(ErrorResponse, exc.to_response()), status_code=exc.http_status)

    with TestClient(app) as client:
        holder["api"] = Api(client=client, w=w)
        yield holder["api"]


def test_inbox_list_and_read(api: Api) -> None:
    """E23：系统管理员的铃铛有 1 条未读；点开后标为已读，未读数为 0；杨娜看不到别人的通知。"""
    w = api.w
    [delivery_id] = commit_registration(w, state(submitted()), context(YANG_NA))
    w.clock.set(T0 + timedelta(seconds=1))
    w.service.dispatch_now([delivery_id])

    c = api.as_user(ADMIN).client
    unread = c.get("/api/inbox", params={"unread": "true", "startRow": 0, "endRow": 20})
    assert unread.status_code == 200, unread.text
    assert unread.json() == {"rows": [{"deliveryId": delivery_id, "title": SUBMITTED_TITLE, "body": "", "link": APPROVAL_LINK,
                                       "createdAt": "2026-10-24T09:30:01", "read": False}], "total": 1, "unread": 1}

    marked = c.post(f"/api/inbox/{delivery_id}/read")
    assert marked.status_code == 204 and marked.content == b""
    assert c.get("/api/inbox", params={"unread": "true"}).json() == {"rows": [], "total": 0, "unread": 0}
    everything = c.get("/api/inbox").json()
    assert [r["read"] for r in everything["rows"]] == [True] and everything["total"] == 1 and everything["unread"] == 0

    assert api.as_user(YANG_NA).client.get("/api/inbox").json() == {"rows": [], "total": 0, "unread": 0}
    assert api.writes == [False, True, False, False, False]  # POST 带 CSRF（C09 第 1 节）


def test_inbox_newest_first_and_paging(api: Api) -> None:
    """杨娜先后收到两条通知（E23 的"已通过"，以及假设的同一审批的第二条），新的在前，按 startRow、endRow 分页。"""
    w = api.w
    first = commit_registration(w, state(passed()), context(ADMIN))
    w.service.dispatch_now(first)
    w.clock.set(T0 + timedelta(minutes=5))
    second = commit_registration(w, state(passed()), context(ADMIN, now=T0 + timedelta(minutes=5)))
    w.service.dispatch_now(second)

    c = api.as_user(YANG_NA).client
    page = c.get("/api/inbox", params={"startRow": 0, "endRow": 1}).json()
    assert [r["deliveryId"] for r in page["rows"]] == second and page["total"] == 2 and page["unread"] == 2
    assert page["rows"][0]["title"] == PASSED_TITLE
    rest = c.get("/api/inbox", params={"startRow": 1, "endRow": 20}).json()
    assert [r["deliveryId"] for r in rest["rows"]] == first


def _abandon(w: World, delivery_id: str) -> None:
    """发送一直失败，直到放弃：提交后立即发送一次，再在第 1、3、7、15、31 分钟各重试一次。"""
    w.outage.down = True
    w.service.dispatch_now([delivery_id])
    for minute in (1, 3, 7, 15, 31):
        w.clock.set(T0 + timedelta(minutes=minute))
        w.service.retry_due()
    w.outage.down = False


def test_admin_lists_abandoned_and_requeues(api: Api) -> None:
    """系统管理员按状态查看投递记录，把放弃的记录重新排队；重新排队后为 pending，下一轮后台任务发送。"""
    w = api.w
    [delivery_id] = commit_registration(w, state(passed()), context(ADMIN))
    _abandon(w, delivery_id)

    c = api.as_user(ADMIN).client
    listed = c.get("/api/admin/deliveries", params={"status": "abandoned", "startRow": 0, "endRow": 50})
    assert listed.status_code == 200, listed.text
    assert listed.json() == {"rows": [{"deliveryId": delivery_id, "recipient": YANG_NA, "status": "abandoned", "attempts": 6,
                                       "nextRetryAt": None, "lastError": "RuntimeError：站内通知暂时写不进去"}], "total": 1}

    w.clock.set(T0 + timedelta(minutes=40))
    requeued = c.post(f"/api/admin/deliveries/{delivery_id}/requeue")
    assert requeued.status_code == 204, requeued.text
    pending = c.get("/api/admin/deliveries", params={"status": "pending"}).json()
    assert pending["rows"] == [{"deliveryId": delivery_id, "recipient": YANG_NA, "status": "pending", "attempts": 0,
                                "nextRetryAt": "2026-10-24T10:10:00", "lastError": "RuntimeError：站内通知暂时写不进去"}]
    assert c.get("/api/admin/deliveries", params={"status": "abandoned"}).json() == {"rows": [], "total": 0}

    again = c.post(f"/api/admin/deliveries/{delivery_id}/requeue")  # C09：不是 abandoned 时 422
    assert again.status_code == 422 and again.json()["code"] == "VALIDATION_FAILED"

    w.service.retry_due()
    assert c.get("/api/admin/deliveries").json()["rows"][0]["status"] == "sent"
    assert [r["delivery_id"] for r in w.inbox_rows()] == [delivery_id]


def test_admin_interfaces_are_for_admin_role_only(api: Api) -> None:
    """C09 第 1 节：`/api/admin/*` 只对管理员角色开放，杨娜（采购角色）为 403。"""
    response = api.as_user(YANG_NA).client.get("/api/admin/deliveries")
    assert response.status_code == 403 and response.json()["code"] == "PERMISSION_DENIED"
