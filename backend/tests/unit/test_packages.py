"""T-AS-1：确认每个模块的包都能导入。"""

import importlib

import pytest

MODULES = [
    "contracts", "config", "identity", "authz", "pipeline", "approval", "operations",
    "delivery", "realtime", "queries", "db_core", "migration", "assembly",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_package_imports(name: str) -> None:
    module = importlib.import_module(f"cost_platform.{name}")
    assert module.__name__ == f"cost_platform.{name}"