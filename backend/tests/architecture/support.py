"""架构检查共用的读取工具：源码文件、导入解析、插件清单、端口清单、方法调用索引。

插件清单按 `.reports/modules/plugin-spec.md` 的约定取：导入 `cost_platform.<模块>.plugin` 和 `cost_platform.assembly` 下的
每个模块，找其中定义的、有 `name`、`provides`、`requires`、`setup` 的类，只读类属性，不创建实例、不运行 setup。
"""

from __future__ import annotations

import ast
import importlib
import inspect
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from fastapi import APIRouter

from cost_platform.contracts import ports as ports_module
from cost_platform.contracts.registry import MULTI_PORTS

BACKEND = Path(__file__).resolve().parents[2]
SRC = BACKEND / "src"
PACKAGE = SRC / "cost_platform"
REPORT = BACKEND.parent / ".reports" / "modules" / "architecture-report.md"

ASSEMBLY = "assembly"
CONTRACTS = "contracts"

# ---------------------------------------------------------------- 端口的例外（用户 2026-10-29 定）

NOT_REGISTERED: dict[str, str] = {
    "ConfigImporter": "只为迁移服务，migration 暂停",
    "AccountImporter": "只为迁移服务，migration 暂停",
    "PersonalConfigImporter": "只为迁移服务，migration 暂停",
    "UnitOfWork": "由 UnitOfWorkFactory.begin 返回，不单独注册",
    "ConfigSnapshot": "由 ConfigSnapshotReader.read 返回，不单独注册",
}
"""不检查提供方个数，也不检查使用方。"""

NO_USER_REQUIRED: dict[str, str] = {
    **NOT_REGISTERED,
    "ConnectionFactory": "只供 migration 读 cmx（migration 暂停），db-core 照样提供",
}
"""不检查"提供方模块以外至少有一个使用方"。"""

RETURNED_BY: dict[str, str] = {"UnitOfWork": "UnitOfWorkFactory", "ConfigSnapshot": "ConfigSnapshotReader"}
"""不单独注册的端口：它的提供方模块按返回它的端口算（报告第 5 条用）。"""


# ---------------------------------------------------------------- 源码文件

@dataclass(frozen=True)
class Source:
    path: Path
    module: str  # 例如 cost_platform.config.service
    is_package: bool  # __init__.py

    @property
    def rel(self) -> str:
        return self.path.relative_to(BACKEND).as_posix()

    @property
    def owner(self) -> str:
        """所属的顶层模块（config、assembly、contracts……）；根包 cost_platform/__init__.py 为空字符串。"""
        parts = self.module.split(".")
        return parts[1] if len(parts) > 1 else ""

    def tree(self) -> ast.Module:
        return _parse(self.path)


@cache
def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@cache
def sources() -> tuple[Source, ...]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
        found.append(Source(path, ".".join(parts), is_package))
    return tuple(found)


def resolve_from(source: Source, node: ast.ImportFrom) -> str:
    """`from X import …` 中 X 的绝对模块名（处理相对导入）。"""
    if node.level == 0:
        return node.module or ""
    base = source.module.split(".") if source.is_package else source.module.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def dotted(node: ast.expr) -> str | None:
    """`a.b.c` 形式的表达式还原成字符串；不是这种形式时为 None。"""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    names.append(node.id)
    return ".".join(reversed(names))


# ---------------------------------------------------------------- 插件清单

@dataclass(frozen=True)
class PluginInfo:
    cls: type
    name: str
    owner: str  # 所属模块：config、identity……；assembly 下的插件为 assembly
    defined_in: str  # 定义它的 Python 模块
    provides: tuple[type, ...]
    requires: tuple[type, ...]


def plugin_module_names() -> list[str]:
    names = [f"cost_platform.{d.name}.plugin" for d in sorted(PACKAGE.iterdir())
             if d.is_dir() and (d / "plugin.py").exists()]
    names += [s.module for s in sources() if s.owner == ASSEMBLY]
    return list(dict.fromkeys(names))


@cache
def collect_plugins() -> tuple[tuple[PluginInfo, ...], tuple[str, ...]]:
    """返回（插件，导入失败的模块说明）。"""
    plugins: list[PluginInfo] = []
    errors: list[str] = []
    for module_name in plugin_module_names():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # 插件还在编写时可能导入不了：列为失败项，不中断其余模块
            errors.append(f"{module_name} 导入失败：{type(exc).__name__}: {exc}")
            continue
        for obj in vars(module).values():
            if (isinstance(obj, type) and obj.__module__ == module.__name__
                    and all(hasattr(obj, a) for a in ("name", "provides", "requires", "setup"))):
                plugins.append(PluginInfo(cls=obj, name=obj.name, owner=module_name.split(".")[1],
                                          defined_in=module_name, provides=tuple(obj.provides),
                                          requires=tuple(obj.requires)))
    return tuple(plugins), tuple(errors)


def plugins() -> tuple[PluginInfo, ...]:
    return collect_plugins()[0]


def import_errors() -> tuple[str, ...]:
    return collect_plugins()[1]


# ---------------------------------------------------------------- 端口

@cache
def all_ports() -> tuple[type, ...]:
    """contracts/ports.py 中定义的全部端口，按定义顺序。"""
    return tuple(obj for obj in vars(ports_module).values()
                 if isinstance(obj, type) and obj.__module__ == ports_module.__name__)


def port_by_name(name: str) -> type:
    return next(p for p in all_ports() if p.__name__ == name)


def is_multi(port: type) -> bool:
    return port in MULTI_PORTS


def known_keys() -> set[type]:
    """插件的 provides、requires 中允许出现的键：ports.py 的端口和 HTTP 路由 APIRouter。"""
    return set(all_ports()) | {APIRouter}


def port_methods(port: type) -> list[str]:
    return [n for n, v in vars(port).items() if inspect.isfunction(v) and not n.startswith("_")]


def providers(port: type) -> list[PluginInfo]:
    return [p for p in plugins() if port in p.provides]


def provider_owners(port: type) -> set[str]:
    source = port_by_name(RETURNED_BY[port.__name__]) if port.__name__ in RETURNED_BY else port
    return {p.owner for p in providers(source)}


def users(port: type) -> list[PluginInfo]:
    """使用方：requires 中有这个端口、所属模块不同于提供方的插件（assembly 的插件也算）。"""
    owners = provider_owners(port)
    return [p for p in plugins() if port in p.requires and p.owner not in owners]


# ---------------------------------------------------------------- 方法调用索引（近似：只按方法名）

@cache
def call_index() -> dict[str, dict[str, list[str]]]:
    """方法名 → 调用它的模块 → 位置（文件:行）。只认 `x.方法名(…)` 形式的调用；contracts 和根包不算调用方。"""
    index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for source in sources():
        if source.owner in ("", CONTRACTS):
            continue
        for node in ast.walk(source.tree()):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                index[node.func.attr][source.owner].append(f"{source.rel}:{node.lineno}")
    return index


def callers(method: str, exclude: set[str]) -> dict[str, list[str]]:
    return {m: locs for m, locs in sorted(call_index().get(method, {}).items()) if m not in exclude}
