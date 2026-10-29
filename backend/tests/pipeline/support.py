"""write-pipeline 测试共用的配置、执行上下文和替代实现（模拟验证）。

配置取自成本核算页（`backend/seed/config` 的 COST_PINGGU、COST_MATERIAL，字段做了删减）和物料清单（业务例子 E08、
C06 第 2 节的 ISERP 写法）。数据取业务例子中的单据：成本单 1001 的原辅料 5001（PRICE 3.50、USAGE 2）、5002；
物料 115（ISERP=1）、116（ISERP=0）。

- `MemoryStore`：`RowStore`（pipeline.document_store）的内存替代实现，按实体保存行，记录每次写入，供合并、计算、
  写入顺序和命令结果的测试使用。真实的 SQL 由 `test_document_store_sql.py` 核对文本，由 oracle 测试在 d_cg 上验证。
- `Pipeline`：按 orchestration 的执行方式（`STAGE_ORDER`，plugin-spec 第 3 节）执行本模块的管道阶段，其他模块的阶段
  用替代实现。
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import (
    FakeConfigSnapshot,
    FakePermissionChecker,
    FakeRulesEngine,
    FakeSchemaInspector,
    FakeUnitOfWorkFactory,
)
from cost_platform.contracts.ports import PipelineStage, UnitOfWork
from cost_platform.contracts.values import to_wire
from cost_platform.orchestration.runner import STAGE_ORDER

PAGE = "COST_PINGGU"
SAVE = "COST_PINGGU.save"
MASTER = "COST_PINGGU"
MATERIAL = "COST_MATERIAL"
GOODS = "COST_GOODS"
GOODS_PAGE = "GOODS_PRICE_MANAGE"
GOODS_SAVE = "GOODS_PRICE_MANAGE.save"
BUTTON = "COST_PINGGU.syncPrice"

KEY_1 = "00000000-0000-4000-8000-0000000000a1"
KEY_2 = "00000000-0000-4000-8000-0000000000a2"
TMP_1 = "tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d"
TMP_2 = "tmp-7b2f3d4e-1c5f-4a6b-9d8e-0f1a2b3c4d5e"
NOW = datetime(2026, 10, 29, 10, 0, 0)


def fld(name: str, type_: t.FieldType = "text", *, role: t.FieldRole = "input", source: t.ColumnSource = "own",
        column: str | None | type[Ellipsis] = ..., default: Any = None) -> t.EntityField:
    data: dict[str, Any] = {"name": name, "column": name if column is ... else column, "label": name, "type": type_,
                            "source": source, "role": role}
    if default is not None:
        data["default"] = default
    return t.parse_wire(t.EntityField, data)


MASTER_ENTITY = t.EntityConfig(
    table="T_COST_PINGGU", primary_key="DOCID", freezable=True,
    fields=[
        fld("DOCID", "number", role="system"),
        fld("GOODSNAME"),
        fld("MEMO"),
        fld("APEX_PL", "number"),
        fld("TOTAL_COST", "number", role="calculated"),
        fld("CREATE_BY", default={"type": "builtin", "value": "currentUserName"}),
        fld("USESTATUS", default={"type": "options", "value": ["草稿", "已提交"]}),
        fld("CREATE_TIME", "datetime", role="system", default={"type": "builtin", "value": "currentTime"}),
    ],
    details=[t.DetailLink(entity=MATERIAL, parent_key="DOCID")],
    field_defaults={"GOODSNAME": t.FieldFlags(editable=False), "CREATE_BY": t.FieldFlags(editable=False)},
)

MATERIAL_ENTITY = t.EntityConfig(
    table="T_COST_PINGGU_DTL", primary_key="DTLID", freezable=True, read_view="V_COST_PINGGU_MATERIAL",
    fields=[
        fld("DTLID", "number", role="system"),
        fld("DOCID", "number", role="system"),
        fld("GOODSID", "number"),
        fld("GOODSNAME", column=None),
        fld("USAGE", "number"),
        fld("PRICE", "number"),
        fld("COST_BATCH", "number", role="calculated"),
        fld("MEMO"),
    ],
)

GOODS_ENTITY = t.EntityConfig(
    table="T_COST_GOODS", primary_key="GOODSID", freezable=True, read_view="T_COST_GOODS_PRICE_V",
    erp_row=t.ErpRow(column="ISERP", value="1", local_value="0"),
    fields=[
        fld("GOODSID", "number", role="system"),
        fld("NAME", source="erp"),
        fld("ISERP", "number", role="system"),
        fld("PRICE", "number", source="erp"),
        fld("ZX_PRICE", "number"),
    ],
)

ENTITIES = {MASTER: MASTER_ENTITY, MATERIAL: MATERIAL_ENTITY, GOODS: GOODS_ENTITY}


def view_fields(entity: t.EntityConfig, editable: Iterable[str], required: Iterable[str] = ()) -> list[t.ViewField]:
    editable, required = set(editable), set(required)
    return [t.ViewField(name=f.name, label=f.label, type=f.type, scale=None, source=f.source,
                        calculated=f.role == "calculated", visible=True, editable=f.name in editable,
                        required=f.name in required, width=None, pinned=None, dict_type=None, lookup=None)
            for f in entity.fields]


_GRID = t.GridOptions(side_bar=True, cell_selection=True, group_by=[])

MASTER_WRITABLE = ("MEMO", "APEX_PL", "USESTATUS")
MATERIAL_WRITABLE = ("GOODSID", "USAGE", "PRICE", "MEMO")
GOODS_WRITABLE = ("PRICE", "ZX_PRICE", "NAME")


def cost_page_view(audit: bool = True, required: dict[str, list[str]] | None = None) -> t.PageView:
    required = required or {}
    return t.PageView(
        page_code=PAGE, title="成本核算", version=1, layout="masterDetail", detail_mode="tabs", audit=audit,
        save_operation=SAVE, rules_pack=t.PackRef(pack_id=PAGE, version=1),
        master=t.ViewMaster(entity=MASTER, primary_key="DOCID", fields=view_fields(MASTER_ENTITY, MASTER_WRITABLE,
                                                                                      required.get(MASTER, [])),
                            buttons=[], grid=_GRID, form_layout=[]),
        details=[t.ViewDetail(entity=MATERIAL, title="原料/辅料", primary_key="DTLID", parent_key="DOCID",
                              fields=view_fields(MATERIAL_ENTITY, MATERIAL_WRITABLE, required.get(MATERIAL, [])),
                              buttons=[], grid=_GRID, form_layout=[])],
        system_buttons=["save", "addRow", "deleteRow"])


def goods_page_view() -> t.PageView:
    return t.PageView(
        page_code=GOODS_PAGE, title="物料清单", version=1, layout="single", detail_mode="tabs", audit=False,
        save_operation=GOODS_SAVE, rules_pack=t.PackRef(pack_id=GOODS_PAGE, version=1),
        master=t.ViewMaster(entity=GOODS, primary_key="GOODSID", fields=view_fields(GOODS_ENTITY, GOODS_WRITABLE),
                            buttons=[], grid=_GRID, form_layout=[], erp_row=GOODS_ENTITY.erp_row),
        details=[], system_buttons=["save"])


def save_operation(row_not_found: str = "skip") -> t.OperationConfig:
    return t.OperationConfig(label="保存", kind="save", row_not_found=row_not_found, propagation="continue")  # type: ignore[arg-type]


EMPTY_PACK = json.dumps({"packId": PAGE, "version": 1, "coreVersion": "0.1.0", "fields": {}, "rules": [], "jdm": {}}).encode()


@dataclass
class Setup:
    """一次测试的配置、权限和规则引擎。"""

    engine: FakeRulesEngine = field(default_factory=FakeRulesEngine)
    permission: FakePermissionChecker = field(default_factory=FakePermissionChecker)
    audit: bool = True
    row_not_found: str = "skip"
    required: dict[str, list[str]] = field(default_factory=dict)
    rule_fields: dict[str, dict[str, frozenset[str]]] | None = None
    """保存时规则读取的字段（ConfigSnapshot.rule_fields）；不给时按"规则读取全部字段"，每次保存都求值。"""

    def __post_init__(self) -> None:
        self.permission.set_writable(PAGE, MASTER, MASTER_WRITABLE)
        self.permission.set_writable(PAGE, MATERIAL, MATERIAL_WRITABLE)
        self.permission.set_writable(GOODS_PAGE, GOODS, GOODS_WRITABLE)
        self.pack = self.engine.load_pack(EMPTY_PACK)

    def snapshot(self) -> FakeConfigSnapshot:
        role = t.RoleConfig(name="成本会计", admin=False, pages={})
        operations = {SAVE: save_operation(self.row_not_found), GOODS_SAVE: save_operation(self.row_not_found),
                      BUTTON: t.OperationConfig(label="同步价格", kind="action", propagation="continue",
                                                row_not_found=self.row_not_found)}  # type: ignore[arg-type]
        return FakeConfigSnapshot(version=1, role_code="COST_ACCOUNTANT", role=role,
                                  page_views={PAGE: cost_page_view(self.audit, self.required), GOODS_PAGE: goods_page_view()},
                                  entities=ENTITIES, operations=operations,
                                  packs={PAGE: self.pack, GOODS_PAGE: self.pack, MASTER: self.pack, GOODS: self.pack},
                                  rule_fields=self.rule_fields)

    def context(self, user_id: str = "112", display_name: str = "张三", *,
                origin: t.Origin | None = None) -> t.ExecutionContext:
        identity = t.Identity(user_id=user_id, username=f"user{user_id}", display_name=display_name, department_id="10",
                              role_code="COST_ACCOUNTANT", session_id=f"s-{user_id}")
        snapshot = self.snapshot()
        return t.ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=identity, config=snapshot,
                                  config_version=1, origin=origin or t.Origin(kind="user", approval_id=None), now=NOW)


def command(documents: list[dict[str, Any]], *, request_key: str = KEY_1, page: str | None = PAGE,
            operation: str = SAVE, params: dict[str, Any] | None = None) -> t.Command:
    return t.parse_wire(t.Command, {"requestKey": request_key, "page": page, "operation": operation,
                                    "documents": documents, "params": params or {}})


def master_none(record_key: str, details: list[dict[str, Any]], entity: str = MASTER) -> dict[str, Any]:
    return {"entity": entity, "master": {"op": "none", "rowKey": record_key}, "details": details}


def master_modify(record_key: str, changes: dict[str, Any], entity: str = MASTER,
                  details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"entity": entity, "master": {"op": "modify", "rowKey": record_key, "changes": changes}, "details": details or []}


# ---------------------------------------------------------------- 内存中的业务表

def initial_rows() -> dict[str, dict[str, dict[str, Any]]]:
    """业务例子中的数据：成本单 1001（两条原辅料）、1002（一条）；物料 115（ERP 行）、116（本地行）。"""
    d = Decimal
    return {
        MASTER: {
            "1001": {"DOCID": d(1001), "GOODSNAME": "250mg乙酰唑胺片", "MEMO": None, "APEX_PL": d("100000"),
                     "TOTAL_COST": d("54.00"), "CREATE_BY": "王五", "USESTATUS": "草稿", "CREATE_TIME": datetime(2026, 1, 5, 9, 0)},
            "1002": {"DOCID": d(1002), "GOODSNAME": "硝苯地平片", "MEMO": "旧备注", "APEX_PL": d("50000"),
                     "TOTAL_COST": d("12.00"), "CREATE_BY": "王五", "USESTATUS": "草稿", "CREATE_TIME": datetime(2026, 1, 6, 9, 0)},
        },
        MATERIAL: {
            "5001": {"DTLID": d(5001), "DOCID": d(1001), "GOODSID": d(115), "GOODSNAME": "硬脂酸镁", "USAGE": d("2.0000"),
                     "PRICE": d("3.50"), "COST_BATCH": d("7.00"), "MEMO": None},
            "5002": {"DTLID": d(5002), "DOCID": d(1001), "GOODSID": d(116), "GOODSNAME": "聚维酮K30", "USAGE": d("1"),
                     "PRICE": d("47.00"), "COST_BATCH": d("47.00"), "MEMO": None},
            "5101": {"DTLID": d(5101), "DOCID": d(1002), "GOODSID": d(115), "GOODSNAME": "硬脂酸镁", "USAGE": d("4"),
                     "PRICE": d("3.00"), "COST_BATCH": d("12.00"), "MEMO": None},
        },
        GOODS: {
            "115": {"GOODSID": d(115), "NAME": "硬脂酸镁", "ISERP": d(1), "PRICE": d("3.50"), "ZX_PRICE": d("3.50")},
            "116": {"GOODSID": d(116), "NAME": "聚维酮K30", "ISERP": d(0), "PRICE": d("47.00"), "ZX_PRICE": d("47.00")},
        },
    }


@dataclass
class Write:
    """`MemoryStore` 收到的一次写入。"""

    op: str
    entity: str
    rows: list[dict[str, Any]]


class MemoryStore:
    """`RowStore` 的内存替代实现：行按实体保存，键为主键文本；新增行的主键从 9001 起依次分配。"""

    def __init__(self, rows: dict[str, dict[str, dict[str, Any]]] | None = None) -> None:
        self.rows = rows if rows is not None else initial_rows()
        self.writes: list[Write] = []
        self.locked: list[tuple[str, list[str]]] = []
        self.detail_loads: list[list[str]] = []
        """每次读明细时的单据主键（一次读取一条语句）。"""
        self.denied: set[tuple[str, str]] = set()
        self._next = 9001

    def _code(self, entity: t.EntityConfig) -> str:
        return next(code for code, e in ENTITIES.items() if e is entity or e == entity)

    def _row(self, code: str, key: str) -> t.Row:
        return t.Row(entity=code, row_key=key, client_row_id=None, values=copy.deepcopy(self.rows[code][key]))

    def lock_load(self, uow: UnitOfWork, entity_code: str, entity: t.EntityConfig, row_keys: list[str],
                  row_condition: t.SqlCondition | None = None) -> dict[str, t.Row]:
        keys = sorted(set(row_keys), key=int)
        self.locked.append((entity_code, keys))
        found = {k: self._row(entity_code, k) for k in keys if k in self.rows[entity_code]}
        if row_condition is not None:
            outside = [k for k in found if (entity_code, k) in self.denied]
            if outside:
                raise t.PlatformError(t.ErrorCode.PERMISSION_DENIED, "超出行权限",
                                      [t.ErrorDetail(entity=entity_code, row_key=k) for k in outside])
        return found

    def load_details_many(self, uow: UnitOfWork, sources: Sequence[Any], record_keys: Sequence[str]) -> dict[str, dict[str, list[t.Row]]]:
        self.detail_loads.append(list(record_keys))
        result: dict[str, dict[str, list[t.Row]]] = {}
        for source in sources:
            by_record: dict[str, list[t.Row]] = {k: [] for k in record_keys}
            for key in sorted(self.rows[source.entity_code], key=int):
                parent = str(to_wire("number", self.rows[source.entity_code][key][source.parent_key]))
                if parent in by_record:
                    by_record[parent].append(self._row(source.entity_code, key))
            result[source.entity_code] = by_record
        return result

    def insert(self, uow: UnitOfWork, entity: t.EntityConfig, changes: list[t.RowChange]) -> None:
        code = self._code(entity)
        for change in changes:
            if change.row_key is None:
                change.row_key = str(self._next)
                self._next += 1
            values = {f.name: None for f in entity.fields}
            values.update(change.values)
            values[entity.primary_key] = Decimal(change.row_key)
            self.rows[code][change.row_key] = values
        self.writes.append(Write("insert", code, [dict(c.values) for c in changes]))

    def update(self, uow: UnitOfWork, entity: t.EntityConfig, changes: list[t.RowChange]) -> None:
        code = self._code(entity)
        for change in changes:
            self.rows[code][change.row_key or ""].update(change.values)
        self.writes.append(Write("update", code, [{"rowKey": c.row_key, **c.values} for c in changes]))

    def delete(self, uow: UnitOfWork, entity: t.EntityConfig, changes: list[t.RowChange]) -> None:
        code = self._code(entity)
        for change in changes:
            del self.rows[code][change.row_key or ""]
        self.writes.append(Write("delete", code, [{"rowKey": c.row_key} for c in changes]))

    def delete_children(self, uow: UnitOfWork, entity: t.EntityConfig, parent_key: str, record_keys: list[str]) -> None:
        code = self._code(entity)
        gone = [k for k, v in self.rows[code].items() if str(to_wire("number", v[parent_key])) in record_keys]
        for key in gone:
            del self.rows[code][key]
        self.writes.append(Write("deleteChildren", code, [{"parent": k} for k in record_keys]))


# ---------------------------------------------------------------- 命令记录表（SQLite，模拟验证判重和回滚）

PF_COMMAND_DDL = (
    "CREATE TABLE pf_command (user_id VARCHAR(64) NOT NULL, request_key VARCHAR(36) NOT NULL, operation VARCHAR(128) NOT NULL, "
    "page VARCHAR(64), digest VARCHAR(64) NOT NULL, status VARCHAR(16) NOT NULL, result TEXT, audit_diff TEXT, "
    "created_at TIMESTAMP NOT NULL, finished_at TIMESTAMP, escape_hatch_calls TEXT, PRIMARY KEY (user_id, request_key))"
)


def command_factory() -> FakeUnitOfWorkFactory:
    """带 PF_COMMAND 表（与迁移 wp_0001、wp_0002 相同的列）的事务工厂。"""
    factory = FakeUnitOfWorkFactory()
    with factory.engine.connect() as connection:
        connection.execute(text(PF_COMMAND_DDL))
        connection.commit()
    return factory


def command_rows(factory: FakeUnitOfWorkFactory) -> list[dict[str, Any]]:
    with factory.engine.connect() as connection:
        return [dict(r) for r in connection.execute(text("SELECT * FROM pf_command ORDER BY user_id, request_key")).mappings()]


def scales_inspector(scales: dict[tuple[str, str], int | None] | None = None) -> FakeSchemaInspector:
    """业务表的列（只有数值列的小数位影响写入）：默认都没有定义小数位（NUMBER），`scales` 改其中的列。"""
    inspector = FakeSchemaInspector()
    scales = scales or {}
    for entity in ENTITIES.values():
        columns = [t.ColumnInfo(name=f.column, data_type="NUMBER" if f.type == "number" else "VARCHAR2", nullable=True,
                                length=None, precision=None, scale=scales.get((entity.table, f.column)))
                   for f in entity.fields if f.column]
        inspector.add_table(entity.table, columns, primary_key=entity.primary_key)
    return inspector


# ---------------------------------------------------------------- 按 orchestration 的执行方式组合本模块的阶段

def run_stages(stages: Sequence[PipelineStage], uow: UnitOfWork, state: t.CommandState, ctx: t.ExecutionContext) -> None:
    """按 plugin-spec 第 3 节"编排的执行方式"执行各位置上 `applies` 为真的阶段：到"展开动作"时，只要有展开动作的阶段
    applies，就一轮轮执行"展开动作 → 加锁读取 → 只对这一轮新读入的单据执行冻结检查 → 合并意图 → 计算与规则"；
    没有动作时这几步（不含展开动作）执行一次；然后是其余位置。"""
    by_name = {name: [s for s in stages if s.name == name] for name in STAGE_ORDER}

    def position(name: str, target: t.CommandState = state) -> None:
        for stage in by_name[name]:
            if stage.applies(target, ctx):
                stage.run(uow, target, ctx)

    def one_round() -> None:
        before = set(state.current)
        position("加锁读取")
        loaded = [ref for ref in state.current if ref not in before]
        if loaded:
            position("冻结检查", dataclasses.replace(state, involved=loaded))
        position("合并意图")
        position("计算与规则")

    expand_at = STAGE_ORDER.index("展开动作")
    for name in STAGE_ORDER[:expand_at]:
        position(name)
    expanders = by_name["展开动作"]
    if any(s.applies(state, ctx) for s in expanders):
        while any(s.applies(state, ctx) for s in expanders):
            position("展开动作")
            one_round()
    else:
        one_round()
    for name in STAGE_ORDER[STAGE_ORDER.index("计算与规则") + 1:]:
        position(name)


Expand = Callable[[t.CommandState, t.ExecutionContext], None]


@dataclass
class _ExpandActions:
    """测试用的"展开动作"阶段（operations 的 ActionStage 的替代）：每次 run 调用 `actions` 中的下一个替代展开。
    每个命令新建一个。"""

    actions: list[Expand]
    cursor: int = 0
    name: str = "展开动作"

    def applies(self, state: t.CommandState, ctx: t.ExecutionContext) -> bool:
        return self.cursor < len(self.actions)

    def run(self, uow: UnitOfWork, state: t.CommandState, ctx: t.ExecutionContext) -> None:
        self.actions[self.cursor](state, ctx)
        self.cursor += 1


@dataclass
class Pipeline:
    """测试用的命令流程（orchestration 将来做的事）：`CommandRecorder.begin` 判重 → 按 `STAGE_ORDER` 执行本模块的阶段
    （与 plugin.py 注册的相同，`RowStore` 换成 `store`）和其他模块阶段的替代实现（`freeze`、`trigger`、`actions`）→
    `CommandRecorder.complete` → 结果不是 unchanged 时提交。"""

    setup: Setup = field(default_factory=Setup)
    store: MemoryStore = field(default_factory=MemoryStore)
    factory: FakeUnitOfWorkFactory = field(default_factory=command_factory)
    inspector: FakeSchemaInspector = field(default_factory=scales_inspector)
    freeze: PipelineStage | None = None
    trigger: PipelineStage | None = None
    actions: list[Expand] = field(default_factory=list)
    extra: list[PipelineStage] = field(default_factory=list)
    """其他位置上的替代阶段（例如审批命令的"确定涉及的单据""审批处理"）。"""
    executions: int = 0

    def __post_init__(self) -> None:
        from cost_platform.pipeline.calc import Recalculator
        from cost_platform.pipeline.command_log import OracleCommandRecorder
        from cost_platform.pipeline.loader import DocumentLoader, PageSaveInvolved
        from cost_platform.pipeline.merge import DocumentMerger, IntentMerger
        from cost_platform.pipeline.stages import (
            LockStage,
            MergeIntentsStage,
            MergePatchesStage,
            RecalculateStage,
            WriteChangesStage,
        )
        from cost_platform.pipeline.values import ColumnScales
        from cost_platform.pipeline.writer import ChangeWriter

        scales = ColumnScales(self.inspector)
        self.recorder = OracleCommandRecorder()
        self.loader = DocumentLoader(self.store, self.setup.permission)
        self.merger = DocumentMerger(self.setup.permission, scales)
        self.intents = IntentMerger(self.loader, scales)
        self.calc = Recalculator(self.setup.engine, scales)
        self.writer = ChangeWriter(self.store)
        self.stages: list[PipelineStage] = [
            PageSaveInvolved(), LockStage(self.loader), MergePatchesStage(self.merger), MergeIntentsStage(self.intents),
            RecalculateStage(self.calc), WriteChangesStage(self.writer)]

    def execute(self, cmd: t.Command, ctx: t.ExecutionContext) -> t.CommandResult:
        others = [s for s in (self.freeze, self.trigger, *self.extra) if s is not None]
        with self.factory.begin() as uow:
            replay = self.recorder.begin(uow, ctx.identity.user_id, cmd, ctx.now)
            if replay is not None:
                return replay
            self.executions += 1
            state = t.CommandState(command=cmd)
            run_stages([*self.stages, *others, _ExpandActions(list(self.actions))], uow, state, ctx)
            result = self.recorder.complete(uow, state, ctx)
            if result.outcome != "unchanged":
                uow.commit()  # unchanged 时不提交，事务回滚，命令记录一起撤销（WP-10 的第二种情况）
            return result
