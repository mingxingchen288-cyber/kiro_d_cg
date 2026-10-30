"""approval 模拟验证共用的样例和测试替身。

- 配置：成本核算页（COST_PINGGU 及原辅料、包材明细）取自 `backend/seed/config`；物料清单页 GOODS_PRICE_MANAGE 按 C06
  第 2 节的例子补上（实体 COST_GOODS_PRICE，表 T_COST_GOODS，读取视图 T_COST_GOODS_PRICE_V）；三个审批流直接读 C06
  7.8、7.9、7.10 的样例 JSON。
- 数据：取自 d_cg 的真实数据（`.reports/approval-design/07、08`，`.reports/modules/approval/01-e37-data.out.txt`）：
  成本单 2550（250mg乙酰唑胺片，商业化）的原辅料 206323 聚维酮K30（物料 25，单价 75，每批数量 10，金额 750）、206326
  玉米淀粉（310，单价 22，42.5，935）、206325 硬脂酸镁（115，单价 63，2.5，157.5）；d_cg 中 2550 还有另外 11 行明细，这里
  没有放进来。成本单 2556（10mg氯丙嗪片）中聚维酮K30 的明细 103681（单价 75、金额 23.25）。物料清单 25 聚维酮K30、115
  硬脂酸镁的参考价格 75、310 玉米淀粉 22、13165 微晶纤维素 40，执行价都为空。物料 116、117 和成本单 2601、2602 是说明用的
  假设数据（d_cg 中 116 是包材"小盒封口签"）；主表的每批物料成本、每盒成本按下面的替身规则算，不是 d_cg 中的值。
- 测试替身（写死的、模拟的，只用于模拟验证）：
  - `World`：内存中的业务表和视图，充当 `DocumentReader`、`TableWriter`、`KeyAllocator`；
  - `WorldSql`：`SqlRunner` 的替身，按 approval 包装好的语句形状在 `World` 上求值；入口条件和审批人 SQL 用按片段
    登记的 Python 判断代替，真实的 SQL 在 `test_oracle.py` 中由 d_cg 执行；
  - `ToyRules`：`RulesEngine` 的替身，只算"金额 = 单价 × 每批数量、主表每批物料成本 = 金额合计、每盒成本 = 每批物料
    成本 / 100"三条，代替 rules-core 的真实规则；
  - `Pipeline`：按架构第 7 节的顺序调用 approval 的阶段，加锁读取、合并、计算和写入由这里代替 write-pipeline 和
    orchestration（只为让审批的阶段跑通一条完整的命令）。
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from cost_platform.approval import ApprovalDeps, ApprovalModule, ApprovalService, ItemsApprovalCatalog, create_approval
from cost_platform.approval.patch import patch_ref
from cost_platform.approval.store import ApprovalStore
from cost_platform.approval.tables import metadata
from cost_platform.config.page_view import build_page_view
from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import (
    FakeBusinessLocker,
    FakeConfigSnapshot,
    FakeDirectory,
    FakeSchemaInspector,
    FakeUnitOfWorkFactory,
)
from cost_platform.contracts.values import from_db, from_wire, to_wire
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

D = Decimal
ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs" / "契约"
SEED = ROOT / "backend" / "seed" / "config"
T0 = datetime(2026, 10, 29, 9, 30, 0)


def _seed(name: str) -> t.ConfigDraft:
    return t.parse_wire(t.ConfigDraft, json.loads((SEED / name).read_text(encoding="utf-8")))


def c06_flows() -> dict[str, t.ConfigDraft]:
    """C06 7.8、7.9、7.10 的三个审批流样例，按编码。"""
    text = next(DOCS.glob("C06-*.md")).read_text(encoding="utf-8")
    found = {}
    for block in re.findall(r"```json\n(.*?)```", text, flags=re.S):
        if '"type": "approvalFlow"' in block:
            item = json.loads(block)
            found[item["key"]] = t.ConfigDraft(type="approvalFlow", key=item["key"], name=item["name"], content=item["content"])
    return found


GOODS_ENTITY = t.ConfigDraft(type="entity", key="COST_GOODS_PRICE", name="物料清单", content={
    "table": "T_COST_GOODS", "primaryKey": "GOODSID", "freezable": True, "readView": "T_COST_GOODS_PRICE_V",
    "fields": [
        {"name": "GOODSID", "column": "GOODSID", "label": "物料ID", "type": "number", "scale": 0, "source": "own", "role": "system"},
        {"name": "GOODSNAME", "column": "GOODSNAME", "label": "物料名称", "type": "text", "source": "own", "role": "input"},
        {"name": "USEFLAG", "column": "USEFLAG", "label": "分类", "type": "text", "source": "own", "role": "input"},
        {"name": "PRICE", "column": "PRICE", "label": "参考价格", "type": "number", "scale": 2, "source": "own", "role": "input"},
        {"name": "ZX_PRICE", "column": "ZX_PRICE", "label": "单价", "type": "number", "scale": 2, "source": "own", "role": "input"},
        {"name": "ISERP", "column": "ISERP", "label": "ERP物料", "type": "text", "source": "own", "role": "input"},
    ],
})
GOODS_PAGE = t.ConfigDraft(type="page", key="GOODS_PRICE_MANAGE", name="物料清单及成本", content={
    "title": "物料清单及成本", "layout": "single", "detailMode": "tabs", "audit": True, "saveOperation": "GOODS_PRICE_MANAGE.save",
    "master": {"entity": "COST_GOODS_PRICE", "grid": {"sideBar": True, "cellSelection": True, "groupBy": []}},
})
GOODS_SAVE = t.ConfigDraft(type="operation", key="GOODS_PRICE_MANAGE.save", name="物料清单保存", content={
    "label": "保存", "kind": "save", "writableFields": {"COST_GOODS_PRICE": ["ZX_PRICE"]}, "impact": ["COST_GOODS_PRICE"],
    "propagation": "continue",
})
ALL_PAGES = {"COST_PINGGU": {"buttons": ["*"]}, "GOODS_PRICE_MANAGE": {"buttons": ["*"]}}


def role_item(code: str, name: str, admin: bool = False) -> t.ConfigDraft:
    return t.ConfigDraft(type="role", key=code, name=name, content={"name": name, "admin": admin, "pages": ALL_PAGES})


ROLES = {"ADMIN": ("系统管理员", True), "COST": ("成本会计", False), "008": ("采购", False), "007": ("生产", False),
         "TECH": ("技术中心", False)}


@dataclass(frozen=True)
class Person:
    user_id: str
    name: str
    role: str
    department: str | None


ADMIN = Person("1", "系统管理员", "ADMIN", None)
YANGNA = Person("112", "杨娜", "COST", "10")
BUYER = Person("2001", "采购员", "008", "20")
MAKER = Person("3001", "生产员", "007", "30")
TECH = Person("501", "技术中心张工", "TECH", "1069")
PEOPLE = [ADMIN, YANGNA, BUYER, MAKER, TECH]


def directory() -> FakeDirectory:
    found = FakeDirectory()
    for p in PEOPLE:
        found.add_account(t.AccountRef(p.user_id, f"u{p.user_id}", p.name, p.department, True), [p.role])
    return found


class Config:
    """一套配置：实体、页面、操作、角色、审批流；`snapshot(角色)` 给出该角色的配置快照，`catalog` 给出 approval 的配置读取。"""

    def __init__(self, flows: Iterable[str] = (), *, register_goods: bool = False,
                 entity_overrides: Mapping[str, dict[str, Any]] | None = None,
                 extra_flows: Iterable[t.ConfigDraft] = ()) -> None:
        """成本核算页原辅料、包材的物料ID用 seed 的物料 Lookup（`costMaterialEffective`，从 T_COST_GOODS_PRICE_V 回填物料
        名称、分类等），对应旧系统成本核算页物料列的 Lookup。"""
        lookup = _seed("lookup.costMaterialEffective.json")
        self.lookups: dict[str, t.LookupConfig] = {lookup.key: t.parse_config_content("lookup", lookup.content)}  # type: ignore[dict-item]
        items = [_seed("entity.COST_PINGGU.json"), _seed("entity.COST_MATERIAL.json"), _seed("entity.COST_PACKAGE.json"),
                 _seed("page.COST_PINGGU.json"), _seed("operation.COST_PINGGU.save.json"), GOODS_ENTITY, GOODS_PAGE, GOODS_SAVE]
        items += [role_item(code, name, admin) for code, (name, admin) in ROLES.items()]
        samples = c06_flows()
        items += [samples[code] for code in flows] + list(extra_flows)
        self.entities: dict[str, t.EntityConfig] = {}
        self.pages: dict[str, t.PageConfig] = {}
        self.operations: dict[str, t.OperationConfig] = {}
        self.roles: dict[str, t.RoleConfig] = {}
        self.flows: dict[str, tuple[str, t.ApprovalFlowConfig]] = {}
        for item in items:
            content = dict(item.content)
            if item.type == "entity" and entity_overrides and item.key in entity_overrides:
                content = {**content, **entity_overrides[item.key]}
            parsed = t.parse_config_content(item.type, content)
            if item.type == "entity":
                self.entities[item.key] = parsed  # type: ignore[assignment]
            elif item.type == "page":
                self.pages[item.key] = parsed  # type: ignore[assignment]
            elif item.type == "operation":
                self.operations[item.key] = parsed  # type: ignore[assignment]
            elif item.type == "role":
                self.roles[item.key] = parsed  # type: ignore[assignment]
            elif item.type == "approvalFlow":
                self.flows[item.key] = (item.name, parsed)  # type: ignore[assignment]
        # 物料清单页的实体在 d_cg 现有的种子配置中还没有：E37 默认按"T_COST_GOODS 没注册"处理（经 TableWriter 写）
        registered = dict(self.entities)
        if not register_goods and not any(f.page == "GOODS_PRICE_MANAGE" for _, f in self.flows.values()):
            registered.pop("COST_GOODS_PRICE")
        self.catalog = ItemsApprovalCatalog(self.flows, registered, self.role_names())
        self.rules = ToyRules()
        self._pack = self.rules.load_pack(b"{}")

    def role_names(self) -> dict[str, str]:
        """角色编码 -> 名称（审批进度中按角色配置的审批人显示名称）。"""
        return {code: role.name for code, role in self.roles.items()}

    def snapshot(self, role_code: str) -> FakeConfigSnapshot:
        role = self.roles[role_code]
        views = {code: build_page_view(code, page, self.entities, role, 1) for code, page in self.pages.items()}
        return FakeConfigSnapshot(version=1, role_code=role_code, role=role, page_views=views, entities=self.entities,
                                  operations=self.operations, approval_flows={k: f for k, (_, f) in self.flows.items()},
                                  packs={"COST_PINGGU": self._pack, "COST_GOODS_PRICE": self._pack}, lookups=self.lookups)

    def ctx(self, person: Person, *, origin: t.Origin | None = None, now: datetime = T0) -> t.ExecutionContext:
        who = t.Identity(user_id=person.user_id, username=f"u{person.user_id}", display_name=person.name,
                         department_id=person.department, role_code=person.role, session_id=f"s-{person.user_id}")
        snap = self.snapshot(person.role)
        return t.ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=who, config=snap,
                                  config_version=1, origin=origin or t.Origin(kind="user", approval_id=None), now=now)


# ============================================================ 业务数据

def _goods(goods_id: int, name: str, useflag: str, price: str | None, zx: str | None = None, iserp: str = "1") -> dict[str, Any]:
    return {"GOODSID": D(goods_id), "GOODSNAME": name, "USEFLAG": useflag, "PRICE": None if price is None else D(price),
            "ZX_PRICE": None if zx is None else D(zx), "ISERP": iserp}


def _dtl(dtlid: int, docid: int, goods: int, price: str, qty: str, *, customer: int = 0, memo: str | None = None) -> dict[str, Any]:
    return {"DTLID": D(dtlid), "DOCID": D(docid), "GOODSID": D(goods), "PRICE": D(price), "BATCH_QTY": D(qty),
            "COST_BATCH": D(price) * D(qty), "CUSTOMER_SPECIFIED": customer, "MEMO": memo, "PER_HL": None, "EXADD_MATER": None}


MATERIAL_FLAGS = ("原料", "辅料")
PACKAGE_FLAGS = ("非印字包材", "印字包材")


class World:
    """内存中的业务表（键为主键文本的行）和由它们算出的视图；只用于模拟验证。"""

    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict[str, Any]]] = {
            "T_COST_GOODS": {}, "T_COST_PINGGU": {}, "T_COST_PINGGU_DTL": {}, "T_COST_PINGGU_DTL_LQ": {},
        }
        self.keys = {"T_COST_PINGGU_SEQ": 3000, "T_COST_PINGGU_DTL_SEQ": 300000, "T_COST_GOODS_SEQ": 900000}
        self.entities: dict[str, t.EntityConfig] = {}
        self.locked: list[tuple[str, str]] = []
        self.table_writes: list[tuple[str, str, str, dict[str, Any]]] = []
        for row in [_goods(25, "聚维酮K30", "辅料", "75"), _goods(115, "硬脂酸镁", "辅料", "75"), _goods(116, "滑石粉", "辅料", "12"),
                    _goods(117, "二氧化硅", "辅料", "13"), _goods(310, "玉米淀粉", "辅料", "22"),
                    _goods(13165, "微晶纤维素", "辅料", "40")]:
            self.put("T_COST_GOODS", row)
        self.add_cost(2550, "250mg乙酰唑胺片", [_dtl(206323, 2550, 25, "75", "10"), _dtl(206326, 2550, 310, "22", "42.5"),
                                               _dtl(206325, 2550, 115, "63", "2.5")])
        self.add_cost(2556, "10mg氯丙嗪片", [_dtl(103681, 2556, 25, "75", "0.31")])

    # ---------------------------------------------------------------- 数据准备

    def put(self, table: str, row: dict[str, Any]) -> None:
        key = {"T_COST_GOODS": "GOODSID", "T_COST_PINGGU": "DOCID"}.get(table, "DTLID")
        self.tables[table][_text(row[key])] = dict(row)

    def add_cost(self, docid: int, product: str, details: list[dict[str, Any]], *, status: str = "商业化") -> None:
        total = sum((d["COST_BATCH"] for d in details), D(0))
        self.put("T_COST_PINGGU", {"DOCID": D(docid), "GOODSID": None, "GOODSNAME": product, "USESTATUS": status, "MEMO": None,
                                   "TOTAL_COST": total, "COST_PERBOX": total / 100})
        for detail in details:
            self.put("T_COST_PINGGU_DTL", detail)

    def row(self, table: str, key: Any) -> dict[str, Any] | None:
        return self.tables[table].get(_text(key))

    # ---------------------------------------------------------------- 视图（与 business_tables.json 中的视图同义）

    def relation(self, name: str) -> list[dict[str, Any]]:
        if name in self.tables:
            return [dict(r) for r in self.tables[name].values()]
        if name == "T_COST_GOODS_PRICE_V":
            return [{**r, "ZX_PRICE": r["ZX_PRICE"] if r["ZX_PRICE"] is not None else r["PRICE"]} for r in self.tables["T_COST_GOODS"].values()]
        flags = {"V_COST_PINGGU_MATERIAL": MATERIAL_FLAGS, "V_COST_PINGGU_PACKAGE": PACKAGE_FLAGS}
        lq = {"V_COST_PINGGU_MATERIAL_LQ": MATERIAL_FLAGS, "V_COST_PINGGU_PACKAGE_LQ": PACKAGE_FLAGS}
        if name in flags or name in lq:
            table = "T_COST_PINGGU_DTL" if name in flags else "T_COST_PINGGU_DTL_LQ"
            wanted = flags.get(name) or lq[name]
            rows = []
            for d in self.tables[table].values():
                g = self.tables["T_COST_GOODS"].get(_text(d["GOODSID"]))
                if g is not None and g["USEFLAG"] in wanted:
                    rows.append({**d, "GOODSNAME": g["GOODSNAME"], "DTL_USEFLAG": g["USEFLAG"], "BASE_PRICE": g["ZX_PRICE"],
                                 "SUQTY": None, "FACTORYNAME": None, "STANDARDTYPE": None, "GOODSTYPE": None, "GOODSNAME_EN": None,
                                 "CUSTOMER_SPECIFIED": d["CUSTOMER_SPECIFIED"] or 0})
            return rows
        raise AssertionError(f"测试数据中没有表或视图 {name}")

    # ---------------------------------------------------------------- DocumentReader

    def bind(self, entities: Mapping[str, t.EntityConfig]) -> World:
        self.entities = dict(entities)
        return self

    def _entity_rows(self, code: str) -> list[dict[str, Any]]:
        entity = self.entities[code]
        return self.relation(entity.read_view or entity.table)

    def _row(self, code: str, raw: dict[str, Any]) -> t.Row:
        entity = self.entities[code]
        values = {f.name: from_db(f.type, raw.get(f.name)) for f in entity.fields}
        return t.Row(entity=code, row_key=_text(raw[entity.primary_key]), client_row_id=None, values=values)

    def load(self, ref: t.DocumentRef) -> t.DocumentData | None:
        entity = self.entities[ref.entity]
        master = next((r for r in self._entity_rows(ref.entity) if _text(r[entity.primary_key]) == ref.record_key), None)
        if master is None:
            return None
        details = {}
        for link in entity.details:
            rows = [r for r in self._entity_rows(link.entity) if _text(r[link.parent_key]) == ref.record_key]
            details[link.entity] = [self._row(link.entity, r) for r in sorted(rows, key=lambda r: r[self.entities[link.entity].primary_key])]
        return t.DocumentData(ref=ref, master=self._row(ref.entity, master), details=details)

    def load_many(self, refs: list[t.DocumentRef]) -> dict[t.DocumentRef, t.DocumentData]:
        return {ref: doc for ref in refs if (doc := self.load(ref)) is not None}

    # ---------------------------------------------------------------- 写入（注册过的实体按字段写到表的列）

    def write_row(self, code: str, op: str, row_key: str | None, values: Mapping[str, Any]) -> str:
        entity = self.entities[code]
        columns = {f.name: f.column for f in entity.fields if f.column is not None}
        table = self.tables[entity.table]
        if op == "delete":
            table.pop(row_key or "", None)
            return row_key or ""
        data = {columns[k]: (1 if v is True else 0 if v is False else v) for k, v in values.items() if k in columns}
        if op == "add":
            key = row_key or self.next_key(None, entity.table)  # type: ignore[arg-type]
            data[columns[entity.primary_key]] = D(key)
            table[key] = {**{c: None for c in columns.values()}, **data}
            return key
        table[row_key or ""].update(data)
        return row_key or ""

    # ---------------------------------------------------------------- TableWriter、KeyAllocator

    def lock_row(self, uow: Any, table: str, key_column: str, key: str) -> dict[str, Any] | None:
        self.locked.append((table, key))
        found = self.row(table, key)
        return None if found is None else dict(found)

    def update(self, uow: Any, table: str, key_column: str, key: str, values: dict[str, Any]) -> None:
        self.tables[table][_text(key)].update(values)
        self.table_writes.append(("update", table, key, dict(values)))

    def insert(self, uow: Any, table: str, values: dict[str, Any]) -> str:
        key = self.next_key(uow, table)
        self.tables[table][key] = {**values, "GOODSID" if table == "T_COST_GOODS" else "DTLID": D(key)}
        self.table_writes.append(("insert", table, key, dict(values)))
        return key

    def delete(self, uow: Any, table: str, key_column: str, key: str) -> None:
        self.tables[table].pop(_text(key), None)
        self.table_writes.append(("delete", table, key, {}))

    def next_key(self, uow: Any, table: str) -> str:
        name = f"{table}_SEQ"
        self.keys[name] = self.keys.get(name, 1) + 1
        return str(self.keys[name])

    def snapshot_state(self) -> Any:
        return copy.deepcopy((self.tables, self.keys))

    def restore(self, state: Any) -> None:
        self.tables, self.keys = copy.deepcopy(state)


def _text(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


# ============================================================ 表结构（SchemaInspector）

def _col(name: str, data_type: str = "NUMBER", scale: int | None = None) -> t.ColumnInfo:
    return t.ColumnInfo(name=name, data_type=data_type, nullable=True, length=None, precision=None, scale=scale)


def schema() -> FakeSchemaInspector:
    found = FakeSchemaInspector()
    goods = [_col("GOODSID"), _col("GOODSNAME", "VARCHAR2"), _col("USEFLAG", "VARCHAR2"), _col("PRICE"), _col("ZX_PRICE"),
             _col("ISERP", "VARCHAR2")]
    dtl = [_col("DTLID"), _col("DOCID"), _col("GOODSID"), _col("PRICE"), _col("BATCH_QTY"), _col("COST_BATCH"),
           _col("CUSTOMER_SPECIFIED"), _col("MEMO", "VARCHAR2"), _col("PER_HL"), _col("EXADD_MATER")]
    found.add_table("T_COST_GOODS", goods, primary_key="GOODSID")
    found.add_table("T_COST_PINGGU", [_col("DOCID"), _col("GOODSNAME", "VARCHAR2"), _col("USESTATUS", "VARCHAR2"),
                                      _col("MEMO", "VARCHAR2"), _col("EFFECTIVE_DATE", "DATE")], primary_key="DOCID")
    found.add_table("T_COST_PINGGU_DTL", dtl, primary_key="DTLID")
    found.add_table("T_COST_PINGGU_DTL_LQ", dtl, primary_key="DTLID")
    found.add_view("T_COST_GOODS_PRICE_V", goods)
    for view in ("V_COST_PINGGU_MATERIAL", "V_COST_PINGGU_PACKAGE", "V_COST_PINGGU_MATERIAL_LQ", "V_COST_PINGGU_PACKAGE_LQ"):
        found.add_view(view, [*dtl, _col("GOODSNAME", "VARCHAR2")])
    return found


# ============================================================ SqlRunner 的替身

def _norm(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (Decimal, int)):
        return D(value).normalize()
    return value


def _simple(condition: str, row: Mapping[str, Any], binds: Mapping[str, Any]) -> bool:
    """`列 = :参数`、`列 <> :参数` 用 AND 连接的条件（样例中冻结和展示数据的关联条件就是这种写法）。"""
    for part in re.split(r"\s+AND\s+", condition.strip()):
        found = re.fullmatch(r"(\w+)\s*(=|<>)\s*:(\w+)", part.strip())
        if found is None:
            raise AssertionError(f"测试替身不认识这个关联条件：{condition}")
        column, op, name = found.groups()
        same = _norm(row.get(column)) == _norm(binds.get(name))
        if (op == "=") != same:
            return False
    return True


class WorldSql:
    """`SqlRunner` 的替身：按 approval 包装好的语句形状（sql.py）在 `World` 上求值。

    - `SELECT 1 FROM DUAL WHERE (<条件>)`：入口条件按片段原文查 `conditions` 中登记的 Python 判断；
    - `SELECT <列> FROM <表或视图> WHERE (<条件>)`：冻结和展示数据的关联条件，只认 `列 = :参数` 的写法；
    - `SELECT (<表达式>) AS V FROM DUAL`：取值，只认 `:参数` 和 `NVL(:a, :b)`；
    - `SELECT … WHERE <列> IN (:k0, …)`：按主键读行；
    - 其他语句（审批人 SQL）按片段查 `queries`。没有准备的语句直接让测试失败。
    """

    def __init__(self, world: World) -> None:
        self.world = world
        self.conditions: dict[str, Callable[[Mapping[str, Any]], bool]] = {}
        self.queries: dict[str, Callable[[Mapping[str, Any]], list[dict[str, Any]]]] = {}
        self.statements: list[tuple[str, dict[str, Any]]] = []

    def rows(self, uow: Any, statement: str, binds: Mapping[str, object]) -> list[dict[str, object]]:
        self.statements.append((statement, dict(binds)))
        for fragment, fn in self.queries.items():
            if fragment in statement:
                return fn(binds)
        if (found := re.fullmatch(r"SELECT 1 FROM DUAL WHERE \((.*)\)", statement, flags=re.S)) is not None:
            condition = found.group(1)
            if condition not in self.conditions:
                raise AssertionError(f"测试没有准备这个入口条件：{condition}")
            return [{"1": D(1)}] if self.conditions[condition](binds) else []
        if (found := re.fullmatch(r"SELECT \((.*)\) AS V FROM DUAL", statement, flags=re.S)) is not None:
            return [{"V": self._value(found.group(1).strip(), binds)}]
        if (found := re.fullmatch(r"SELECT (.+?) FROM (\w+) WHERE (\w+) IN \((.*)\)", statement)) is not None:
            columns, source, column, names = found.groups()
            keys = {_text(binds[n.strip()[1:]]) for n in names.split(",")}
            rows = [r for r in self.world.relation(source) if r.get(column) is not None and _text(r.get(column)) in keys]
            return [self._project(r, columns) for r in rows]
        if (found := re.fullmatch(r"SELECT (.+?) FROM (\w+) WHERE \((.*)\)", statement, flags=re.S)) is not None:
            columns, source, condition = found.groups()
            return [self._project(r, columns) for r in self.world.relation(source) if _simple(condition, r, binds)]
        raise AssertionError(f"测试没有准备这条 SQL：{statement}")

    @staticmethod
    def _project(row: Mapping[str, Any], columns: str) -> dict[str, Any]:
        if columns.strip() == "*":
            return {k.upper(): v for k, v in row.items()}
        return {c.strip().upper(): row.get(c.strip()) for c in columns.split(",")}

    @staticmethod
    def _value(expression: str, binds: Mapping[str, Any]) -> Any:
        if (found := re.fullmatch(r":(\w+)", expression)) is not None:
            return binds.get(found.group(1))
        if (found := re.fullmatch(r"NVL\(:(\w+),\s*:(\w+)\)", expression)) is not None:
            first = binds.get(found.group(1))
            return first if first is not None else binds.get(found.group(2))
        raise AssertionError(f"测试替身不认识这个取值：{expression}")


def list_price(world: World, goods_id: Any) -> Decimal | None:
    """物料清单的单价：执行价为空时取参考价格（SELECT NVL(ZX_PRICE, PRICE) FROM T_COST_GOODS WHERE GOODSID = …）。"""
    row = world.row("T_COST_GOODS", goods_id) if goods_id is not None else None
    if row is None:
        return None
    return row["ZX_PRICE"] if row["ZX_PRICE"] is not None else row["PRICE"]


def _changed(a: Any, b: Any) -> bool:
    """DECODE(a, b, 0, 1) = 1：空和空相同，空和有值不同。"""
    return _norm(a) != _norm(b)


def sample_sql(world: World) -> WorldSql:
    """C06 7.8、7.9、7.10 的入口条件，在 World 上按同样的意思求值（真实执行见 test_oracle.py）。"""
    sql = WorldSql(world)
    flows = c06_flows()

    def condition(flow: str, level: int) -> str:
        return flows[flow].content["levels"][level - 1]["nodes"][0]["condition"]  # type: ignore[index]

    def e78_level1(b: Mapping[str, Any]) -> bool:
        moved = _changed(b["new_GOODSID"], b["old_GOODSID"]) or _changed(b["new_PRICE"], b["old_PRICE"])
        return moved and _changed(b["new_PRICE"], list_price(world, b["new_GOODSID"]))

    def e78_level2(b: Mapping[str, Any]) -> bool:
        price = list_price(world, b["new_GOODSID"])
        return b["new_PRICE"] is not None and price is not None and D(b["new_PRICE"]) > price * D("1.1")

    def e79_level1(b: Mapping[str, Any]) -> bool:
        return (b["master_old_USESTATUS"] == "评估中" and (b["old_CUSTOMER_SPECIFIED"] or 0) != 0
                and (b["operation"] == "deleted" or _changed(b["new_GOODSID"], b["old_GOODSID"])
                     or _changed(b["new_CUSTOMER_SPECIFIED"], b["old_CUSTOMER_SPECIFIED"])))

    sql.conditions[condition("COST_TO_GOODS", 1)] = e78_level1
    sql.conditions[condition("COST_TO_GOODS", 2)] = e78_level2
    sql.conditions[condition("TECH_CUSTOMER_MATERIAL", 1)] = e79_level1
    sql.conditions[condition("GOODS_TO_COST", 1)] = lambda b: _changed(b["new_ZX_PRICE"], b["old_ZX_PRICE"])
    return sql


# ============================================================ RulesEngine 的替身

def toy_calc(document: t.EvalDocument, deleted: set[tuple[str, str]]) -> list[t.EvalRowResult]:
    """代替 rules-core 的三条计算：金额 = 单价 × 每批数量；主表每批物料成本 = 未删除明细的金额合计；每盒成本 = 每批物料成本 / 100。"""
    results = []
    total = D(0)
    for entity, rows in document.details.items():
        for row in rows:
            ident = row.row_key or row.client_row_id or ""
            price = row.values.get("PRICE")
            qty = row.values.get("BATCH_QTY")
            amount = D(price) * D(qty) if isinstance(price, str) and isinstance(qty, str) else D(0)
            if (entity, ident) not in deleted:
                total += amount
            results.append(t.EvalRowResult(entity=entity, row_key=row.row_key, client_row_id=row.client_row_id,
                                           computed={"COST_BATCH": to_wire("number", amount)}, fields={},
                                           style=t.RowStyle(row=None, cells={})))
    if document.entity == "COST_PINGGU":
        m = document.master
        results.append(t.EvalRowResult(entity="COST_PINGGU", row_key=m.row_key, client_row_id=m.client_row_id,
                                       computed={"TOTAL_COST": to_wire("number", total), "COST_PERBOX": to_wire("number", total / 100)},
                                       fields={}, style=t.RowStyle(row=None, cells={})))
    return results


class ToyRules:
    """`RulesEngine` 的替身（只用于模拟验证）：按 C07 解析求值请求，用 `toy_calc` 算出结果。"""

    def __init__(self) -> None:
        self.requests: list[t.EvaluationRequest] = []

    def load_pack(self, pack_json: bytes) -> object:
        return object()

    def core_version(self) -> str:
        return "toy"

    def evaluate(self, handle: object, request_json: str) -> str:
        request = t.parse_wire(t.EvaluationRequest, json.loads(request_json))
        self.requests.append(request)
        deleted = {(c.entity, c.row_key or c.client_row_id or "") for c in request.changed if c.op == "delete"}
        result = t.EvalComputed(ok=True, rows=toy_calc(request.document, deleted), effects=[])
        return json.dumps(t.dump_wire(t.EvaluationResult, result), ensure_ascii=False)


# ============================================================ 命令执行的替身（代替 orchestration 和 write-pipeline）

def _same(a: Any, b: Any) -> bool:
    return _norm(a) == _norm(b) or ((a in (None, "")) and (b in (None, "")))


@dataclass
class Run:
    state: t.CommandState
    result: t.CommandResult


class Pipeline:
    """按架构第 7 节的顺序调用 approval 的阶段；判重、加锁读取（这里直接读 World）、合并、计算（`toy_calc` 同样的三条）、
    写入由这里代替。命令出错时 World 和审批数据（替代事务）一起回滚。只用于模拟验证。"""

    def __init__(self, world: World, approval: ApprovalModule, uow: FakeUnitOfWorkFactory, locks: FakeBusinessLocker) -> None:
        self.world = world
        self.approval = approval
        self.uow = uow
        self.locks = locks
        self.done: dict[tuple[str, str], Run] = {}
        self.executed: list[t.Command] = []
        self.runs: list[Run] = []

    def execute(self, command: t.Command, ctx: t.ExecutionContext) -> t.CommandResult:
        return self.run(command, ctx).result

    def run(self, command: t.Command, ctx: t.ExecutionContext) -> Run:
        key = (ctx.identity.user_id, command.request_key)
        if key in self.done:
            return self.done[key]
        saved = self.world.snapshot_state()
        stages = self.approval
        try:
            with self.uow.begin() as uow:
                state = self.prepare(uow, command, ctx)
                if stages.trigger.applies(state, ctx):
                    stages.trigger.run(uow, state, ctx)
                if stages.required.applies(state, ctx):
                    stages.required.run(uow, state, ctx)
                self._write(state)
                if state.outcome is None:
                    state.outcome = ("approvalProcessed" if command.operation.startswith("approval.")
                                     else "saved" if state.changes.rows else "unchanged")
                uow.commit()
        except Exception:
            self.world.restore(saved)
            raise
        result = t.CommandResult(request_key=command.request_key, outcome=state.outcome, rows=[], id_map={}, prompts=[],
                                 skipped=[], approvals=list(state.approvals))
        run = Run(state, result)
        self.done[key] = run
        self.executed.append(command)
        self.runs.append(run)
        return run

    def prepare(self, uow: Any, command: t.Command, ctx: t.ExecutionContext) -> t.CommandState:
        """触发审批之前的各步：确定涉及的单据、加锁读取、冻结检查、审批处理、合并、写入意图、计算、变更计划。"""
        stages = self.approval
        state = t.CommandState(command=command)
        if stages.resolve.applies(state, ctx):
            stages.resolve.run(uow, state, ctx)
        if stages.trigger_scope.applies(state, ctx):
            stages.trigger_scope.run(uow, state, ctx)
        for patch in command.documents:
            state.involved.append(patch_ref(patch))
        self._load(uow, ctx, state, list(state.involved))
        if stages.freeze_check.applies(state, ctx):
            stages.freeze_check.run(uow, state, ctx)
        if stages.process.applies(state, ctx):
            stages.process.run(uow, state, ctx)
        state.candidate = {ref: copy.deepcopy(doc) for ref, doc in state.current.items()}
        for patch in command.documents:
            self._merge(ctx, state, patch)
        self._intents(uow, state, ctx)
        for doc in state.candidate.values():
            self._calc(doc)
        state.changes = t.ChangePlan(rows=self._diff(state))
        return state

    def _load(self, uow: Any, ctx: t.ExecutionContext, state: t.CommandState, refs: list[t.DocumentRef]) -> None:
        """加锁读取（代替 write-pipeline）：库里有的单据按统一顺序经 `locks` 一次锁住（`defer_lock` 时只读不锁），再读入。"""
        found = {ref: doc for ref in refs if ref not in state.current and (doc := self.world.load(ref)) is not None}
        if found and not state.defer_lock:
            self.locks.lock(uow, ctx, [self.locks.document(ctx, ref) for ref in found])
        state.current.update(found)

    def _merge(self, ctx: t.ExecutionContext, state: t.CommandState, patch: t.DocumentPatch) -> None:
        ref = patch_ref(patch)
        entity = ctx.config.entity(patch.entity)
        types = {code: {f.name: f.type for f in ctx.config.entity(code).fields}
                 for code in [patch.entity, *(l.entity for l in entity.details)]}

        def values(code: str, wire: Mapping[str, Any], copy_of: str | None = None) -> dict[str, Any]:
            if copy_of is not None:
                return copied(code, wire, copy_of)
            return {k: from_wire(types[code][k], v) for k, v in wire.items()}

        def copied(code: str, wire: Mapping[str, Any], copy_of: str) -> dict[str, Any]:
            """代替 write-pipeline 的 WP-21：可写的字段取命令中的值；不可写、能写进表的字段取源行（World 中保存这一刻的
            这一行）的值；计算字段和只在视图中的字段不写。"""
            config = ctx.config.entity(code)
            fields = {f.name: f for f in config.fields}
            writable = set(ctx.config.operation(state.command.operation).writable_fields.get(code, []))
            source = self.world.row(config.table, copy_of) or {}
            found: dict[str, Any] = {}
            for name, raw in wire.items():
                f = fields[name]
                if name in writable:
                    found[name] = from_wire(f.type, raw)
                elif f.column is not None and f.role != "calculated":
                    found[name] = source.get(f.column)
            return found

        master = patch.master
        if isinstance(master, t.MasterAdd):
            state.candidate[ref] = t.DocumentData(ref, t.Row(patch.entity, None, master.client_row_id,
                                                             values(patch.entity, master.values, master.copy_of)),
                                                  {l.entity: [] for l in entity.details})
        elif isinstance(master, t.MasterDelete):
            state.candidate.pop(ref, None)
            return
        doc = state.candidate[ref]
        if isinstance(master, t.MasterModify):
            doc.master.values.update(values(patch.entity, master.changes))
        parents = {l.entity: l.parent_key for l in entity.details}
        for detail in patch.details:
            rows = doc.details.setdefault(detail.entity, [])
            if isinstance(detail, t.DetailAdd):
                rows.append(t.Row(detail.entity, None, detail.client_row_id,
                                  {**values(detail.entity, detail.values, detail.copy_of),
                                   parents[detail.entity]: doc.master.values.get(entity.primary_key)}))
            elif isinstance(detail, t.DetailModify):
                next(r for r in rows if r.row_key == detail.row_key).values.update(values(detail.entity, detail.changes))
            else:
                rows[:] = [r for r in rows if r.row_key != detail.row_key]

    def _intents(self, uow: Any, state: t.CommandState, ctx: t.ExecutionContext) -> None:
        """WP-18：意图所属单据不在 involved 中的，先加入、读入，再执行一次冻结检查，然后合并。"""
        intents, state.intents = list(state.intents), []
        new_refs = [i.document for i in intents if i.document not in state.involved]
        if new_refs:
            state.involved += list(dict.fromkeys(new_refs))
            self._load(uow, ctx, state, new_refs)
            for ref in new_refs:
                if ref in state.current:
                    state.candidate[ref] = copy.deepcopy(state.current[ref])
            self.approval.freeze_check.run(uow, state, ctx)
        for intent in intents:
            entity = ctx.config.entity(intent.entity)
            doc = state.candidate.get(intent.document)
            if intent.op == "add" and intent.entity == intent.document.entity and doc is None:
                state.candidate[intent.document] = t.DocumentData(
                    intent.document, t.Row(intent.entity, intent.row_key, intent.client_row_id, dict(intent.values)),
                    {l.entity: [] for l in entity.details})
                continue
            assert doc is not None, intent
            if intent.entity == intent.document.entity:
                if intent.op == "delete":
                    state.candidate.pop(intent.document)
                else:
                    doc.master.values.update(intent.values)
                continue
            rows = doc.details.setdefault(intent.entity, [])
            if intent.op == "add":
                rows.append(t.Row(intent.entity, intent.row_key, intent.client_row_id, {**intent.values,
                                  entity.primary_key: D(intent.row_key) if intent.row_key else None}))
            elif intent.op == "modify":
                next(r for r in rows if r.row_key == intent.row_key).values.update(intent.values)
            else:
                rows[:] = [r for r in rows if r.row_key != intent.row_key]

    @staticmethod
    def _calc(doc: t.DocumentData) -> None:
        if doc.ref.entity != "COST_PINGGU":
            return
        total = D(0)
        for rows in doc.details.values():
            for row in rows:
                price, qty = row.values.get("PRICE"), row.values.get("BATCH_QTY")
                row.values["COST_BATCH"] = D(price) * D(qty) if price is not None and qty is not None else D(0)
                total += row.values["COST_BATCH"]
        doc.master.values["TOTAL_COST"] = total
        doc.master.values["COST_PERBOX"] = total / 100

    def _diff(self, state: t.CommandState) -> list[t.RowChange]:
        changes: list[t.RowChange] = []
        for ref in dict.fromkeys([*state.current, *state.candidate]):
            before, after = state.current.get(ref), state.candidate.get(ref)
            old_rows = {} if before is None else {(r.entity, r.row_key): r for r in [before.master, *(x for v in before.details.values() for x in v)]}
            new_rows = [] if after is None else [after.master, *(x for v in after.details.values() for x in v)]
            for row in new_rows:
                old = old_rows.pop((row.entity, row.row_key), None) if row.row_key is not None else None
                if old is None:
                    changes.append(t.RowChange(ref, row.entity, "add", row.row_key, row.client_row_id,
                                               {k: v for k, v in row.values.items() if v is not None}, {}))
                    continue
                diff = {k: v for k, v in row.values.items() if not _same(v, old.values.get(k))}
                if diff:
                    changes.append(t.RowChange(ref, row.entity, "modify", row.row_key, None, diff, {k: old.values.get(k) for k in diff}))
            for (entity, key), old in old_rows.items():
                changes.append(t.RowChange(ref, entity, "delete", key, None, {}, dict(old.values)))
        return changes

    def _write(self, state: t.CommandState) -> None:
        for change in state.changes.rows:
            if change.document in state.pending_documents:
                continue
            self.world.write_row(change.entity, change.op, change.row_key, change.values)


# ============================================================ 一套完整的模拟环境

class Harness:
    """配置、业务数据、approval 的阶段和服务、命令执行的替身接在一起。"""

    def __init__(self, flows: Iterable[str] = ("COST_TO_GOODS",), *, threads: bool = False, **options: Any) -> None:
        self.config = Config(flows, **options)
        self.world = World().bind(self.config.entities)
        self.uow = FakeUnitOfWorkFactory()
        if threads:  # 接口测试中路由在线程池里执行：同一个内存库允许跨线程使用
            self.uow.engine = create_engine("sqlite://", poolclass=StaticPool,
                                            connect_args={"detect_types": sqlite3.PARSE_DECLTYPES, "check_same_thread": False})
        metadata.create_all(self.uow.engine)
        self.sql = sample_sql(self.world)
        self.directory = directory()
        self.store = ApprovalStore()
        self.locks = FakeBusinessLocker(self.world.load)
        self.deps = ApprovalDeps(catalog=lambda ctx: self.config.catalog, schema=schema(), directory=self.directory,
                                 documents=self.world, rules=self.config.rules, tables=self.world, locks=self.locks,
                                 store=self.store, sql=self.sql, keys=self.world)
        self.approval = create_approval(self.deps)
        self.pipeline = Pipeline(self.world, self.approval, self.uow, self.locks)
        self.service = ApprovalService(self.deps, self.uow, self.pipeline)
        self._keys = 0

    def request_key(self) -> str:
        self._keys += 1
        return f"00000000-0000-4000-8000-{self._keys:012x}"

    def ctx(self, person: Person) -> t.ExecutionContext:
        return self.config.ctx(person)

    def save(self, person: Person, page: str, documents: list[dict[str, Any]]) -> Run:
        operation = self.config.pages[page].save_operation
        command = t.parse_wire(t.Command, {"requestKey": self.request_key(), "page": page, "operation": operation,
                                           "documents": documents, "params": {}})
        return self.pipeline.run(command, self.ctx(person))

    def detail(self, person: Person, approval_id: str) -> t.ApprovalDetail:
        return self.service.detail(self.ctx(person), approval_id)

    def preview(self, person: Person, approval_id: str, checked: list[tuple[str, str, str]]) -> t.PreviewResponse:
        rows = [t.CheckedRow(flow=f, block=b, key=k) for f, b, k in checked]
        return self.service.preview(self.ctx(person), approval_id, t.PreviewRequest(checked_rows=rows))

    def pass_(self, person: Person, approval_id: str, *, checked: list[tuple[str, str, str]] | None = None,
              params: dict[str, Any] | None = None, fingerprint: str | None = None, request_key: str | None = None) -> t.CommandResult:
        """通过：不给 `checked` 时提交详情中当前勾选的行；不给 `fingerprint` 时按这些勾选先预览取得指纹。"""
        if checked is None:
            view = self.detail(person, approval_id).view
            checked = [(b.flow, b.key, r.ref.key) for b in view.affected if b.editable for r in b.rows if r.ref and r.checked]
        if fingerprint is None:
            fingerprint = self.preview(person, approval_id, checked).fingerprint
        request = t.PassRequest(request_key=request_key or self.request_key(), fingerprint=fingerprint,
                                checked_rows=[t.CheckedRow(flow=f, block=b, key=k) for f, b, k in checked], params=params or {})
        return self.service.pass_(self.ctx(person), approval_id, request)

    def reject(self, person: Person, approval_id: str, comment: str | None) -> t.CommandResult:
        return self.service.reject(self.ctx(person), approval_id, t.RejectRequest(request_key=self.request_key(), comment=comment))

    def withdraw(self, person: Person, approval_id: str, comment: str | None = None) -> t.CommandResult:
        return self.service.withdraw(self.ctx(person), approval_id, t.WithdrawRequest(request_key=self.request_key(), comment=comment))

    def frozen(self) -> set[tuple[str, str]]:
        with self.uow.begin() as uow:
            rows = uow.connection.exec_driver_sql("SELECT root_table, record_key FROM pf_approval_freeze").all()
        return {(r[0], r[1]) for r in rows}

    def record(self, approval_id: str) -> Any:
        with self.uow.begin() as uow:
            return self.store.load(uow, approval_id)

    def records(self, approval_id: str) -> Any:
        with self.uow.begin() as uow:
            return self.store.records(uow, approval_id)


def modify(entity: str, row_key: int | str, **changes: Any) -> dict[str, Any]:
    return {"entity": entity, "op": "modify", "rowKey": str(row_key), "changes": changes}


def cost(docid: int | str, *details: dict[str, Any], master: dict[str, Any] | None = None) -> dict[str, Any]:
    """成本核算页一张单据的修改；`master` 为主表的修改，不给时主表不改。"""
    head = {"op": "modify", "rowKey": str(docid), "changes": master} if master else {"op": "none", "rowKey": str(docid)}
    return {"entity": "COST_PINGGU", "master": head, "details": list(details)}


def goods(goods_id: int | str, **changes: Any) -> dict[str, Any]:
    """物料清单页（单表页）一行的修改。"""
    return {"entity": "COST_GOODS_PRICE", "master": {"op": "modify", "rowKey": str(goods_id), "changes": changes}, "details": []}
