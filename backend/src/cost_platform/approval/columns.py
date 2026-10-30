"""受影响单据修改表的列名（审批详情和批准时生成"修改内容"用，`view.py` 的 `_affected_table`）。

每张表经 `SchemaInspector` 只读一次，之后在进程内复用，表结构变更随部署重启生效（同 write-pipeline 的 `ColumnScales`）。
没有缓存时，每次计算"修改内容"都读一次修改表的列定义：审批通过要算两次（核对指纹、最终批准），每次通过多 2 条
`user_tab_columns`（d_cg 上为 T_COST_GOODS，`.reports/batch3-20261030/h2-approval/findings.md`）。
"""

from __future__ import annotations

from cost_platform.contracts.ports import SchemaInspector


class TableColumns:
    def __init__(self, inspector: SchemaInspector) -> None:
        self._inspector = inspector
        self._tables: dict[str, frozenset[str]] = {}

    def names(self, table: str) -> frozenset[str]:
        """表的列名（大写）；表不存在时为空集合，同样只读一次。"""
        key = table.upper()
        found = self._tables.get(key)
        if found is None:
            found = frozenset(name.upper() for name in (self._inspector.columns(table) or {}))
            self._tables[key] = found
        return found
