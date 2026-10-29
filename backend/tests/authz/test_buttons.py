"""单角色授权、按钮权限（AZ-01、AZ-02、AZ-06，业务例子 E07）。工程约定第 5 节：先写失败的测试。

角色权限取自旧系统 cmx 的真实数据（见 samples.py）。技术中心在成本核算页：有保存、三个区域的复制、由BOM生成明细，
没有新增、删除、同步采购价和导出；001 有新增、同步采购价和导出 cost-pinggu-export。
"""

from __future__ import annotations

from typing import Any

import pytest

from cost_platform.authz import OperationPermissionStage, RolePermissionChecker
from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.contracts.types import (
    Command,
    CommandState,
    DetailAdd,
    DetailChange,
    DetailDelete,
    DetailModify,
    DocumentPatch,
    ErrorCode,
    MasterAdd,
    MasterDelete,
    MasterModify,
    MasterNone,
    Origin,
    PlatformError,
)

from .samples import (
    COST_MATERIAL,
    COST_PACKAGE,
    COST_PINGGU,
    EXPORT,
    GENERATE_FROM_BOM,
    GOODS_MANAGE,
    SAVE,
    SYNC_PRICE,
    TECH_CENTER_PINGGU_BUTTONS,
    context,
    role,
    snapshot,
)

MASTER_COPY = "tmp-1b3c5d7e-0000-4000-8000-000000000001"
MATERIAL_COPY = "tmp-1b3c5d7e-0000-4000-8000-000000000002"
PACKAGE_COPY = "tmp-1b3c5d7e-0000-4000-8000-000000000003"
MATERIAL_NEW = "tmp-1b3c5d7e-0000-4000-8000-000000000004"
PACKAGE_NEW = "tmp-1b3c5d7e-0000-4000-8000-000000000005"

checker = RolePermissionChecker()
stage = OperationPermissionStage(checker)


def command(*documents: DocumentPatch, operation: str = SAVE, page: str | None = COST_PINGGU,
            params: dict[str, Any] | None = None) -> Command:
    return Command(request_key="5c1e2f3a-4b5c-4d6e-8f70-8192a3b4c5d6", page=page, operation=operation,
                   documents=list(documents), params=params or {})


def copied_document() -> DocumentPatch:
    """复制单据 200680 的主表行：旧前端 copyMasterRow 连同明细一起复制，复制出的行在后端都是新增行（C06 第 8 节）。"""
    return DocumentPatch(entity=COST_PINGGU, master=MasterAdd(op="add", client_row_id=MASTER_COPY,
                                                               values={"GOODSID": "1", "MEMO": "测试"}),
                         details=[DetailAdd(entity=COST_MATERIAL, op="add", client_row_id=MATERIAL_COPY,
                                            values={"GOODSID": "115"}),
                                  DetailAdd(entity=COST_PACKAGE, op="add", client_row_id=PACKAGE_COPY,
                                            values={"GOODSID": "201"})])


def details_of(*changes: DetailChange) -> DocumentPatch:
    """成本单 200680 的主表不改、只改明细。"""
    return DocumentPatch(entity=COST_PINGGU, master=MasterNone(op="none", row_key="200680"), details=list(changes))


def run(cmd: Command, role_code: str = "技术中心", **snapshot_args: Any) -> None:
    ctx = context(snapshot(role_code, **snapshot_args))
    with FakeUnitOfWorkFactory().begin() as uow:
        stage.run(uow, CommandState(command=cmd), ctx)


def denied(cmd: Command, role_code: str = "技术中心", **snapshot_args: Any) -> PlatformError:
    with pytest.raises(PlatformError) as caught:
        run(cmd, role_code, **snapshot_args)
    assert caught.value.code is ErrorCode.PERMISSION_DENIED
    return caught.value


# ---------------------------------------------------------------- E07

def test_e07_tech_center_copies_master_row_and_saves() -> None:
    """技术中心复制成本核算主表行（连同明细）并保存：保存有 system:save，三个区域的新增行都有该区域的 copyRow。"""
    ctx = context(snapshot("技术中心"))
    assert checker.can_run(ctx, SAVE, COST_PINGGU) is True
    run(command(copied_document()))


def test_e07_new_row_not_from_copy_passes_by_area_copy_row() -> None:
    """直接调接口提交一条不是复制出来的新增行：按新增处理，原辅料明细有 copyRow 而放行（技术中心没有 system:addRow）。"""
    assert "system:addRow" not in TECH_CENTER_PINGGU_BUTTONS
    run(command(details_of(DetailAdd(entity=COST_MATERIAL, op="add", client_row_id=MATERIAL_NEW, values={"GOODSID": "117"}))))


def test_e07_add_in_area_without_copy_row_is_denied() -> None:
    """没有 copyRow 的区域新增返回 403。cmx 中技术中心在成本核算三个区域都有 copyRow（03 查询没有现成的反例），
    这里在真实权限上去掉包材明细的 copyRow；原辅料明细照常放行，拒绝明细指向包材明细那一行。"""
    assert "system:addRow" in role("001").pages[COST_PINGGU].buttons  # 001 有新增，但选了技术中心，不起作用
    without = [b for b in TECH_CENTER_PINGGU_BUTTONS if b != "COST_PACKAGE:copyRow"]
    tech = role("技术中心", **{COST_PINGGU: {"buttons": without}})
    error = denied(command(details_of(
        DetailAdd(entity=COST_MATERIAL, op="add", client_row_id=MATERIAL_NEW, values={"GOODSID": "117"}),
        DetailAdd(entity=COST_PACKAGE, op="add", client_row_id=PACKAGE_NEW, values={"GOODSID": "201"}))), grant_role=tech)
    assert [(d.entity, d.client_row_id) for d in error.details] == [(COST_PACKAGE, PACKAGE_NEW)]


