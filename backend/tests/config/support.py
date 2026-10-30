"""config 测试共用的环境（模拟验证）。

- 数据库：contracts 的 `FakeUnitOfWorkFactory`（内存 SQLite）。PF_CONFIG_ITEM、PF_CONFIG_GENERATION 用本模块的迁移脚本建立；
  业务表和视图按 d_cg、cmx 的真实列建成表（只用于 SQL 解析检查，没有数据），另建 DUAL，并注册 DECODE、NVL 两个函数。
- 表结构：contracts 的 `FakeSchemaInspector`，内容与上面相同。
- Redis：`MemoryConfigCache`；实时事件：`FakeRealtimePublisher`；规则内核默认 `FakeRulesEngine`，需要真实计算时传入
  rules-core 的 `RulesEngine`。

表的列取自只读查询 `.reports/modules/config/01～03-*.sql`（d_cg：T_COST_PINGGU、T_COST_PINGGU_DTL、T_COST_GOODS 和两个明细视图；
cmx：T_COST_GOODS_PRICE_V 和液体成本的表、视图）。液体成本主表 T_COST_PINGGU_LQ 在这里按 T_COST_PINGGU 的列建（cmx 中为 50 列，
测试只用到 DOCID、GOODSNAME、COST_PERBOX、JGF_PERQP），这一点是简化的。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from cost_platform.config.cache import MemoryConfigCache
from cost_platform.config.deps import StaticDepartments, StaticSequences
from cost_platform.config.migrations import cf_0001_pf_config
from cost_platform.config.records import ItemRecord, item_id
from cost_platform.config.runtime import ConfigRuntime, RecoveryTask
from cost_platform.config.service import ConfigService
from cost_platform.config.snapshot import ConfigReader
from cost_platform.config.store import ConfigStore
from cost_platform.config.validation import Validator
from cost_platform.contracts.fakes import (
    FakeClock,
    FakeIdGenerator,
    FakeRealtimePublisher,
    FakeRulesEngine,
    FakeSchemaInspector,
    FakeUnitOfWorkFactory,
)
from cost_platform.contracts.ports import RulesEngine
from cost_platform.contracts.types import ColumnInfo, ConfigDraft, parse_wire

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
SEED = BACKEND / "seed" / "config"


def _cols(spec: str) -> list[ColumnInfo]:
    """`列名:类型 列名:类型 …`，类型 N 为 NUMBER，V 为 VARCHAR2，D 为 DATE，T 为 TIMESTAMP(6)。"""
    kinds = {"N": "NUMBER", "V": "VARCHAR2", "D": "DATE", "T": "TIMESTAMP(6)"}
    result = []
    for part in spec.split():
        name, kind = part.split(":")
        result.append(ColumnInfo(name=name, data_type=kinds[kind], nullable=True, length=200 if kind == "V" else None,
                                 precision=None, scale=None))
    return result


_PINGGU = ("GOODSID:N GOODSNAME:V STRENGTH:V MA_NO:V APEX_PL:N MAH:V P_PERPACK:N FORM:V S_PERBACK:N PACKTYPE:V X_PERBACK:N "
           "TOTAL_FL:N TOTAL_BC:N TOTAL_YL:N MEMO:V USESTATUS:V DOCID:N DOSAGE:V ANNUAL_QTY:N YIELD:N OUT_PRICE_F:N COST_PERQP:N "
           "CUSTOMID:N CUSTOMNAME:V COUNTRY:V PROJECTNO:V USEFLAG:N YIELD_TIME:D APEX_PL_TIME:D FMNAME:V FMRATE:N GOODSNAME_EN:V "
           "LIVERY:V M_PERPACK:N TRANPOSID:N PINGGU_CLASS:V BUSINESS_USER:V OUT_PRICE_RMB:N TOTAL_COST:N SALEMONEY:N JGF_BATCH:N "
           "COST_PERBOX:N JGF_PERQP:N ML_PERQP:N Y_JG_RE:N Y_ML:N Y_SALE:N")
_DTL = "DOCID:N GOODSID:N PER_HL:N EXADD_MATER:N PRICE:N MEMO:V DTLID:N CUSTOMER_SPECIFIED:N BATCH_QTY:N COST_BATCH:N"
_DTL_VIEW = ("DTLID:N DOCID:N GOODSID:N PER_HL:N PRICE:N BATCH_QTY:N COST_BATCH:N EXADD_MATER:N MEMO:V GOODSNAME_EN:V "
             "BASE_PRICE:N SUQTY:N GOODSNAME:V DTL_USEFLAG:V STANDARDTYPE:V FACTORYNAME:V GOODSTYPE:V CUSTOMER_SPECIFIED:N")
_GOODS = ("GOODSID:N GOODSNAME:V PRICE:N SUQTY:N USEFLAG:V FACTORYNAME:V STANDARDTYPE:V ISERP:N GOODSTYPE:V PACKTYPE:V "
          "UPDATE_BY:V GOODSNAME_EN:V ZX_PRICE:N")
_GOODS_VIEW = ("GOODSID:N GOODSNAME:V PRICE:N USEFLAG:V GOODSTYPE:V PACKTYPE:V FACTORYNAME:V DELETED:N CREATE_TIME:T "
               "UPDATE_TIME:T CREATE_BY:V UPDATE_BY:V ISERP:N ROW_CLASS_FLAG:V STANDARDTYPE:V GOODSNAME_EN:V ZX_PRICE:N")
_DTL_LQ = ("DOCID:N GOODSID:N GOODSNAME:V DTL_USEFLAG:V STANDARDTYPE:V PER_HL:N EXADD_MATER:N BATCH_QTY:N PRICE:N COST_BATCH:N "
           "MEMO:V DTLID:N FACTORYNAME:V FACTORYID:N MODIFYDATE:D BASE_PRICE:N SUQTY:N GOODSTYPE:V GOODSNAME_EN:V DELETED:N "
           "CREATE_TIME:T UPDATE_TIME:T CREATE_BY:V UPDATE_BY:V SOURCE_TYPE:V SOURCE_BATCH_QTY:N")
_DTL_LQ_VIEW = ("DTLID:N DOCID:N GOODSID:N PER_HL:N PRICE:N BATCH_QTY:N COST_BATCH:N EXADD_MATER:N MEMO:V DELETED:N "
                "CREATE_TIME:T UPDATE_TIME:T CREATE_BY:V UPDATE_BY:V GOODSNAME_EN:V BASE_PRICE:N SUQTY:N GOODSNAME:V "
                "DTL_USEFLAG:V STANDARDTYPE:V FACTORYNAME:V GOODSTYPE:V SOURCE_TYPE:V SOURCE_BATCH_QTY:N")

# 名称 →（table 或 view，列，主键）
TABLES: dict[str, tuple[str, list[ColumnInfo], str | None]] = {
    "T_COST_PINGGU": ("table", _cols(_PINGGU), "DOCID"),
    "T_COST_PINGGU_DTL": ("table", _cols(_DTL), "DTLID"),
    "V_COST_PINGGU_MATERIAL": ("view", _cols(_DTL_VIEW), None),
    "V_COST_PINGGU_PACKAGE": ("view", _cols(_DTL_VIEW), None),
    "T_COST_GOODS": ("table", _cols(_GOODS), "GOODSID"),
    "T_COST_GOODS_PRICE_V": ("view", _cols(_GOODS_VIEW), None),
    "T_COST_PINGGU_LQ": ("table", _cols(_PINGGU), "DOCID"),
    "T_COST_PINGGU_DTL_LQ": ("table", _cols(_DTL_LQ), "DTLID"),
    "V_COST_PINGGU_MATERIAL_LQ": ("view", _cols(_DTL_LQ_VIEW), None),
    "V_COST_PINGGU_PACKAGE_LQ": ("view", _cols(_DTL_LQ_VIEW), None),
    "T_CT_GOODS": ("table", _cols("GOODSID:N NAME:V PRICE:N"), "GOODSID"),
    # 成本核算主表的产品、客户、商务人员 Lookup（seed 的 costGoods、costCustomer、costUser）：列同 cmx 的同名视图
    # （.reports/batch3-20261030/h3-new-doc/q02、q04），d_cg 中要另建（见该目录的待人工审核 SQL）
    "V_COST_GOODS_LOOKUP": ("view", _cols("GOODSID:N GOODSNAME:V MA_NO:V APEX_PL:N MAH:V P_PERPACK:N S_PERBACK:N CUSTOMID:N "
                                          "CUSTOMNAME:V MEMO:V STRENGTH:V LIVERY:V GOODSNAME_EN:V"), None),
    "V_COST_CUSTOMER_LOOKUP": ("view", _cols("CUSTOMID:N CUSTOMNAME:V COUNTRY:V LIVERY:V TRANPOSID:N"), None),
    "V_COST_USER": ("view", _cols("USERNAME:V REAL_NAME:V"), None),
}
CMX_TABLES: dict[str, list[ColumnInfo]] = {
    "T_COST_BOM_GOODS_TREE_V": _cols("TREEID:V PID:V GOODSID:N GOODSNAME:V USEFLAG:V STANDARDTYPE:V LVCODE:N USEQTY:N ENTRYID:N"),
    "PUB_GOODS_V": _cols("GOODSID:N GOODSNAME:V GOODSNO:V PRICE:N SUQTY:N USEFLAG:V FACTORYNAME:V STANDARDTYPE:V ZX_PL:N "
                         "ZX_MINIMUM:N APPROVEDOCNO:V BASEUNITQTY:N ZX_CUSTOMERID:N CUSTOMNAME:V TARGETMARKET:V HOLDERSNAME:V "
                         "ISERP:N GOODSTYPE:V PACKTYPE:V TRANPOSNAME:V BOMID:N LASTSUQTY:N TRANPOSID:N"),
}
SEQUENCES = ["T_COST_PINGGU_SEQ", "T_COST_PINGGU_DTL_SEQ", "T_COST_GOODS_SEQ", "T_COST_PINGGU_LQ_SEQ",
             "T_COST_PINGGU_DTL_LQ_SEQ", "T_CT_GOODS_SEQ"]
# 1069：C06 7.9 样例中旧系统技术中心的编号；18：d_cg 中技术中心的部门编号（2026-10-30 经系统管理接口新建），
# seed 的审批流 TECH_CUSTOMER_MATERIAL 引用它
DEPARTMENTS = ["1069", "10", "18"]


def _decode(*args: Any) -> Any:
    """Oracle 的 DECODE：两个空值算相等。"""
    expr, rest = args[0], list(args[1:])
    default = rest.pop() if len(rest) % 2 == 1 else None
    for i in range(0, len(rest), 2):
        if rest[i] == expr or (rest[i] is None and expr is None):
            return rest[i + 1]
    return default


def install_sqlite(factory: FakeUnitOfWorkFactory, tables: dict[str, tuple[str, list[ColumnInfo], str | None]]) -> None:
    raw = factory.engine.raw_connection()
    raw.driver_connection.create_function("DECODE", -1, _decode)
    raw.driver_connection.create_function("NVL", 2, lambda a, b: b if a is None else a)
    raw.close()
    with factory.engine.begin() as connection:
        # cmx 的 BOM 树和物料视图（seed 的"由BOM生成明细"按旧 P_COST_BOM_INSERT 查它们，d_cg 中写作 CMX.<名称>）：
        # 另挂一个名为 CMX 的库建同名表，列取自只读查询 .reports/batch1-20261029/bom-price/01-BOM候选产品.sql
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS CMX")
        for name, columns in CMX_TABLES.items():
            connection.exec_driver_sql(f"CREATE TABLE CMX.{name} ({', '.join(f'{c.name} {c.data_type}' for c in columns)})")
        with Operations.context(MigrationContext.configure(connection)):
            cf_0001_pf_config.upgrade()
        connection.exec_driver_sql("CREATE TABLE DUAL (DUMMY VARCHAR2(1))")
        connection.exec_driver_sql("INSERT INTO DUAL VALUES ('X')")
        for name, (_, columns, _key) in tables.items():
            connection.exec_driver_sql(f"CREATE TABLE {name} ({', '.join(f'{c.name} {c.data_type}' for c in columns)})")


class Env:
    """一个后端进程的 config：保存服务、快照读取、预热和恢复任务，共用同一个"Oracle"（SQLite）和"Redis"（内存）。"""

    def __init__(self, engine: RulesEngine | None = None) -> None:
        self.uow = FakeUnitOfWorkFactory()
        # 与替代实现的引擎相同，只是允许在别的线程中使用：FastAPI 的同步接口在线程池中执行（test_router）
        self.uow.engine = create_engine("sqlite://", poolclass=StaticPool,
                                        connect_args={"detect_types": sqlite3.PARSE_DECLTYPES, "check_same_thread": False})
        install_sqlite(self.uow, TABLES)
        self.schema = FakeSchemaInspector()
        for name, (kind, columns, key) in TABLES.items():
            if kind == "table":
                self.schema.add_table(name, columns, key)
            else:
                self.schema.add_view(name, columns)
        self.sequences = StaticSequences(SEQUENCES)
        self.departments = StaticDepartments(DEPARTMENTS)
        self.engine: Any = engine or FakeRulesEngine()
        self.cache = MemoryConfigCache()
        self.publisher = FakeRealtimePublisher()
        self.clock = FakeClock()
        self.ids = FakeIdGenerator()
        self.validator = Validator(self.schema, self.sequences, self.departments, self.engine)
        self.hook: Callable[[str], None] | None = None
        self.service = ConfigService(self.uow, self.validator, self.cache, self.publisher, self.clock, self.ids,
                                     step_hook=lambda step: self.hook(step) if self.hook else None)
        self.reader = self.new_reader()

    def new_reader(self) -> ConfigReader:
        """另一个后端进程（或进程重启后）的快照读取：进程缓存是空的。"""
        return ConfigReader(self.uow, self.cache, self.engine, self.publisher, self.ids)

    def runtime(self, reader: ConfigReader | None = None, **kwargs: Any) -> ConfigRuntime:
        return ConfigRuntime(self.uow, self.cache, reader or self.reader, **kwargs)

    def recovery(self) -> RecoveryTask:
        return RecoveryTask(self.uow, self.cache, self.publisher, self.clock, self.ids)

    def save(self, items: list[ConfigDraft], user: str = "1") -> Any:
        return self.service.save(items, user)

    # ---------------------------------------------------------------- 直接查"Oracle"

    def records(self) -> dict[str, ItemRecord]:
        with self.uow.engine.connect() as connection:
            _, found = ConfigStore().read_all(_Uow(connection))
        return found

    def generation(self) -> int:
        with self.uow.engine.connect() as connection:
            return int(connection.execute(text("SELECT generation FROM pf_config_generation WHERE id = 1")).scalar_one())

    def stored(self, config_type: str, key: str) -> dict[str, Any] | None:
        found = self.records().get(item_id(config_type, key))
        return None if found is None else found.content()


class _Uow:
    def __init__(self, connection: Any) -> None:
        self.connection = connection


class KilledProcess(BaseException):
    """模拟进程在保存的某一步之后退出：不是 Exception，保存流程不会捕获它。"""


def kill_after(step: str) -> Callable[[str], None]:
    def hook(current: str) -> None:
        if current == step:
            raise KilledProcess(step)
    return hook


# ---------------------------------------------------------------- 配置项

def draft(config_type: str, key: str, content: dict[str, Any], name: str | None = None) -> ConfigDraft:
    return ConfigDraft(type=config_type, key=key, name=name or key, content=content)


def seed_drafts() -> list[ConfigDraft]:
    """`backend/seed/config/` 的配置项（成本核算配置：链路 0 手写，2026-10-29 按旧系统补上计算规则、按钮和物料 Lookup）。"""
    return [parse_wire(ConfigDraft, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(SEED.glob("*.json"))]


def seed_without_rules() -> list[ConfigDraft]:
    """seed 中除计算规则以外的配置项。seed 的规则配置项（`rule.R_*.json`）是成本核算的 17 条计算规则，由
    `rules-core/fixtures/gen_packs.py` 的 COST_RULES（公式与 cmx 虚拟列一致）按 C06 第 5 节写成，order 按旧系统页面规则；
    只测某一条规则的用例用这里的配置项，不带 seed 的规则。"""
    return [d for d in seed_drafts() if d.type != "rule"]


def doc_json(prefix: str, index: int) -> Any:
    from tests.contracts.support import doc_json as read

    return read(prefix, index)


def flow_samples() -> list[ConfigDraft]:
    """C06 7.8、7.9、7.10 三个审批流样例。"""
    return [parse_wire(ConfigDraft, doc_json("C06", i)) for i in (6, 7, 8)]


def gen_packs() -> Any:
    spec = importlib.util.spec_from_file_location("gen_packs", ROOT / "rules-core" / "fixtures" / "gen_packs.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GRID = {"sideBar": True, "cellSelection": True, "groupBy": []}


def goods_price_items() -> list[ConfigDraft]:
    """物料清单（C06 7.10 的所属页面）：实体经视图 T_COST_GOODS_PRICE_V 读取、写表 T_COST_GOODS，ERP 行 ISERP = 1。"""
    def f(name: str, kind: str = "number", source: str = "own", role: str = "input", column: str | None = "") -> dict[str, Any]:
        return {"name": name, "column": name if column == "" else column, "label": name, "type": kind, "source": source, "role": role}

    entity = {"table": "T_COST_GOODS", "readView": "T_COST_GOODS_PRICE_V", "primaryKey": "GOODSID", "freezable": True,
              "erpRow": {"column": "ISERP", "value": "1", "localValue": "0"},
              "fields": [f("GOODSID", role="system"), f("GOODSNAME", "text", "erp"), f("PRICE", source="erp"), f("ZX_PRICE"),
                         f("ISERP"), f("USEFLAG", "text"), f("ROW_CLASS_FLAG", "text", column=None)]}
    page = {"title": "物料清单及成本", "layout": "single", "detailMode": "tabs", "audit": True,
            "saveOperation": "GOODS_PRICE_MANAGE.save", "master": {"entity": "COST_GOODS_PRICE", "grid": GRID}}
    operation = {"label": "保存", "kind": "save", "writableFields": {"COST_GOODS_PRICE": ["ZX_PRICE"]},
                 "impact": ["COST_GOODS_PRICE"], "propagation": "continue"}
    return [draft("entity", "COST_GOODS_PRICE", entity, "物料清单"), draft("operation", "GOODS_PRICE_MANAGE.save", operation),
            draft("page", "GOODS_PRICE_MANAGE", page, "物料清单及成本")]


def liquid_items() -> list[ConfigDraft]:
    """液体成本核算（C06 7.10 冻结和受影响的 T_COST_PINGGU_DTL_LQ）。"""
    def f(name: str, kind: str = "number", role: str = "input", column: str | None = "") -> dict[str, Any]:
        return {"name": name, "column": name if column == "" else column, "label": name, "type": kind, "source": "own", "role": role}

    master = {"table": "T_COST_PINGGU_LQ", "primaryKey": "DOCID", "freezable": True,
              "fields": [f("DOCID", role="system"), f("GOODSNAME", "text"), f("COST_PERBOX", role="calculated"),
                         f("JGF_PERQP", role="calculated")],
              "details": [{"entity": "COST_MATERIAL_LQ", "parentKey": "DOCID"}, {"entity": "COST_PACKAGE_LQ", "parentKey": "DOCID"}]}
    # 物料名由明细视图从物料表取，明细表自存的那份不复制（DB-03）；与 seed 的 COST_MATERIAL 相同，column 为 null
    detail_fields = [f("DTLID", role="system"), f("DOCID", role="system"), f("GOODSID"), f("GOODSNAME", "text", column=None), f("PRICE"),
                     f("COST_BATCH", role="calculated")]
    items = [draft("entity", "COST_PINGGU_LQ", master, "液体成本核算")]
    for code, view in (("COST_MATERIAL_LQ", "V_COST_PINGGU_MATERIAL_LQ"), ("COST_PACKAGE_LQ", "V_COST_PINGGU_PACKAGE_LQ")):
        items.append(draft("entity", code, {"table": "T_COST_PINGGU_DTL_LQ", "readView": view, "primaryKey": "DTLID",
                                            "freezable": True, "fields": detail_fields}))
    page = {"title": "液体成本核算", "layout": "masterDetail", "detailMode": "tabs", "audit": True,
            "saveOperation": "COST_PINGGU_LQ.save", "master": {"entity": "COST_PINGGU_LQ", "grid": GRID},
            "details": [{"entity": "COST_MATERIAL_LQ", "title": "原辅料", "grid": GRID},
                        {"entity": "COST_PACKAGE_LQ", "title": "包材", "grid": GRID}]}
    operation = {"label": "保存", "kind": "save", "writableFields": {"COST_MATERIAL_LQ": ["PRICE"], "COST_PACKAGE_LQ": ["PRICE"]},
                 "impact": ["COST_PINGGU_LQ", "COST_MATERIAL_LQ", "COST_PACKAGE_LQ"], "propagation": "continue"}
    return [*items, draft("operation", "COST_PINGGU_LQ.save", operation), draft("page", "COST_PINGGU_LQ", page, "液体成本核算")]


def base_world() -> list[ConfigDraft]:
    """seed 的成本核算配置，加上物料清单和液体成本核算：三个审批流样例引用的页面、实体都在其中。"""
    return [*seed_drafts(), *goods_price_items(), *liquid_items()]
