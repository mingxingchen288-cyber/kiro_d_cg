"""复制出的行进入审批后按提交时的值写（approval T-AP-7，AP-02、AP-10；write-pipeline WP-16、WP-21）。d_cg + Redis，
后端为 conftest 的两个进程。

admin 在成本核算页复制成本单 2550：主表，加上明细中单价等于物料清单执行价（NVL(ZX_PRICE, PRICE)）的 10 行，命令的
写法同前端 `edit-buffer.ts` 的 `writableValues`（可写的字段照写；不可写、可见、能写进表的复制字段有值时也写；带 `copyOf`）；
再复制 206325 硬脂酸镁一行、把物料换成测试物料（参考价格 10、执行价为空），单价 63 不变：63 与 10 不同，进入 COST_TO_GOODS，
冻结新单据和测试物料。
- 待审修改存的是保存这一刻按源行解出的值：币种"人民币"等不可写字段取 2550 的值；只在视图中的物料名称、计算字段不在其中。
- 审批详情：新单据主表为"新增"，产品为 2550 的产品；复制的原辅料、包材都为"新增"，物料名称按 Lookup 查出，测试物料那一行
  触发审批；物料清单一块是测试物料，单价 → 63.00。
- admin 通过后新单据写入，与同样复制、不进审批直接保存的另一张新单据逐列相同（主表和那 10 行明细；计算字段、主键、
  默认取 SYSDATE 的两列除外）：复制的字段与 2550 相同，没复制的字段为空。改之前最终通过按 Patch 重放，没复制的字段补默认值，
  只在视图中的物料名称返回 422 FIELD_NOT_WRITABLE。

触发审批的那一行用测试物料，不用 2550 自己单价与执行价不同的四行（206319、206322、206325、206330）：通过时 COST_TO_GOODS
把物料清单的执行价写成这一行的单价、修改人写成 admin，这四个物料的执行价原为空（例如 115 硬脂酸镁），经平台改不回。
测试建的两张成本单经平台删除，测试物料直接删表（sample_two.CreatedData），审批、命令记录由 dcg.Cleanup 删除。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine

from .dcg import PAGE, Cleanup, document, one, rows, save_command
from .sample_two import TEST_GOODS_NAME, CreatedData
from .servers import Backend, Browser

pytestmark = [pytest.mark.oracle, pytest.mark.redis]

D = Decimal
ADMIN = ("admin", "admin123..")
SOURCE = "2550"
STEARATE = "206325"
MARKER = "PF_TEST test_copy_approval"
# 默认取 SYSDATE 的列：两张新单据各自取保存时的时间
SYSDATE_COLUMNS = {"yield_time", "apex_pl_time"}


@pytest.fixture(scope="module")
def admin(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[0], *ADMIN)
    yield browser
    browser.close()


@pytest.fixture(scope="module")
def copier(servers: list[Backend]) -> Iterator[Browser]:
    """复制、保存的会话：admin 在另一个后端进程上登录（d_cg 中成本会计 chengben01 没有成本核算的新增行权限
    `system:addRow`、`copyRow`，复制保存返回 403）。"""
    browser = Browser(servers[1], *ADMIN)
    yield browser
    browser.close()


@pytest.fixture
def created(dcg: Engine) -> Iterator[CreatedData]:
    """测试物料和测试成本单：用例中途失败、平台没删掉的，结束时直接按主键删。"""
    data = CreatedData(dcg)
    yield data
    data.drop_all()


def tmp() -> str:
    return f"tmp-{uuid.uuid4()}"


# ---------------------------------------------------------------- 按前端的写法生成复制命令

def _on_new_row(region: dict[str, Any], field: dict[str, Any]) -> bool:
    """同前端 `fields.ts` 的 `writableOnRow`（新增行）：主键、关联字段、计算字段、`erpRow.column` 不能写，ERP 列只在有
    `erpRow` 的实体上能写。"""
    erp = region.get("erpRow")
    if field["name"] in (region["primaryKey"], region.get("parentKey")) or field["calculated"]:
        return False
    if erp and field["name"] == erp["column"]:
        return False
    return bool(erp) if field["source"] == "erp" else True


def copied_values(region: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """复制出的行在命令中的值（`edit-buffer.ts` 的 `writableValues`）：可写的字段照写（为空也写 null）；不可写的字段可见、
    能写进表、有值时也写，后端按 `copyOf` 取源行的值。"""
    found: dict[str, Any] = {}
    for field in region["fields"]:
        name = field["name"]
        if name not in values or not _on_new_row(region, field):
            continue
        if field["editable"] or field.get("fillWritable"):
            found[name] = values[name]
        elif field["visible"] and values[name] is not None:
            found[name] = values[name]
    return found


def exec_prices(dcg: Engine, goods_ids: list[str]) -> dict[str, Decimal | None]:
    """物料清单的执行价：视图 T_COST_GOODS_PRICE_V 的 ZX_PRICE（执行价为空时取参考价格）。"""
    found = rows(dcg, f"SELECT goodsid, zx_price FROM t_cost_goods_price_v WHERE goodsid IN ({', '.join(goods_ids)})")
    return {str(r["goodsid"]): None if r["zx_price"] is None else D(str(r["zx_price"])) for r in found}


def copy_document(view: dict[str, Any], record: dict[str, Any], keep: list[tuple[str, dict[str, Any]]],
                  extra: list[tuple[str, dict[str, Any], dict[str, Any]]] = ()) -> tuple[dict[str, Any], str, dict[str, str]]:
    """复制 2550 为新单据：主表、`keep` 中的明细（实体、源行），以及 `extra` 中复制后改过的明细（实体、源行、改的值）。
    返回单据、主表的临时编号和源明细主键 → 临时编号。"""
    regions = {d["entity"]: d for d in view["details"]}
    master_id = tmp()
    ids: dict[str, str] = {}
    details = []
    for entity, row, *changed in [*((e, r) for e, r in keep), *extra]:
        values = copied_values(regions[entity], row["values"])
        for change in changed:
            values.update(change)
        ids[row["rowKey"]] = tmp()
        details.append({"entity": entity, "op": "add", "clientRowId": ids[row["rowKey"]], "copyOf": row["rowKey"],
                        "values": values})
    master_values = {**copied_values(view["master"], record["master"]["values"]), "MEMO": MARKER}
    doc = {"entity": PAGE, "master": {"op": "add", "clientRowId": master_id, "copyOf": SOURCE, "values": master_values},
           "details": details}
    return doc, master_id, ids


def save(browser: Browser, cleanup: Cleanup, documents: list[dict[str, Any]]) -> httpx.Response:
    response = browser.post("/api/commands", save_command(cleanup.key(), documents))
    if response.status_code == 200:
        cleanup.result(response.json())
    return response


def pass_body(browser: Browser, cleanup: Cleanup, approval_id: str) -> dict[str, Any]:
    detail = browser.ok(browser.get(f"/api/approvals/{approval_id}"))
    return {"requestKey": cleanup.key(), "fingerprint": detail["fingerprint"], "checkedRows": [], "comment": "B2 复制审批通过",
            "params": {}}


def cells(block: dict[str, Any], column: str) -> list[tuple[Any, Any]]:
    index = block["columns"].index(column)
    return [(r["cells"][index]["before"], r["cells"][index]["after"]) for r in block["rows"]]


def without(row: dict[str, Any], names: set[str]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in names}


def calculated_columns(admin: Browser, entity: str) -> set[str]:
    """实体配置（d_cg 已发布的）中计算字段的列名（小写，同 `dcg.rows` 的键）。"""
    item = admin.ok(admin.get(f"/api/config/items/entity/{entity}"))
    return {f["column"].lower() for f in item["content"]["fields"] if f["role"] == "calculated" and f.get("column")}


def stored(value: Any) -> Any:
    """写库时数值最多保留 8 位小数、第 9 位四舍五入（WP-15）：源单据中超过 8 位的值（例如 2550 的 COST_PERQP
    13.929051856924948）复制后按这个规则存。"""
    if isinstance(value, int | float | Decimal) and not isinstance(value, bool):
        return D(str(value)).quantize(D("1e-8"), rounding=ROUND_HALF_UP).normalize()
    return value


# ---------------------------------------------------------------- 业务例子

def test_copied_document_approved_with_values_resolved_at_submission(admin: Browser, copier: Browser, dcg: Engine,
                                                                     cleanup: Cleanup, created: CreatedData) -> None:
    goodsid = created.add_erp_goods("10")
    view = copier.ok(copier.get(f"/api/pages/{PAGE}/view"))
    record = copier.ok(copier.get(f"/api/pages/{PAGE}/records/{SOURCE}"))
    source_rows = [(entity, row) for entity, found in record["details"].items() for row in found]
    prices = exec_prices(dcg, [str(r["values"]["GOODSID"]) for _, r in source_rows])
    priced = [(e, r) for e, r in source_rows
              if r["values"]["PRICE"] is not None and D(r["values"]["PRICE"]) == prices[str(r["values"]["GOODSID"])]]
    [stearate] = [(e, r) for e, r in source_rows if r["rowKey"] == STEARATE]
    assert len(priced) == 10 and D(stearate[1]["values"]["PRICE"]) == D(63)
    swapped = (*stearate, {"GOODSID": goodsid, "GOODSNAME": TEST_GOODS_NAME})

    # 同样复制、不进审批直接保存的一张（对照）
    plain_doc, plain_master, plain_ids = copy_document(view, record, priced)
    plain = save(copier, cleanup, [plain_doc])
    assert plain.status_code == 200 and plain.json()["outcome"] == "saved", plain.text
    plain_map = plain.json()["idMap"]
    plain_key = plain_map[plain_master]
    created.docids.append(plain_key)

    # 带测试物料那一行：进入审批
    doc, master_id, ids = copy_document(view, record, priced, [swapped])
    response = save(copier, cleanup, [doc])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["outcome"] == "approvalSubmitted", result
    [approval] = result["approvals"]
    approval_id = str(approval["approvalId"])
    assert approval["flows"] == ["COST_TO_GOODS"]
    stored_approval = json.loads(one(dcg, "SELECT pending FROM pf_approval WHERE approval_id = :a",
                                     a=int(approval_id))["pending"])
    key_map = stored_approval["keyMap"]  # 送审时取得的主键（AP-02）
    print(f"提交结果的 idMap：{result['idMap']}")
    bill = approval["document"]["recordKey"]
    assert key_map[master_id] == bill
    created.docids.append(bill)
    assert document(dcg, int(bill)) == (None, [])  # 审批结束前不写业务表
    freezes = {(r["root_table"], r["record_key"]) for r in rows(dcg, "SELECT root_table, record_key FROM pf_approval_freeze "
                                                                     "WHERE approval_id = :a", a=int(approval_id))}
    assert freezes == {("T_COST_PINGGU", bill), ("T_COST_GOODS", goodsid)}

    # 待审修改存的是保存这一刻按源行解出的值
    pending = stored_approval["patch"]
    [sent] = [d for d in doc["details"] if d["clientRowId"] == ids[STEARATE]]
    [kept] = [d for d in pending["details"] if d["clientRowId"] == ids[STEARATE]]
    print(f"审批 {approval_id}：新单据 {bill}，对照单据 {plain_key}；待审修改主表 {len(pending['master']['values'])} 个字段、"
          f"明细 {len(pending['details'])} 行；换成测试物料的那一行，命令中 {sorted(sent['values'])}，"
          f"待审修改中 {sorted(kept['values'])}")
    calculated = calculated_columns(admin, PAGE)
    assert pending["master"]["copyOf"] == SOURCE and pending["master"]["values"]["FMNAME"] == record["master"]["values"]["FMNAME"]
    assert not {n.lower() for n in pending["master"]["values"]} & calculated
    assert all("GOODSNAME" not in d["values"] and "COST_BATCH" not in d["values"] for d in pending["details"])

    # 审批详情
    detail = admin.ok(admin.get(f"/api/approvals/{approval_id}"))
    master_block = detail["view"]["master"]
    assert [r["op"] for r in master_block["rows"]] == ["add"]
    assert cells(master_block, "单据号") == [(None, bill)]
    assert cells(master_block, "产品") == [(None, record["master"]["values"]["GOODSNAME"])]
    blocks = {b["key"]: b for b in detail["view"]["details"]}
    material, package = blocks["material"], blocks["package"]
    assert {r["op"] for r in material["rows"] + package["rows"]} == {"add"}
    assert len(material["rows"]) + len(package["rows"]) == 11
    [trigger] = [r for r in material["rows"] if r["flows"] == ["COST_TO_GOODS"]]
    names = material["columns"].index("物料名称")
    assert trigger["cells"][names]["after"] == TEST_GOODS_NAME
    assert all(r["cells"][names]["after"] for r in material["rows"] + package["rows"])  # 名称按 Lookup 查出
    [goods_block] = detail["view"]["affected"]
    assert [r["ref"]["key"] for r in goods_block["rows"]] == [goodsid] and cells(goods_block, "单价")[0][1] == "63.00"

    # admin 通过：新单据写入
    passed = admin.post(f"/api/approvals/{approval_id}/pass", pass_body(admin, cleanup, approval_id))
    assert passed.status_code == 200, passed.text
    assert passed.json()["approvals"][0]["status"] == "approved"
    master, details = document(dcg, int(bill))
    plain_master_row, plain_details = document(dcg, int(plain_key))
    assert master is not None and plain_master_row is not None
    source_master, _ = document(dcg, int(SOURCE))
    assert source_master is not None
    # 复制的字段与 2550 相同（备注是测试标记），没复制的字段为空
    for name in pending["master"]["values"]:
        column = name.lower()
        if column in source_master and column != "memo":
            assert stored(master[column]) == stored(source_master[column]), name
    assert (master["fmname"], master["projectno"], master["memo"]) == (source_master["fmname"], None, MARKER)
    # 与不进审批直接保存的那张逐列相同（主表；明细为那 10 行）
    skip_master = {"docid", *SYSDATE_COLUMNS, *calculated}
    assert without(master, skip_master) == without(plain_master_row, skip_master)
    detail_calculated = calculated_columns(admin, "COST_MATERIAL") | calculated_columns(admin, "COST_PACKAGE")
    skip_detail = {"dtlid", "docid", *detail_calculated}
    by_key = {str(r["dtlid"]): r for r in details}
    plain_by_key = {str(r["dtlid"]): r for r in plain_details}
    for _, row in priced:
        mine = by_key[key_map[ids[row["rowKey"]]]]
        theirs = plain_by_key[plain_map[plain_ids[row["rowKey"]]]]
        assert without(mine, skip_detail) == without(theirs, skip_detail), row["rowKey"]
    added = by_key[key_map[ids[STEARATE]]]
    assert (str(added["goodsid"]), D(str(added["price"])), added["exadd_mater"]) == (goodsid, D(63), None)
    assert len(details) == 11 and len(plain_details) == 10
    assert D(str(one(dcg, "SELECT zx_price FROM t_cost_goods WHERE goodsid = :g", g=int(goodsid))["zx_price"])) == D(63)

    # 经平台删掉两张测试成本单（删除不在 COST_TO_GOODS 的 operations 中，不进审批）
    removed = save(copier, cleanup, [{"entity": PAGE, "master": {"op": "delete", "rowKey": key}, "details": []}
                                         for key in (bill, plain_key)])
    assert removed.status_code == 200 and removed.json()["outcome"] == "saved", removed.text
    assert document(dcg, int(bill)) == (None, []) and document(dcg, int(plain_key)) == (None, [])
