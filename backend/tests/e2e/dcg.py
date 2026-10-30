"""真实联调用的 d_cg 读取、成本核算的保存命令和测试数据清理。

业务数据由各测试"改了再改回"或自己建、自己删；测试产生的平台记录由 `Cleanup` 在结束时删掉：本测试发起的审批
（PF_APPROVAL、PF_APPROVAL_AFFECTED、PF_APPROVAL_RECORD、PF_APPROVAL_FREEZE）、命令产生的投递和站内通知
（PF_DELIVERY、PF_INBOX）和命令记录（PF_COMMAND），以及测试建的账号（PF_USER、PF_USER_ROLE）。
还在审批中的审批一起删掉时，它的待审修改从没写进业务表，冻结记录也删掉，单据恢复为可修改。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Engine, bindparam, text

from cost_platform.assembly.settings import Settings
from cost_platform.db_core.engine import create_oracle_engine

PAGE = "COST_PINGGU"
SAVE = "COST_PINGGU.save"


def oracle_engine() -> Engine:
    s = Settings.load()
    return create_oracle_engine(s.db_user, s.db_password, s.db_dsn)


def rows(engine: Engine, sql: str, **binds: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), binds).mappings()]


def one(engine: Engine, sql: str, **binds: Any) -> dict[str, Any]:
    [found] = rows(engine, sql, **binds)
    return found


def document(engine: Engine, docid: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """成本单的主表行和明细表行（T_COST_PINGGU、T_COST_PINGGU_DTL，按 DTLID 排序）。"""
    master = rows(engine, "SELECT * FROM t_cost_pinggu WHERE docid = :d", d=docid)
    details = rows(engine, "SELECT * FROM t_cost_pinggu_dtl WHERE docid = :d ORDER BY dtlid", d=docid)
    return (master[0] if master else None), details


def goods(engine: Engine, goodsid: int) -> dict[str, Any]:
    return one(engine, "SELECT * FROM t_cost_goods WHERE goodsid = :g", g=goodsid)


def save_command(request_key: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
    return {"requestKey": request_key, "page": PAGE, "operation": SAVE, "params": {}, "documents": documents}


def detail_change(docid: str, entity: str, rowkey: str, changes: dict[str, Any],
                  master: dict[str, Any] | None = None) -> dict[str, Any]:
    """一张成本单的修改：明细一行的 changes，主表默认不改。"""
    return {"entity": PAGE, "master": master or {"op": "none", "rowKey": docid},
            "details": [{"entity": entity, "op": "modify", "rowKey": rowkey, "changes": changes}]}


class Cleanup:
    """记下本测试的请求键、审批和账号，`run()` 时删掉它们产生的平台记录。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.request_keys: list[str] = []
        self.approvals: list[str] = []
        self.users: list[str] = []

    def key(self) -> str:
        key = str(uuid.uuid4())
        self.request_keys.append(key)
        return key

    def result(self, result: dict[str, Any]) -> dict[str, Any]:
        """命令结果中提交的审批记下来。"""
        for approval in result.get("approvals", []):
            if approval["approvalId"] not in self.approvals:
                self.approvals.append(approval["approvalId"])
        return result

    def run(self) -> None:
        keys = bindparam("keys", expanding=True)
        ids = bindparam("ids", expanding=True)
        users = bindparam("users", expanding=True)
        with self.engine.begin() as conn:
            if self.request_keys:
                binds = {"keys": self.request_keys}
                conn.execute(text("DELETE FROM pf_inbox WHERE delivery_id IN "
                                  "(SELECT delivery_id FROM pf_delivery WHERE request_key IN :keys)").bindparams(keys), binds)
                conn.execute(text("DELETE FROM pf_delivery WHERE request_key IN :keys").bindparams(keys), binds)
                conn.execute(text("DELETE FROM pf_command WHERE request_key IN :keys").bindparams(keys), binds)
            if self.approvals:
                binds = {"ids": [int(i) for i in self.approvals]}
                for table in ("pf_approval_freeze", "pf_approval_record", "pf_approval_affected", "pf_approval"):
                    conn.execute(text(f"DELETE FROM {table} WHERE approval_id IN :ids").bindparams(ids), binds)
            if self.users:
                binds = {"users": [int(u) for u in self.users]}
                conn.execute(text("DELETE FROM pf_user_role WHERE user_id IN :users").bindparams(users), binds)
                conn.execute(text("DELETE FROM pf_user WHERE user_id IN :users").bindparams(users), binds)
