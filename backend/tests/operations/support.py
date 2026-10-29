"""operations 测试共用的配置、数据和替代实现（模拟验证）。

配置按成本核算页（COST_PINGGU 主表、COST_MATERIAL 原辅料明细）和物料清单（COST_GOODS_PRICE，ISERP 区分 ERP 行），
字段做了删减。数据取业务例子和任务卡 T-OP-1 中的单据：

- 成本单 D（2550）：原辅料 5001 物料 115 单价 80，5002 物料 116 单价 12（按钮"同步单价"的来源）；
- 成本单 A（2551）：6101 物料 115、6102 物料 116；成本单 B（2552）：6201 物料 116；
- 成本单 E（2553）：7001 物料 115、7002 物料 116、7003 物料 120（同时含 115 和 116）；
- 物料 115 为 ERP 行（ISERP=1），116 为本地行（ISERP=0）。

`Bench` 模拟 write-pipeline 在动作前后做的事（架构第 7 节第 4 步、WP-18），只为把本模块的阶段串起来：
加锁读取 = 从内存中的单据复制到 `current`；合并 intents = 所属单据不在 `involved` 的先读入，再把值写进 `candidate`。
它不做计算、写权限和冻结检查，这些由 write-pipeline、rules-core、approval 负责，联调（T-AS-5）时用真实实现验证。
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeConfigSnapshot, FakeRelatedQuery, FakeUnitOfWorkFactory
from cost_platform.contracts.ports import PipelineStage, UnitOfWork
from cost_platform.operations import ActionStage, ButtonInvolvedStage

PAGE = "COST_PINGGU"
GOODS_PAGE = "GOODS_PRICE_MANAGE"
MASTER = "COST_PINGGU"
MATERIAL = "COST_MATERIAL"
GOODS = "COST_GOODS_PRICE"
SYNC = "COST_PINGGU.syncUnitPrice"
BOM = "COST_PINGGU.generateFromBom"
NOW = datetime(2026, 10, 29, 10, 0, 0)
KEY = "00000000-0000-4000-8000-0000000000b1"

D, A, B, E = "2550", "2551", "2552", "2553"


def ref(key: str, entity: str = MASTER) -> t.DocumentRef:
    return t.DocumentRef(entity, key)


def fld(name: str, type_: t.FieldType = "number", *, role: t.FieldRole = "input", source: t.ColumnSource = "own",
        column: str | None | type[Ellipsis] = ...) -> t.EntityField:
    return t.parse_wire(t.EntityField, {"name": name, "column": name if column is ... else column, "label": name,
                                        "type": type_, "source": source, "role": role})


MASTER_ENTITY = t.EntityConfig(
    table="T_COST_PINGGU", primary_key="DOCID", freezable=True,
    fields=[fld("DOCID", role="system"), fld("GOODSID"), fld("GOODSNAME", "text", source="erp"), fld("MEMO", "text"),
            fld("TOTAL_COST", role="calculated")],
    details=[t.DetailLink(entity=MATERIAL, parent_key="DOCID")])

MATERIAL_ENTITY = t.EntityConfig(
    table="T_COST_PINGGU_DTL", primary_key="DTLID", freezable=True, read_view="V_COST_PINGGU_MATERIAL",
    fields=[fld("DTLID", role="system"), fld("DOCID", role="system"), fld("GOODSID"), fld("GOODSNAME", "text", column=None),
            fld("PRICE"), fld("COST_BATCH", role="calculated"), fld("MEMO", "text")])

GOODS_ENTITY = t.EntityConfig(
    table="T_COST_GOODS", primary_key="GOODSID", freezable=True, read_view="T_COST_GOODS_PRICE_V",
    erp_row=t.ErpRow(column="ISERP", value="1", local_value="0"),
    fields=[fld("GOODSID", role="system"), fld("GOODSNAME", "text", source="erp"), fld("ISERP", role="system"),
            fld("PRICE", source="erp"), fld("ZX_PRICE")])

ENTITIES = {MASTER: MASTER_ENTITY, MATERIAL: MATERIAL_ENTITY, GOODS: GOODS_ENTITY}

_GRID = t.GridOptions(side_bar=True, cell_selection=True, group_by=[])


def _view_fields(entity: t.EntityConfig) -> list[t.ViewField]:
    return [t.ViewField(name=f.name, label=f.label, type=f.type, scale=None, source=f.source,
                        calculated=f.role == "calculated", visible=True, editable=False, required=False, width=None,
                        pinned=None, dict_type=None, lookup=None) for f in entity.fields]


def button(operation: str, requires: bool = True, action: str | None = None) -> t.ViewButton:
    name = action or operation.split(".", 1)[1]
    return t.ViewButton(key=f"master:{name}", action=name, label=name, operation=operation, requires_selection=requires)


def cost_page_view(buttons: Sequence[t.ViewButton]) -> t.PageView:
    return t.PageView(
        page_code=PAGE, title="成本核算", version=1, layout="masterDetail", detail_mode="tabs", audit=True,
        save_operation=f"{PAGE}.save", rules_pack=t.PackRef(pack_id=PAGE, version=1),
        master=t.ViewMaster(entity=MASTER, primary_key="DOCID", fields=_view_fields(MASTER_ENTITY), buttons=list(buttons),
                            grid=_GRID, form_layout=[]),
        details=[t.ViewDetail(entity=MATERIAL, title="原辅料", primary_key="DTLID", parent_key="DOCID",
                              fields=_view_fields(MATERIAL_ENTITY), buttons=[], grid=_GRID, form_layout=[])],
        system_buttons=["save"])


def operation(actions: Sequence[dict[str, Any]], *, writable: dict[str, list[str]] | None = None,
              propagation: str = "continue", row_not_found: str = "skip", impact: Sequence[str] = (MASTER, MATERIAL),
              kind: str = "action", procedure: str | None = None, writes: dict[str, list[str]] | None = None,
              label: str = "同步单价") -> t.OperationConfig:
    """按 C06 第 4 节的 JSON 写法构造操作配置。"""
    content: dict[str, Any] = {"label": label, "kind": kind, "actions": list(actions), "propagation": propagation,
                               "rowNotFound": row_not_found, "impact": list(impact),
                               "writableFields": writable if writable is not None else {MATERIAL: ["PRICE"]}}
    if procedure is not None:
        content["procedure"] = procedure
    if writes is not None:
        content["writes"] = writes
    return t.parse_wire(t.OperationConfig, content)


def snapshot(operations: dict[str, t.OperationConfig], buttons: Sequence[t.ViewButton] | None = None) -> FakeConfigSnapshot:
    role = t.RoleConfig(name="成本会计", admin=False, pages={})
    views = {PAGE: cost_page_view(buttons if buttons is not None else [button(code) for code in operations])}
    return FakeConfigSnapshot(version=1, role_code="COST_ACCOUNTANT", role=role, page_views=views, entities=ENTITIES,
                              operations=operations)


def context(config: FakeConfigSnapshot, *, user_id: str = "112", name: str = "张三",
            origin: t.Origin | None = None) -> t.ExecutionContext:
    who = t.Identity(user_id=user_id, username=f"user{user_id}", display_name=name, department_id="10",
                     role_code="COST_ACCOUNTANT", session_id=f"s-{user_id}")
    return t.ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=who, config=config,
                              config_version=1, origin=origin or t.Origin(kind="user", approval_id=None), now=NOW)


def command(op: str, selected: Iterable[tuple[str, str]] = (), *, documents: list[dict[str, Any]] | None = None,
            params: dict[str, Any] | None = None, request_key: str = KEY) -> t.Command:
    body = {"selectedRows": [{"entity": e, "rowKey": k} for e, k in selected], **(params or {})}
    return t.parse_wire(t.Command, {"requestKey": request_key, "page": PAGE, "operation": op,
                                    "documents": documents or [], "params": body})


# ---------------------------------------------------------------- 数据

def _row(entity: str, key: str, **values: Any) -> t.Row:
    return t.Row(entity=entity, row_key=key, client_row_id=None,
                 values={k: (Decimal(v) if isinstance(v, int | str) and k not in ("GOODSNAME", "MEMO") else v)
                         for k, v in values.items()})


def material(key: str, doc: str, goods: int, price: str) -> t.Row:
    names = {115: "硬脂酸镁", 116: "聚维酮K30", 120: "玉米淀粉"}
    return _row(MATERIAL, key, DTLID=key, DOCID=doc, GOODSID=goods, GOODSNAME=names.get(goods, "物料"), PRICE=price,
                COST_BATCH="0", MEMO=None)


def cost_doc(key: str, rows: Sequence[t.Row], product: int = 900) -> t.DocumentData:
    master = _row(MASTER, key, DOCID=key, GOODSID=product, GOODSNAME="250mg乙酰唑胺片", MEMO=None, TOTAL_COST="0")
    return t.DocumentData(ref=ref(key), master=master, details={MATERIAL: list(rows)})


def goods_doc(key: str, iserp: int, price: str) -> t.DocumentData:
    row = _row(GOODS, key, GOODSID=key, GOODSNAME="物料", ISERP=iserp, PRICE=price, ZX_PRICE=price)
    return t.DocumentData(ref=ref(key, GOODS), master=row, details={})


def documents() -> dict[t.DocumentRef, t.DocumentData]:
    docs = [
        cost_doc(D, [material("5001", D, 115, "80"), material("5002", D, 116, "12")]),
        cost_doc(A, [material("6101", A, 115, "75"), material("6102", A, 116, "10")]),
        cost_doc(B, [material("6201", B, 116, "11")]),
        cost_doc(E, [material("7001", E, 115, "70"), material("7002", E, 116, "9"), material("7003", E, 120, "5")]),
        goods_doc("115", 1, "75"),
        goods_doc("116", 0, "10"),
    ]
    return {d.ref: d for d in docs}


# ---------------------------------------------------------------- 关联 SQL（C06 6.1 的写法）

def detail_sql_finder() -> t.SqlFinder:
    """按物料编号找其他成本单的原辅料明细（绑定明细字段，逐行执行）。"""
    return t.parse_wire(t.SqlFinder, {
        "kind": "sql", "entity": MATERIAL,
        "sql": "SELECT D.DOCID AS DOC_ID, D.DTLID AS DTL_ID FROM T_COST_PINGGU_DTL D "
               "WHERE D.GOODSID = :goodsId AND D.DOCID <> :docId ORDER BY D.DOCID, D.DTLID",
        "binds": {"goodsId": f"{MATERIAL}.GOODSID", "docId": f"{MASTER}.DOCID"},
        "recordKeyColumn": "DOC_ID", "rowKeyColumns": ["DTL_ID"]})


def document_sql_finder() -> t.SqlFinder:
    """按物料编号找含这个物料的其他成本单（整张单据）。"""
    return t.parse_wire(t.SqlFinder, {
        "kind": "sql", "entity": MASTER,
        "sql": "SELECT DISTINCT D.DOCID AS DOC_ID FROM T_COST_PINGGU_DTL D "
               "WHERE D.GOODSID = :goodsId AND D.DOCID <> :docId ORDER BY D.DOCID",
        "binds": {"goodsId": f"{MATERIAL}.GOODSID", "docId": f"{MASTER}.DOCID"},
        "recordKeyColumn": "DOC_ID"})


def goods_key_finder() -> t.RelationKeyFinder:
    """按关联键找物料清单：物料清单的 GOODSID = 原辅料的 GOODSID。"""
    return t.parse_wire(t.RelationKeyFinder, {"kind": "relationKey", "entity": GOODS, "targetKey": "GOODSID",
                                              "sourceKey": f"{MATERIAL}.GOODSID", "rows": "all"})


def detail_target(doc: str, row: str) -> t.TargetObject:
    return t.TargetObject(entity=MATERIAL, record_key=doc, row_keys=(row,), display={}, missing=False)


def register_selection(related: FakeRelatedQuery, docs: dict[t.DocumentRef, t.DocumentData]) -> None:
    """按明细主键找所属单据（选中明细行时，SelectionResolver 经 RelatedQuery 查）。"""
    for data in docs.values():
        for row in data.details.get(MATERIAL, []):
            related.add_target(MATERIAL, "DTLID", row.values["DTLID"], detail_target(data.ref.record_key, row.row_key or ""))


# ---------------------------------------------------------------- 把阶段串起来

@dataclass
class Bench:
    """一个命令的测试台：本模块的两个阶段，加上模拟的加锁读取和 intents 合并（见文件开头的说明）。"""

    config: FakeConfigSnapshot
    related: FakeRelatedQuery = field(default_factory=FakeRelatedQuery)
    docs: dict[t.DocumentRef, t.DocumentData] = field(default_factory=documents)
    stage: ActionStage | None = None
    setup_sql: Sequence[str] = ()
    """开启命令事务之前在替代数据库（内存 SQLite）中执行的语句，例如建逃生舱要写的表。"""
    merged: list[t.RowIntent] = field(default_factory=list)
    """每一轮合并的 intents，按先后。"""

    def __post_init__(self) -> None:
        self._stack = ExitStack()
        self.factory = FakeUnitOfWorkFactory()
        with self.factory.engine.connect() as connection:
            for sql in self.setup_sql:
                connection.exec_driver_sql(sql)
            connection.commit()
        self.uow: UnitOfWork = self._stack.enter_context(self.factory.begin())
        register_selection(self.related, self.docs)
        self.involved = ButtonInvolvedStage(self.related)
        if self.stage is None:
            self.stage = ActionStage(self.related)

    def close(self) -> None:
        self._stack.close()

    def ctx(self, **kwargs: Any) -> t.ExecutionContext:
        return context(self.config, **kwargs)

    def lock(self, state: t.CommandState, refs: Iterable[t.DocumentRef] | None = None) -> None:
        """模拟加锁读取：读入 `involved` 中还没有读入的单据；不存在的从 `involved` 去掉。"""
        for r in list(refs if refs is not None else state.involved):
            if r in state.current:
                continue
            if r in self.docs:
                state.current[r] = copy.deepcopy(self.docs[r])
            else:
                state.involved.remove(r)

    def absorb(self, state: t.CommandState) -> None:
        """模拟 WP-18：所属单据不在 `involved` 的先加入并读入，再把 intents 的值写进候选数据，清空 intents。"""
        outside = [i.document for i in state.intents if i.document not in state.involved]
        for r in dict.fromkeys(outside):
            state.involved.append(r)
        self.lock(state, outside)
        for intent in state.intents:
            if intent.document not in state.current:
                continue
            doc = state.candidate.setdefault(intent.document, copy.deepcopy(state.current[intent.document]))
            rows = [doc.master] if intent.entity == intent.document.entity else doc.details.get(intent.entity, [])
            for row in rows:
                if row.row_key == intent.row_key:
                    row.values.update(intent.values)
        self.merged += state.intents
        state.intents.clear()

    def prepare(self, cmd: t.Command, ctx: t.ExecutionContext | None = None) -> t.CommandState:
        """确定涉及的单据 → 加锁读取。"""
        ctx = ctx or self.ctx()
        state = t.CommandState(command=cmd)
        if self.involved.applies(state, ctx):
            self.involved.run(self.uow, state, ctx)
        self.lock(state)
        return state

    def run(self, cmd: t.Command, ctx: t.ExecutionContext | None = None,
            stages: Sequence[PipelineStage] = ()) -> t.CommandState:
        """完整的一次：确定涉及的单据 → 加锁读取 → 每个动作一轮（展开 → 合并）。"""
        ctx = ctx or self.ctx()
        state = self.prepare(cmd, ctx)
        assert self.stage is not None
        while self.stage.applies(state, ctx):
            self.stage.run(self.uow, state, ctx)
            self.absorb(state)
        return state


def writes(intents: Iterable[t.RowIntent]) -> list[tuple[str, str, str, dict[str, Any]]]:
    """intents 的简写：（所属单据、实体、行主键、要写的值）。"""
    return [(i.document.record_key, i.entity, i.row_key or "", dict(i.values)) for i in intents]