def test_e07_only_the_selected_role_applies() -> None:
    """账号同时有技术中心和 001，选了技术中心：只有 001 有的权限（新增、同步采购价、导出、产品信息维护页）都不起作用。"""
    tech, other = context(snapshot("技术中心")), context(snapshot("001"))

    assert checker.can_run(other, SYNC_PRICE, COST_PINGGU) is True
    assert checker.can_run(tech, SYNC_PRICE, COST_PINGGU) is False
    denied(command(operation=SYNC_PRICE, params={"selectedRows": [{"entity": COST_PINGGU, "rowKey": "200680"}]}))

    assert checker.can_export(other, COST_PINGGU, EXPORT) is True
    assert checker.can_export(tech, COST_PINGGU, EXPORT) is False

    assert checker.can_access_page(other, GOODS_MANAGE) is True
    assert checker.can_access_page(tech, GOODS_MANAGE) is False


# ---------------------------------------------------------------- AZ-01 其余

def test_delete_without_delete_row_is_denied() -> None:
    """技术中心没有 system:deleteRow：删除明细行、删除整张单据都返回 403，明细指向被删的行。"""
    error = denied(command(details_of(DetailModify(entity=COST_MATERIAL, op="modify", row_key="5001", changes={"MEMO": "改"}),
                                      DetailDelete(entity=COST_MATERIAL, op="delete", row_key="5002"))))
    assert [(d.entity, d.row_key) for d in error.details] == [(COST_MATERIAL, "5002")]
    error = denied(command(DocumentPatch(entity=COST_PINGGU, master=MasterDelete(op="delete", row_key="200680"), details=[])))
    assert [(d.entity, d.row_key) for d in error.details] == [(COST_PINGGU, "200680")]


def test_star_allows_everything() -> None:
    """ADMIN 在成本核算页为 ["*"]（cmx ROLE_ID 3）：保存、新增、复制、删除、按钮操作和导出都通过。"""
    ctx = context(snapshot("ADMIN"))
    for operation in (SAVE, SYNC_PRICE, GENERATE_FROM_BOM):
        assert checker.can_run(ctx, operation, COST_PINGGU) is True
    assert checker.can_export(ctx, COST_PINGGU, EXPORT) is True
    run(command(copied_document(),
                DocumentPatch(entity=COST_PINGGU, master=MasterModify(op="modify", row_key="200680", changes={"MEMO": "测试"}),
                              details=[DetailDelete(entity=COST_MATERIAL, op="delete", row_key="5002")]),
                DocumentPatch(entity=COST_PINGGU, master=MasterDelete(op="delete", row_key="200726"), details=[])), "ADMIN")
    run(command(operation=SYNC_PRICE, params={"selectedRows": [{"entity": COST_PINGGU, "rowKey": "200680"}]}), "ADMIN")


def test_button_operation_needs_its_button_key() -> None:
    """按钮操作需要引用该操作的按钮键：技术中心有 master:generateFromBom，可以执行由BOM生成明细。"""
    ctx = context(snapshot("技术中心"))
    assert checker.can_run(ctx, GENERATE_FROM_BOM, COST_PINGGU) is True
    run(command(operation=GENERATE_FROM_BOM, params={"selectedRows": [{"entity": COST_PINGGU, "rowKey": "200680"}]}))


def test_page_not_in_role_is_denied() -> None:
    """AZ-02：技术中心的角色配置中没有产品信息维护页，不能在这个页面执行命令。"""
    ctx = context(snapshot("技术中心"))
    assert checker.can_run(ctx, "GOODS_MANAGE.save", GOODS_MANAGE) is False
    denied(command(operation="GOODS_MANAGE.save", page=GOODS_MANAGE))


def test_approval_operations_only_need_a_selected_role() -> None:
    """审批处理（approval.*）的处理人由 approval 判断；这里只确认已选定角色，技术中心没有审批按钮也放行。"""
    ctx = context(snapshot("技术中心"))
    for operation in ("approval.pass", "approval.reject", "approval.withdraw"):
        assert checker.can_run(ctx, operation, None) is True
        run(command(operation=operation, page=None, params={"approvalId": "203"}))


def test_approval_origin_writes_skip_button_checks() -> None:
    """来源为审批的写入不按某个人的权限（架构 10.4 第 3 步；旧系统审批通过的修改跳过保存权限检查）。"""
    ctx = context(snapshot("技术中心"), origin=Origin(kind="approval", approval_id="203"))
    cmd = command(details_of(DetailDelete(entity=COST_MATERIAL, op="delete", row_key="5002")))
    with FakeUnitOfWorkFactory().begin() as uow:
        stage.run(uow, CommandState(command=cmd), ctx)
    assert checker.can_run(ctx, SAVE, COST_PINGGU) is True
