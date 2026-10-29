"""`EntityDirectory` 的真实实现 `PublishedEntities`（C08 第 4 节）：模拟验证（SQLite 上的 PF_ 表、内存 Redis）。
d_cg 上的同一套契约测试在 test_oracle.py。"""

from __future__ import annotations

import pytest

from cost_platform.config.entities import PublishedEntities
from cost_platform.contracts.types import ConfigDraft
from tests.contracts.test_entity_directory import EntityDirectoryContract

from .support import Env, draft, goods_price_items, seed_drafts


def entity_drafts() -> list[ConfigDraft]:
    """契约测试的四个实体：seed 的成本核算主表和两个明细（同在 T_COST_PINGGU_DTL），加上物料清单的实体（T_COST_GOODS）。
    契约测试的 ENTITIES 只是写法示意（物料清单的两个字段同名），不能经保存流程保存，所以用这几份真实配置。"""
    return [*(d for d in seed_drafts() if d.type == "entity"), *(d for d in goods_price_items() if d.type == "entity")]


class TestPublishedEntities(EntityDirectoryContract):
    @pytest.fixture
    def directory(self) -> PublishedEntities:
        env = Env()
        env.save(entity_drafts())
        return PublishedEntities(env.uow, env.reader)


def test_cached_by_generation() -> None:
    """代号没变时用缓存，不读 Oracle；保存后读到新发布的实体配置。"""
    env = Env()
    env.save(entity_drafts())
    directory = PublishedEntities(env.uow, env.reader)
    assert directory.entity("COST_GOODS_PRICE").read_view == "T_COST_GOODS_PRICE_V"
    assert directory.master_of("COST_MATERIAL") == ("COST_PINGGU", "DOCID")
    assert directory.oracle_reads == 1
    goods = next(d for d in entity_drafts() if d.key == "COST_GOODS_PRICE")
    fields = [{**f, "label": "物料名称（改）"} if f["name"] == "GOODSNAME" else f for f in goods.content["fields"]]
    env.save([draft("entity", goods.key, {**goods.content, "fields": fields}, goods.name)])
    assert next(f.label for f in directory.entity("COST_GOODS_PRICE").fields if f.name == "GOODSNAME") == "物料名称（改）"
    assert directory.oracle_reads == 2
