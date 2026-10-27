"""`PermissionChecker` 的契约测试（C08 第 7 节）。

真实实现（authz）的测试继承 `PermissionCheckerContract`，提供 `harness` fixture，实现 `PermissionCheckerHarness`：
按角色配置安排好下面各项的场景。各种 `buttons`、两种行权限写法的转换由 authz 自己的测试（T-AZ-1）验证。
"""

from __future__ import annotations

import re
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakePermissionChecker
from cost_platform.contracts.ports import PermissionChecker
from cost_platform.contracts.types import ExecutionContext, SqlCondition

from .support import context


class PermissionCheckerHarness(Protocol):
    checker: PermissionChecker

    def context(self) -> ExecutionContext:
        """执行上下文，其中的角色配置按下面各项安排。"""
        ...

    allowed: tuple[str, str | None]
    """（操作、页面）：角色可以执行。"""
    denied: tuple[str, str | None]
    """（操作、页面）：角色不能执行。"""
    unrestricted: tuple[str, str]
    """（页面、实体）：角色在这个页面没有行权限。"""
    restricted: tuple[str, str]
    """（页面、实体）：行权限条件引用了 `${userId}`。"""
    editable: tuple[str, str]
    """（页面、实体）：页面中有可编辑的字段。"""
    export_allowed: tuple[str, str]
    """（页面、导出编码）：角色可以使用这个导出配置。"""
    export_denied: tuple[str, str]


class PermissionCheckerContract:
    @pytest.fixture
    def harness(self) -> PermissionCheckerHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_can_run(self, harness: PermissionCheckerHarness) -> None:
        ctx = harness.context()
        assert harness.checker.can_run(ctx, *harness.allowed) is True
        assert harness.checker.can_run(ctx, *harness.denied) is False

    def test_no_row_policy_is_none(self, harness: PermissionCheckerHarness) -> None:
        assert harness.checker.row_condition(harness.context(), *harness.unrestricted) is None

    def test_row_condition_uses_bind_variables(self, harness: PermissionCheckerHarness) -> None:
        """占位符已换成绑定变量名，SQL 文本中不出现 `${…}`；绑定变量的值在 binds 中。"""
        ctx = harness.context()
        condition = harness.checker.row_condition(ctx, *harness.restricted)
        assert isinstance(condition, SqlCondition)
        assert "${" not in condition.sql
        assert condition.binds
        for name in condition.binds:
            assert re.search(rf":{re.escape(name)}\b", condition.sql), (name, condition.sql)
        assert ctx.identity.user_id in condition.binds.values()

    def test_writable_fields_is_frozenset(self, harness: PermissionCheckerHarness) -> None:
        fields = harness.checker.writable_fields(harness.context(), *harness.editable)
        assert isinstance(fields, frozenset)
        assert fields and all(isinstance(f, str) for f in fields)

    def test_can_export(self, harness: PermissionCheckerHarness) -> None:
        ctx = harness.context()
        assert harness.checker.can_export(ctx, *harness.export_allowed) is True
        assert harness.checker.can_export(ctx, *harness.export_denied) is False


class FakePermissionCheckerHarness:
    allowed = ("COST_PINGGU.save", "COST_PINGGU")
    denied = ("COST_PINGGU.syncPrice", "COST_PINGGU")
    unrestricted = ("GOODS_PRICE_MANAGE", "COST_GOODS_PRICE")
    restricted = ("COST_PINGGU", "COST_PINGGU")
    editable = ("COST_PINGGU", "COST_MATERIAL")
    export_allowed = ("COST_PINGGU", "cost-pinggu-export")
    export_denied = ("COST_PINGGU", "other-export")

    def __init__(self) -> None:
        self.checker = FakePermissionChecker(allow_all=False)
        self._ctx = context("112")
        self.checker.allow(*self.allowed)
        self.checker.set_rows(*self.restricted, SqlCondition(sql="CREATE_BY = :p_user_id", binds={"p_user_id": "112"}))
        self.checker.set_writable(*self.editable, ["GOODSID", "USAGE", "PRICE"])
        self.checker.allow_export(*self.export_allowed)

    def context(self) -> ExecutionContext:
        return self._ctx


class TestFakePermissionChecker(PermissionCheckerContract):
    @pytest.fixture
    def harness(self) -> FakePermissionCheckerHarness:
        return FakePermissionCheckerHarness()


def test_fake_defaults() -> None:
    """替代实现：没有预设时按 allow_all 判断，没有行权限，可写字段为空。"""
    checker = FakePermissionChecker()
    ctx = context()
    assert checker.can_run(ctx, "X.save", "X") is True
    assert checker.can_export(ctx, "X", "e") is True
    assert checker.row_condition(ctx, "X", "X") is None
    assert checker.writable_fields(ctx, "X", "X") == frozenset()
    checker.deny("X.save", "X")
    assert checker.can_run(ctx, "X.save", "X") is False
