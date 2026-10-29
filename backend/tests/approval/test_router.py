"""C09 第 6 节的接口（T-AP-3）：经 FastAPI 的 TestClient 调用 `approval_router`，执行上下文由测试代替 assembly 给出。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from cost_platform.approval import approval_router
from cost_platform.contracts import types as t

from .support import ADMIN, PEOPLE, YANGNA, Harness
from .test_freeze import e37_save


def client(h: Harness) -> TestClient:
    people = {p.user_id: p for p in PEOPLE}

    def context(request: Request, is_write: bool) -> t.ExecutionContext:
        return h.ctx(people[request.headers["x-user"]])

    app = FastAPI()
    app.include_router(approval_router(h.service, context))

    @app.exception_handler(t.PlatformError)
    async def platform_error(request: Request, exc: t.PlatformError) -> JSONResponse:
        return JSONResponse(t.dump_wire(t.ErrorResponse, exc.to_response()), status_code=exc.http_status)

    return TestClient(app)


def test_todo_detail_preview_pass_over_http() -> None:
    h = Harness(["COST_TO_GOODS"], threads=True)
    approval = e37_save(h, "80")
    api = client(h)
    admin = {"x-user": ADMIN.user_id}
    todo = api.get("/api/approvals", params={"box": "todo", "startRow": 0, "endRow": 50}, headers=admin)
    assert todo.status_code == 200
    assert todo.json()["total"] == 1 and todo.json()["rows"][0]["source"] == {"entity": "COST_PINGGU", "recordKey": "2550",
                                                                              "label": "250mg乙酰唑胺片"}
    detail = api.get(f"/api/approvals/{approval.approval_id}", headers=admin).json()
    assert detail["view"]["affected"][0]["rows"][0]["cells"][2] == {"before": "75", "after": "80"}
    preview = api.post(f"/api/approvals/{approval.approval_id}/preview", json={"checkedRows": []}, headers=admin).json()
    assert preview["fingerprint"] == detail["fingerprint"]  # 物料清单一块是 all，不能改勾选
    passed = api.post(f"/api/approvals/{approval.approval_id}/pass", headers=admin, json={
        "requestKey": "00000000-0000-4000-8000-0000000000c1", "fingerprint": detail["fingerprint"], "checkedRows": [],
        "comment": "价格已核对", "params": {}})
    assert passed.status_code == 200 and passed.json()["outcome"] == "approvalProcessed"
    assert passed.json()["approvals"][0]["status"] == "approved"
    mine = api.get("/api/approvals", params={"box": "mine"}, headers={"x-user": YANGNA.user_id}).json()
    assert mine["rows"][0]["status"] == "approved"


def test_reject_without_reason_and_withdraw_by_other_user() -> None:
    h = Harness(["COST_TO_GOODS"], threads=True)
    approval = e37_save(h)
    api = client(h)
    no_reason = api.post(f"/api/approvals/{approval.approval_id}/reject", headers={"x-user": ADMIN.user_id},
                         json={"requestKey": "00000000-0000-4000-8000-0000000000c2"})
    assert no_reason.status_code == 422 and no_reason.json()["code"] == "VALIDATION_FAILED"
    other = api.post(f"/api/approvals/{approval.approval_id}/withdraw", headers={"x-user": ADMIN.user_id},
                     json={"requestKey": "00000000-0000-4000-8000-0000000000c3"})
    assert other.status_code == 403
    done = api.post(f"/api/approvals/{approval.approval_id}/withdraw", headers={"x-user": YANGNA.user_id},
                    json={"requestKey": "00000000-0000-4000-8000-0000000000c4", "comment": "录入有误"})
    assert done.status_code == 200 and done.json()["approvals"][0]["status"] == "withdrawn"
