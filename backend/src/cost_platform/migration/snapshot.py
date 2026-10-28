"""读取旧元数据：只读连接 cmx，把要迁移的页面用到的旧配置读成一份快照（MG-01、MG-11）。

快照是 `{查询名: [行, ...]}`，每行是 `{列名(大写): 值}`。值只有 JSON 的基本类型：整数为 int，其他数值为十进制文本，
日期时间为 ISO 文本，CLOB、LONG 为完整文本。每条查询都按主键排序，同样的旧数据得到同样的快照。

读取分两步：先读页面、表、列、规则、权限、导出、Lookup、审批流，再按其中引用的表、视图和存储过程读取数据字典
（ALL_TAB_COLS、ALL_VIEWS、ALL_OBJECTS、ALL_SOURCE、ALL_DEPENDENCIES）。所有语句只有 SELECT，在
`ConnectionFactory.legacy_readonly` 的只读事务中执行。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

    from cost_platform.contracts.ports import ConnectionFactory

Row = dict[str, Any]
Snapshot = dict[str, list[Row]]

PAGES: tuple[str, ...] = ("cost-pinggu", "cost-pinggu-lq", "goods-price-manage")
"""本次迁移的旧页面，按迁移先后排列。"""

_PAGE_BINDS = ", ".join(f":p{i}" for i in range(len(PAGES)))

# 第一步：旧配置。键为快照中的查询名，也用作来源记录中的旧表名。
_CONFIG_QUERIES: dict[str, str] = {
    "CMX.T_COST_TABLE_METADATA": f"""
        SELECT ID, TABLE_CODE, TABLE_NAME, QUERY_VIEW, TARGET_TABLE, SEQUENCE_NAME, PK_COLUMN, PARENT_TABLE_CODE,
               PARENT_FK_COLUMN, AUDIT_ENABLED, VALIDATION_RULES, ACTION_RULES, DESCRIPTION, PAGE_CODE, COMPONENT_KEY,
               SOURCE_TABLE_CODE
          FROM CMX.T_COST_TABLE_METADATA
         WHERE DELETED = 0 AND PAGE_CODE IN ({_PAGE_BINDS})
         ORDER BY ID""",
    "CMX.T_COST_COLUMN_METADATA": f"""
        SELECT C.ID, C.TABLE_METADATA_ID, C.COLUMN_NAME, C.QUERY_COLUMN, C.TARGET_COLUMN, C.HEADER_TEXT, C.DATA_TYPE,
               C.DISPLAY_ORDER, C.SORTABLE, C.FILTERABLE, C.IS_VIRTUAL, C.DICT_TYPE, C.VISIBLE, C.EDITABLE, C.REQUIRED,
               C.SEARCHABLE, C.WIDTH, C.PINNED, C.CELL_EDITOR, C.DEFAULT_VALUE, C.RULES_CONFIG
          FROM CMX.T_COST_COLUMN_METADATA C
         WHERE C.DELETED = 0
           AND C.TABLE_METADATA_ID IN (SELECT T.ID FROM CMX.T_COST_TABLE_METADATA T
                                        WHERE T.DELETED = 0 AND T.PAGE_CODE IN ({_PAGE_BINDS}))
         ORDER BY C.TABLE_METADATA_ID, C.DISPLAY_ORDER, C.ID""",
    "CMX.T_COST_PAGE_COMPONENT": f"""
        SELECT ID, PAGE_CODE, COMPONENT_KEY, COMPONENT_TYPE, PARENT_KEY, COMPONENT_CONFIG, REF_TABLE_CODE, SLOT_NAME,
               SORT_ORDER, DESCRIPTION
          FROM CMX.T_COST_PAGE_COMPONENT
         WHERE DELETED = 0 AND PAGE_CODE IN ({_PAGE_BINDS})
         ORDER BY ID""",
    "CMX.T_COST_PAGE_RULE": f"""
        SELECT ID, PAGE_CODE, COMPONENT_KEY, RULE_TYPE, RULES, SORT_ORDER, DESCRIPTION
          FROM CMX.T_COST_PAGE_RULE
         WHERE DELETED = 0 AND PAGE_CODE IN ({_PAGE_BINDS})
         ORDER BY ID""",
    "CMX.T_COST_ROLE": "SELECT ID, ROLE_CODE, ROLE_NAME, DESCRIPTION FROM CMX.T_COST_ROLE ORDER BY ID",
    "CMX.T_COST_ROLE_PAGE": """
        SELECT ID, ROLE_ID, PAGE_CODE, BUTTON_POLICY, COLUMN_POLICY, ROW_POLICY
          FROM CMX.T_COST_ROLE_PAGE
         ORDER BY ID""",
    "CMX.T_COST_RESOURCE": """
        SELECT ID, RESOURCE_NAME, RESOURCE_TYPE, PAGE_CODE, ICON, ROUTE, PARENT_ID, SORT_ORDER, IS_HARDCODED
          FROM CMX.T_COST_RESOURCE
         ORDER BY ID""",
    "CMX.T_COST_EXPORT_CONFIG": f"""
        SELECT ID, EXPORT_CODE, EXPORT_NAME, PAGE_CODE, MASTER_SQL, MASTER_TABLE_ALIAS, PK_COLUMN, PAGE_VIEW_ALIAS,
               PAGE_FK_COLUMN, MASTER_LINK_COLUMN, COLUMNS, MASTER_SHEET_NAME, DISPLAY_ORDER, FONT_NAME
          FROM CMX.T_COST_EXPORT_CONFIG
         WHERE NVL(DELETED, 0) = 0 AND PAGE_CODE IN ({_PAGE_BINDS})
         ORDER BY ID""",
    "CMX.T_COST_EXPORT_CONFIG_DETAIL": f"""
        SELECT D.ID, D.EXPORT_CONFIG_ID, D.TAB_KEY, D.SHEET_NAME, D.DETAIL_SQL, D.MASTER_TABLE_ALIAS,
               D.DETAIL_TABLE_ALIAS, D.DETAIL_LINK_COLUMN, D.COLUMNS, D.DISPLAY_ORDER
          FROM CMX.T_COST_EXPORT_CONFIG_DETAIL D
         WHERE D.EXPORT_CONFIG_ID IN (SELECT E.ID FROM CMX.T_COST_EXPORT_CONFIG E
                                       WHERE NVL(E.DELETED, 0) = 0 AND E.PAGE_CODE IN ({_PAGE_BINDS}))
         ORDER BY D.ID""",
    "CMX.T_COST_LOOKUP_CONFIG": """
        SELECT ID, LOOKUP_CODE, LOOKUP_NAME, DATA_SOURCE, DISPLAY_COLUMNS, VALUE_FIELD, LABEL_FIELD
          FROM CMX.T_COST_LOOKUP_CONFIG
         WHERE DELETED = 0
         ORDER BY ID""",
    "CMX.T_COST_DICTIONARY_TYPE": """
        SELECT ID, TYPE_CODE, TYPE_NAME, DESCRIPTION FROM CMX.T_COST_DICTIONARY_TYPE WHERE DELETED = 0 ORDER BY ID""",
    "CMX.T_COST_DICTIONARY_ITEM": """
        SELECT ID, TYPE_ID, ITEM_CODE, ITEM_NAME, ITEM_VALUE, SORT_ORDER, EXTRA_CONFIG
          FROM CMX.T_COST_DICTIONARY_ITEM
         WHERE DELETED = 0
         ORDER BY ID""",
    "CMX.WF_FLOW_DEF": f"""
        SELECT FLOW_ID, PAGE_CODE, PAGE_NAME, FLOW_NAME, FLOW_VERSION, IS_ENABLED, FLOW_PRIORITY, REMARK
          FROM CMX.WF_FLOW_DEF
         WHERE PAGE_CODE IN ({_PAGE_BINDS})
         ORDER BY FLOW_ID""",
    "CMX.WF_FLOW_NODE": f"""
        SELECT N.NODE_ID, N.FLOW_ID, N.APPROVAL_LEVEL, N.NODE_NAME, N.APPROVAL_MODE, N.IS_ENABLED, N.CONDITION_MODE,
               N.LOGIC_TREE, N.SQL_EXPR, N.ON_ERROR, N.ACTION_CONFIG
          FROM CMX.WF_FLOW_NODE N
         WHERE N.FLOW_ID IN (SELECT F.FLOW_ID FROM CMX.WF_FLOW_DEF F WHERE F.IS_ENABLED = 1 AND F.PAGE_CODE IN ({_PAGE_BINDS}))
         ORDER BY N.NODE_ID""",
    "CMX.WF_FLOW_APPROVER": f"""
        SELECT A.ID, A.NODE_ID, A.APPLY_DEPT_ID, A.APPLY_DEPT_NAME, A.TARGET_TYPE, A.TARGET_USER_ID,
               A.TARGET_USER_NAME, A.TARGET_ROLE_ID, A.TARGET_ROLE_CODE, A.TARGET_ROLE_NAME, A.SORT_ORDER, A.IS_ENABLED,
               A.CONDITION_MODE, A.LOGIC_TREE, A.SQL_EXPR, A.ON_ERROR
          FROM CMX.WF_FLOW_APPROVER A
         WHERE A.NODE_ID IN (SELECT N.NODE_ID FROM CMX.WF_FLOW_NODE N
                              WHERE N.FLOW_ID IN (SELECT F.FLOW_ID FROM CMX.WF_FLOW_DEF F
                                                   WHERE F.IS_ENABLED = 1 AND F.PAGE_CODE IN ({_PAGE_BINDS})))
         ORDER BY A.ID""",
    "CMX.WF_FLOW_CONDITION": f"""
        SELECT CONDITION_ID, FLOW_ID, CONDITION_NAME, CONDITION_MODE, LOGIC_TREE, SQL_EXPR, ON_ERROR, IS_ENABLED
          FROM CMX.WF_FLOW_CONDITION
         WHERE FLOW_ID IN (SELECT F.FLOW_ID FROM CMX.WF_FLOW_DEF F WHERE F.IS_ENABLED = 1 AND F.PAGE_CODE IN ({_PAGE_BINDS}))
         ORDER BY CONDITION_ID""",
    "CMX.WF_FLOW_CONFIG": f"""
        SELECT FLOW_ID, FAMILY_ID, CONFIG_JSON
          FROM CMX.WF_FLOW_CONFIG
         WHERE FLOW_ID IN (SELECT F.FLOW_ID FROM CMX.WF_FLOW_DEF F WHERE F.IS_ENABLED = 1 AND F.PAGE_CODE IN ({_PAGE_BINDS}))
         ORDER BY FLOW_ID""",
}

_NAME = re.compile(r"^[A-Z][A-Z0-9_$#]*$")


def read_snapshot(connections: ConnectionFactory) -> Snapshot:
    """在一个只读事务中读出全部旧元数据。"""
    binds = {f"p{i}": code for i, code in enumerate(PAGES)}
    snapshot: Snapshot = {}
    with connections.legacy_readonly() as connection:
        for name, sql in _CONFIG_QUERIES.items():
            snapshot[name] = _fetch(connection, sql, binds if ":p0" in sql else {})
        objects = sorted(_referenced_objects(snapshot))
        procedures = sorted(_referenced_procedures(snapshot))
        snapshot.update(_dictionary(connection, objects, procedures))
    return snapshot


def _referenced_objects(snapshot: Snapshot) -> set[str]:
    names: set[str] = set()
    for row in snapshot["CMX.T_COST_TABLE_METADATA"]:
        names.update(n.upper() for n in (row["QUERY_VIEW"], row["TARGET_TABLE"]) if n)
    for row in snapshot["CMX.T_COST_LOOKUP_CONFIG"]:
        if row["DATA_SOURCE"]:
            names.add(row["DATA_SOURCE"].upper())
    return {n for n in names if _NAME.match(n)}


def _referenced_procedures(snapshot: Snapshot) -> set[str]:
    """组件按钮和审批动作调用的存储过程（取包名或过程名）。"""
    found: set[str] = set()
    texts = [r["COMPONENT_CONFIG"] or "" for r in snapshot["CMX.T_COST_PAGE_COMPONENT"]]
    texts += [r["ACTION_CONFIG"] or "" for r in snapshot["CMX.WF_FLOW_NODE"]]
    texts += [r["CONFIG_JSON"] or "" for r in snapshot["CMX.WF_FLOW_CONFIG"]]
    for value in texts:
        for match in re.finditer(r'"procedure"\s*:\s*"([A-Za-z0-9_$#.]+)"', value):
            found.add(match.group(1).split(".")[0].upper())
    return found


def _in_list(prefix: str, values: Sequence[str]) -> tuple[str, dict[str, str]]:
    binds = {f"{prefix}{i}": v for i, v in enumerate(values)}
    return ", ".join(f":{k}" for k in binds) or "NULL", binds


def _dictionary(connection: Connection, objects: Sequence[str], procedures: Sequence[str]) -> Snapshot:
    obj_in, obj_binds = _in_list("o", objects)
    proc_in, proc_binds = _in_list("s", procedures)
    queries = {
        "ALL_OBJECTS": (f"""
            SELECT OBJECT_NAME, OBJECT_TYPE FROM ALL_OBJECTS
             WHERE OWNER = 'CMX' AND OBJECT_TYPE IN ('TABLE', 'VIEW') AND OBJECT_NAME IN ({obj_in})
             ORDER BY OBJECT_NAME, OBJECT_TYPE""", obj_binds),
        "ALL_TAB_COLS": (f"""
            SELECT TABLE_NAME, COLUMN_ID, COLUMN_NAME, DATA_TYPE, DATA_PRECISION, DATA_SCALE, NULLABLE,
                   VIRTUAL_COLUMN, DATA_DEFAULT
              FROM ALL_TAB_COLS
             WHERE OWNER = 'CMX' AND HIDDEN_COLUMN = 'NO' AND TABLE_NAME IN ({obj_in})
             ORDER BY TABLE_NAME, COLUMN_ID""", obj_binds),
        "ALL_VIEWS": (f"""
            SELECT VIEW_NAME, TEXT FROM ALL_VIEWS WHERE OWNER = 'CMX' AND VIEW_NAME IN ({obj_in}) ORDER BY VIEW_NAME""",
                      obj_binds),
        "ALL_SOURCE": (f"""
            SELECT NAME, TYPE, LINE, TEXT FROM ALL_SOURCE
             WHERE OWNER = 'CMX' AND NAME IN ({proc_in}) AND TYPE IN ('PROCEDURE', 'PACKAGE BODY')
             ORDER BY NAME, TYPE, LINE""", proc_binds),
        "ALL_DEPENDENCIES": (f"""
            SELECT NAME, TYPE, REFERENCED_OWNER, REFERENCED_NAME, REFERENCED_TYPE FROM ALL_DEPENDENCIES
             WHERE OWNER = 'CMX' AND NAME IN ({proc_in}) AND REFERENCED_OWNER = 'CMX'
               AND REFERENCED_TYPE IN ('TABLE', 'VIEW', 'PROCEDURE', 'PACKAGE')
             ORDER BY NAME, TYPE, REFERENCED_NAME, REFERENCED_TYPE""", proc_binds),
    }
    return {name: _fetch(connection, sql, binds) for name, (sql, binds) in queries.items()}


def _fetch(connection: Connection, sql: str, binds: dict[str, str]) -> list[Row]:
    result = connection.execute(text(sql), binds)
    keys = [k.upper() for k in result.keys()]
    return [{k: _value(v) for k, v in zip(keys, row, strict=True)} for row in result]


def _value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        value = Decimal(repr(value))
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "read"):
        return value.read()
    return str(value)


def dump_snapshot(snapshot: Snapshot, path: Path) -> None:
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load_snapshot(path: Path) -> Snapshot:
    data: Snapshot = json.loads(path.read_text(encoding="utf-8"))
    return data


def rows(snapshot: Snapshot, name: str) -> Iterable[Row]:
    return snapshot.get(name, [])
