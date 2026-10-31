"""真实验证（d_cg，只读）：新建页面向导按关键字列出表和视图、导入列的标题取列注释（CF-20、T-CF-13）。

只查 d_cg 的数据字典（USER_OBJECTS、USER_TAB_COLUMNS、USER_COL_COMMENTS、USER_CONSTRAINTS、USER_SEQUENCES），
不写 PF_CONFIG_ITEM，不用 `test_oracle.py` 的 `ora` fixture（它会删、写 `CT_` 开头的配置项）。
依据的只读查询：`.reports/batch8-20261031/g5-config-caps/02-*`、`03-*`（2026-10-31，T_COST_GOODS 和 T_COST_GOODS_PRICE_V
没有列注释；T_COST_PINGGU_LQ 有两列注释，主键 DOCID，序列 T_COST_PINGGU_LQ_SEQ 已存在）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from cost_platform.config.cache import MemoryConfigCache
from cost_platform.contracts.types import WizardColumnsRequest

from .real_support import OracleEnv, engine  # noqa: F401 - fixture

pytestmark = pytest.mark.oracle


def test_wizard_search_and_comment_labels_on_d_cg(engine: Engine) -> None:  # noqa: F811
    """向导里输入"T_COST_GOODS"，列出物料表和物料清单视图，先表后视图；选液体成本核算主表 T_COST_PINGGU_LQ 导入列，
    COST_PERBOX、M_PERPACK 的标题是列注释，其余列是列名。"""
    service = OracleEnv(engine, MemoryConfigCache()).service
    found = [(o.name, o.type) for o in service.schema_objects("T_COST_GOODS").objects]
    assert ("T_COST_GOODS", "table") in found and ("T_COST_GOODS_PRICE_V", "view") in found
    assert all("T_COST_GOODS" in name for name, _ in found)
    assert [t for _, t in found] == sorted(t for _, t in found)

    columns = service.wizard_columns(WizardColumnsRequest(read_view=None, table="T_COST_PINGGU_LQ"))
    labels = {c.name: c.label for c in columns.columns}
    assert (columns.primary_key, columns.sequence.name, columns.sequence.exists) == ("DOCID", "T_COST_PINGGU_LQ_SEQ", True)
    assert (labels["COST_PERBOX"], labels["M_PERPACK"]) == ("每盒成本", "每中盒小盒数")
    assert labels["DOCID"] == "DOCID"
