"""插件注册表（架构 6.1，用户 2026-10-29 定）：模块只提供能力，每个模块的 plugin.py 自己创建内部对象、注册它实现的端口；
assembly 只维护插件清单并调用 `boot`。

- 键直接用 C08 的端口类（ports.py 中的 Protocol），不用字符串名。
- 单实现端口：`provide(port, impl)`、`get(port)`，一个端口只能有一个提供方。
- 多实现端口：`add(port, impl)`、`all(port)`，只用于 `PipelineStage` 和 HTTP 路由 `APIRouter`（`MULTI_PORTS`）。
- 插件约定（`Plugin`）：`name`、`provides`、`requires`、`setup(reg)`；可选 `async start()`、`async stop()`，后台任务放在这里。
- `boot(plugins)`：按 `requires` 排序后依次调用 `setup`；依赖多实现端口的插件排在所有提供这个端口的插件之后。清单的先后不影响
  结果（依赖相同的插件按名称排列）。每个插件在 setup 中拿到自己的视图（`PluginView`）：只能 get/all 自己 `requires` 里的端口，
  只能 provide/add 自己 `provides` 里的端口。boot 结束后冻结，之后再调用 provide、get、add、all 都报错。
- 启动时检查：缺提供方、单实现端口有两个提供方、依赖成环、取用或注册了没声明的端口、声明提供却没有注册；有一项不通过就抛
  `RegistryError`，写明插件和端口。boot 结束时在日志中打印"端口 → 插件 → 实现类"。

除这些检查外不另加防御代码。注册表和视图只出现在本文件、各模块的 plugin.py 和 assembly（backend/tests/architecture/ 检查）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Protocol, TypeVar

from fastapi import APIRouter

from .ports import PipelineStage

_log = logging.getLogger("cost_platform.registry")

T = TypeVar("T")

MULTI_PORTS: frozenset[type] = frozenset({PipelineStage, APIRouter})
"""多实现端口：同一端口可以由几个插件各注册几个实现。"""


class RegistryError(Exception):
    """注册表检查不通过：拒绝启动。"""


class Plugin(Protocol):
    name: str
    provides: tuple[type, ...]
    requires: tuple[type, ...]

    def setup(self, reg: PluginView) -> None:
        """创建本模块的对象：从 `reg.get`、`reg.all` 取用端口，用 `reg.provide`、`reg.add` 注册端口的实现。"""
        ...


def _port_name(port: type) -> str:
    return port.__name__


def _impl_name(impl: object) -> str:
    cls = impl if isinstance(impl, type) else type(impl)
    return f"{cls.__module__}.{cls.__qualname__}"


class PluginView:
    """一个插件在 setup 中拿到的注册表视图。"""

    __slots__ = ("_plugin", "_registry")

    def __init__(self, registry: Registry, plugin: Plugin) -> None:
        self._registry = registry
        self._plugin = plugin

    def provide(self, port: type[T], impl: T) -> None:
        self._registry._provide(self._plugin, port, impl)

    def get(self, port: type[T]) -> T:
        return self._registry._get(self._plugin, port)

    def add(self, port: type[T], impl: T) -> None:
        self._registry._add(self._plugin, port, impl)

    def all(self, port: type[T]) -> list[T]:
        return self._registry._all(self._plugin, port)


class Registry:
    def __init__(self) -> None:
        self._single: dict[type, tuple[str, Any]] = {}
        self._multi: dict[type, list[tuple[str, Any]]] = {}
        self._active: PluginView | None = None
        self._frozen = False

    # ---------------------------------------------------------------- 公开方法：只在插件的 setup 中有效

    def provide(self, port: type[T], impl: T) -> None:
        self._view().provide(port, impl)

    def get(self, port: type[T]) -> T:
        return self._view().get(port)

    def add(self, port: type[T], impl: T) -> None:
        self._view().add(port, impl)

    def all(self, port: type[T]) -> list[T]:
        return self._view().all(port)

    def boot(self, plugins: Sequence[Plugin]) -> list[Plugin]:
        """检查声明、排序、依次 setup、冻结；返回 setup 的先后（assembly 按它调用 start，按相反顺序调用 stop）。"""
        if self._frozen:
            raise RegistryError("注册表已经 boot 过，不能再 boot")
        ordered = _order(plugins)
        for plugin in ordered:
            view = PluginView(self, plugin)
            self._active = view
            try:
                plugin.setup(view)
            finally:
                self._active = None
            for port in plugin.provides:
                registered = (self._single.get(port, ("", None))[0] == plugin.name if port not in MULTI_PORTS
                              else any(owner == plugin.name for owner, _ in self._multi.get(port, [])))
                if not registered:
                    raise RegistryError(f"插件 {plugin.name} 声明提供 {_port_name(port)}，setup 中却没有注册")
        self._frozen = True
        for line in self._wiring():
            _log.info(line)
        return ordered

    # ---------------------------------------------------------------- 视图调用的实现

    def _view(self) -> PluginView:
        if self._frozen:
            raise RegistryError("注册表已冻结：boot 结束后不能再取用或注册端口")
        if self._active is None:
            raise RegistryError("注册表只能在插件的 setup 中使用")
        return self._active

    def _check(self, plugin: Plugin, port: type, *, declared: tuple[type, ...], what: str, multi: bool) -> None:
        if self._frozen:
            raise RegistryError(f"注册表已冻结：插件 {plugin.name} 在 boot 结束后{what}端口 {_port_name(port)}")
        if port not in declared:
            raise RegistryError(f"插件 {plugin.name} {what}了没有声明的端口 {_port_name(port)}")
        if (port in MULTI_PORTS) != multi:
            right = "add/all" if port in MULTI_PORTS else "provide/get"
            raise RegistryError(f"插件 {plugin.name} 对端口 {_port_name(port)} 要用 {right}")

    def _provide(self, plugin: Plugin, port: type, impl: Any) -> None:
        self._check(plugin, port, declared=plugin.provides, what="注册", multi=False)
        if port in self._single:
            raise RegistryError(f"单实现端口 {_port_name(port)} 有两个提供方：{self._single[port][0]}、{plugin.name}")
        self._single[port] = (plugin.name, impl)

    def _add(self, plugin: Plugin, port: type, impl: Any) -> None:
        self._check(plugin, port, declared=plugin.provides, what="注册", multi=True)
        self._multi.setdefault(port, []).append((plugin.name, impl))

    def _get(self, plugin: Plugin, port: type) -> Any:
        self._check(plugin, port, declared=plugin.requires, what="取用", multi=False)
        return self._single[port][1]

    def _all(self, plugin: Plugin, port: type) -> list[Any]:
        self._check(plugin, port, declared=plugin.requires, what="取用", multi=True)
        return [impl for _, impl in self._multi.get(port, [])]

    def _wiring(self) -> list[str]:
        lines = [f"{_port_name(p)} → {owner} → {_impl_name(impl)}" for p, (owner, impl) in self._single.items()]
        for port, entries in self._multi.items():
            for owner, impl in entries:
                label = getattr(impl, "name", None) if port is PipelineStage else None
                suffix = f"（{label}）" if label else ""
                lines.append(f"{_port_name(port)} → {owner} → {_impl_name(impl)}{suffix}")
        return sorted(lines)


def _order(plugins: Sequence[Plugin]) -> list[Plugin]:
    """按 requires 排序：单实现端口排在提供方之后，多实现端口排在全部提供方之后；依赖相同的按名称排列。"""
    names = [p.name for p in plugins]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise RegistryError(f"插件名称重复：{'、'.join(duplicated)}")
    providers: dict[type, list[str]] = {}
    for plugin in plugins:
        for port in plugin.provides:
            providers.setdefault(port, []).append(plugin.name)
    for port, owners in providers.items():
        if port not in MULTI_PORTS and len(owners) > 1:
            raise RegistryError(f"单实现端口 {_port_name(port)} 有两个提供方：{'、'.join(owners)}")
    after: dict[str, set[str]] = {p.name: set() for p in plugins}
    via: dict[tuple[str, str], list[str]] = {}
    for plugin in plugins:
        for port in plugin.requires:
            owners = providers.get(port)
            if not owners:
                raise RegistryError(f"插件 {plugin.name} 需要的端口 {_port_name(port)} 没有提供方")
            after[plugin.name] |= set(owners)
            for owner in owners:
                via.setdefault((plugin.name, owner), []).append(_port_name(port))
    by_name = {p.name: p for p in plugins}
    ordered: list[Plugin] = []
    done: set[str] = set()
    while len(ordered) < len(plugins):
        ready = sorted(n for n in after if n not in done and after[n] <= done)
        if not ready:
            left = sorted(n for n in after if n not in done)
            detail = "；".join(
                f"{n} 等待 " + "、".join(f"{o}（{'、'.join(via[(n, o)])}）" for o in sorted(after[n] - done))
                for n in left)
            raise RegistryError(f"插件依赖成环：{detail}")
        for name in ready:
            ordered.append(by_name[name])
            done.add(name)
    return ordered
