"""样例二（C06 7.9 TECH_CUSTOMER_MATERIAL、7.10 GOODS_TO_COST）真实联调用的测试数据：自己建、自己删。

d_cg 的业务数据不改：两个审批流涉及的单据都由这里新建，结束时删掉。
- 7.9：admin 经平台新建一张"评估中"的成本单，原辅料两行：硬脂酸镁（物料 115，客户指定）、玉米淀粉（310，不是客户指定），
  单价都等于物料清单的单价（执行价为空时取参考价格，115 为 75、310 为 22），不触发 COST_TO_GOODS。
- 7.10：物料清单里新增一个 ERP 物料（模拟 ERP 同步写入：ISERP = 1、UPDATE_BY = 'ERP_SYNC'，参考价格 10、执行价为空，
  用途"辅料"），主键取 T_COST_GOODS_SEQ；admin 经平台新建两张成本单 D1、D2，各有一行这个物料（每片含量 10、单价 10）；
  液体成本核算没有在平台注册（只有表和视图），液体主表、明细各一行直接写 SQL（T_COST_PINGGU_LQ_SEQ、T_COST_PINGGU_DTL_LQ_SEQ）。
- 删除：成本单经平台删除（`delete_documents`）；平台删不了的（ERP 物料：删除满足 approvalRequired 条件的行必须审批，
  液体成本没注册）和中途失败留下的，由 `drop_all` 直接按主键删。

用到的物料单价在运行时从 T_COST_GOODS_PRICE_V 读出，不写死。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text

from .dcg import one, rows

D = Decimal
PAGE = "COST_PINGGU"
SAVE = "COST_PINGGU.save"
GOODS_PAGE = "GOODS_PRICE_MANAGE"
GOODS_SAVE = "GOODS_PRICE_MANAGE.save"
GOODS_ENTITY = "COST_GOODS_PRICE"
TEST_GOODS_NAME = "H5联调辅料"
MASTER_VALUES = {"APEX_PL": "1000000", "P_PERPACK": "112", "S_PERBACK": "80", "YIELD": "93.94"}


def tmp() -> str:
    return f"tmp-{uuid.uuid4()}"


def list_price(engine: Engine, goodsid: int | str) -> str:
    """物料清单的单价：视图 T_COST_GOODS_PRICE_V 的 ZX_PRICE（执行价为空时取参考价格）。"""
    found = one(engine, "SELECT zx_price FROM t_cost_goods_price_v WHERE goodsid = :g", g=int(goodsid))["zx_price"]
    return format(D(str(found)).normalize(), "f")


def new_document(memo: str, materials: list[dict[str, Any]], **master: str) -> tuple[dict[str, Any], str, list[str]]:
    """一张新成本单：主表取 G5 用过的批量、包装规格等，原辅料为这些新增行。返回单据和主表、各明细的临时编号。"""
    master_id, detail_ids = tmp(), [tmp() for _ in materials]
    doc = {"entity": PAGE, "master": {"op": "add", "clientRowId": master_id, "values": {"MEMO": memo, **MASTER_VALUES, **master}},
           "details": [{"entity": "COST_MATERIAL", "op": "add", "clientRowId": i, "values": v} for i, v in zip(detail_ids, materials,
                                                                                                          strict=True)]}
    return doc, master_id, detail_ids


def command(request_key: str, page: str, operation: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
    return {"requestKey": request_key, "page": page, "operation": operation, "params": {}, "documents": documents}


@dataclass
class CreatedData:
    """本次运行建的数据：成本单、ERP 物料、液体成本单的主键。"""

    engine: Engine
    docids: list[str] = field(default_factory=list)
    goodsids: list[str] = field(default_factory=list)
    lq_docids: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """几张业务表的行数（建数据前、删掉后核对）。"""
        found = {}
        for table in ("t_cost_pinggu", "t_cost_pinggu_dtl", "t_cost_goods", "t_cost_pinggu_lq", "t_cost_pinggu_dtl_lq"):
            found[table] = int(one(self.engine, f"SELECT COUNT(*) AS n FROM {table}")["n"])
        return found

    def add_erp_goods(self, price: str) -> str:
        """模拟 ERP 同步新增一个 ERP 物料（旧 PROC_SYNC_GOODS_PRICE 的 INSERT：ISERP = 1、UPDATE_BY = 'ERP_SYNC'）。"""
        with self.engine.begin() as conn:
            goodsid = str(conn.execute(text("SELECT t_cost_goods_seq.NEXTVAL FROM dual")).scalar_one())
            conn.execute(text("INSERT INTO t_cost_goods (goodsid, goodsname, price, useflag, iserp, update_by) "
                              "VALUES (:g, :n, :p, '辅料', 1, 'ERP_SYNC')"), {"g": int(goodsid), "n": TEST_GOODS_NAME, "p": D(price)})
        self.goodsids.append(goodsid)
        return goodsid

    def add_liquid(self, goodsid: str, per_hl: str, price: str, batch_qty: str, cost_batch: str) -> tuple[str, str]:
        """液体成本单一张，明细一行这个物料（液体成本核算没有在平台注册，直接写表）。"""
        with self.engine.begin() as conn:
            docid = str(conn.execute(text("SELECT t_cost_pinggu_lq_seq.NEXTVAL FROM dual")).scalar_one())
            dtlid = str(conn.execute(text("SELECT t_cost_pinggu_dtl_lq_seq.NEXTVAL FROM dual")).scalar_one())
            conn.execute(text("INSERT INTO t_cost_pinggu_lq (docid, goodsname, memo) VALUES (:d, 'H5联调液体单', 'H5 联调样例三')"),
                         {"d": int(docid)})
            conn.execute(text("INSERT INTO t_cost_pinggu_dtl_lq (dtlid, docid, goodsid, per_hl, price, batch_qty, cost_batch) "
                              "VALUES (:t, :d, :g, :h, :p, :q, :c)"),
                         {"t": int(dtlid), "d": int(docid), "g": int(goodsid), "h": D(per_hl), "p": D(price), "q": D(batch_qty),
                          "c": D(cost_batch)})
        self.lq_docids.append(docid)
        return docid, dtlid

    def drop_all(self) -> None:
        """直接按主键删掉本次建的全部数据（已经删掉的不影响）。"""
        with self.engine.begin() as conn:
            for docid in self.docids:
                conn.execute(text("DELETE FROM t_cost_pinggu_dtl WHERE docid = :d"), {"d": int(docid)})
                conn.execute(text("DELETE FROM t_cost_pinggu WHERE docid = :d"), {"d": int(docid)})
            for docid in self.lq_docids:
                conn.execute(text("DELETE FROM t_cost_pinggu_dtl_lq WHERE docid = :d"), {"d": int(docid)})
                conn.execute(text("DELETE FROM t_cost_pinggu_lq WHERE docid = :d"), {"d": int(docid)})
            for goodsid in self.goodsids:
                conn.execute(text("DELETE FROM t_cost_goods WHERE goodsid = :g"), {"g": int(goodsid)})


def master_row(engine: Engine, docid: str) -> dict[str, Any] | None:
    found = rows(engine, "SELECT * FROM t_cost_pinggu WHERE docid = :d", d=int(docid))
    return found[0] if found else None


def detail_rows(engine: Engine, docid: str) -> list[dict[str, Any]]:
    return rows(engine, "SELECT * FROM t_cost_pinggu_dtl WHERE docid = :d ORDER BY dtlid", d=int(docid))


def goods_row(engine: Engine, goodsid: str) -> dict[str, Any]:
    return one(engine, "SELECT * FROM t_cost_goods WHERE goodsid = :g", g=int(goodsid))


def liquid_row(engine: Engine, dtlid: str) -> dict[str, Any]:
    return one(engine, "SELECT * FROM t_cost_pinggu_dtl_lq WHERE dtlid = :t", t=int(dtlid))


def freezes(engine: Engine, approval_id: str) -> set[tuple[str, str]]:
    return {(r["root_table"], r["record_key"]) for r in rows(engine, "SELECT root_table, record_key FROM pf_approval_freeze "
                                                                     "WHERE approval_id = :a", a=int(approval_id))}
