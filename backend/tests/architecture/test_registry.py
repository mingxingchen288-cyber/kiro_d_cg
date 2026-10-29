"""注册表（contracts/registry.py）的单元测试：用几个小插件检查 boot 的排序和启动检查；错误说明要写明插件名和端口名。"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Protocol

import pytest

from cost_platform.contracts.ports import PipelineStage
from cost_platform.contracts.registry import PluginView, Registry, RegistryError


class PortA(Protocol):
    pass


class PortB(Protocol):
    pass


class PortC(Protocol):
    pass


class Stage:
    def __init__(self, name: str) -> None:
        self.name = name


class Plug:
    """测试用插件：setup 默认把 provides 里的端口都注册上（单实现 provide，多实现 add）。"""

    def __init__(self, name: str, provides: tuple[type, ...] = (), requires: tuple[type, ...] = (),
                 setup: Callable[[Plug, PluginView], None] | None = None) -> None:
        self.name = name
        self.provides = provides
        self.requires = requires
        self._setup = setup
        self.view: PluginView | None = None
        self.got: dict[type, object] = {}

    def setup(self, reg: PluginView) -> None:
        self.view = reg
        if self._setup is not None:
            self._setup(self, reg)
            return
        for port in self.requires:
            self.got[port] = reg.all(port) if port is PipelineStage else reg.get(port)
        for port in self.provides:
            if port is PipelineStage:
                reg.add(port, Stage(f"{self.name}.stage"))
            else:
                reg.provide(port, f"{self.name}:{port.__name__}")


def names(plugins: list[Plug]) -> list[str]:
    return [p.name for p in plugins]


def boot_error(plugins: list[Plug]) -> str:
    with pytest.raises(RegistryError) as info:
        Registry().boot(plugins)
    return str(info.value)


# ---------------------------------------------------------------- 排序


def test_boot_order_does_not_depend_on_list_order() -> None:
    def make() -> list[Plug]:
        return [
            Plug("c", requires=(PortB,)),
            Plug("b", provides=(PortB,), requires=(PortA,)),
            Plug("a", provides=(PortA,)),
            Plug("d", requires=(PortA,)),  # 与 b 依赖相同：按名称排在 b 之后
            Plug("x"),  # 没有依赖：与 a 一起最先，按名称排在 a 之后
        ]

    orders = {tuple(names(Registry().boot(list(perm)))) for perm in itertools.permutations(make())}
    assert orders == {("a", "x", "b", "d", "c")}


def test_setup_gets_the_provider_implementation() -> None:
    consumer = Plug("consumer", requires=(PortA,))
    Registry().boot([consumer, Plug("provider", provides=(PortA,))])
    assert consumer.got == {PortA: "provider:PortA"}


def test_multi_port_consumer_runs_after_every_provider() -> None:
    # 消费方的名称排在提供方之前，提供方之间也没有依赖：只有多实现端口的规则能把它排到最后
    def make() -> list[Plug]:
        return [Plug("a-orchestration", requires=(PipelineStage,)), Plug("z-stage", provides=(PipelineStage,)),
                Plug("m-stage", provides=(PipelineStage,), requires=(PortA,)), Plug("b-port", provides=(PortA,))]

    for perm in itertools.permutations(make()):
        assert names(Registry().boot(list(perm)))[-1] == "a-orchestration"


def test_all_returns_implementations_in_registration_order() -> None:
    def add_two(_: Plug, reg: PluginView) -> None:
        reg.add(PipelineStage, Stage("后注册的名称排前"))
        reg.add(PipelineStage, Stage("a-先注册"))

    first = Plug("a", provides=(PipelineStage,), setup=add_two)
    second = Plug("b", provides=(PipelineStage,))
    consumer = Plug("c", requires=(PipelineStage,))
    Registry().boot([consumer, second, first])
    assert [s.name for s in consumer.got[PipelineStage]] == ["后注册的名称排前", "a-先注册", "b.stage"]


# ---------------------------------------------------------------- 启动检查


def test_missing_provider() -> None:
    message = boot_error([Plug("consumer", requires=(PortA,))])
    assert "consumer" in message and "PortA" in message


def test_single_port_with_two_providers() -> None:
    message = boot_error([Plug("first", provides=(PortA,)), Plug("second", provides=(PortA,))])
    assert "first" in message and "second" in message and "PortA" in message


def test_dependency_cycle() -> None:
    message = boot_error([Plug("left", provides=(PortA,), requires=(PortB,)),
                          Plug("right", provides=(PortB,), requires=(PortA,)),
                          Plug("free", provides=(PortC,))])
    for part in ("left", "right", "PortA", "PortB"):
        assert part in message, f"错误说明缺 {part}：{message}"


def test_get_undeclared_port() -> None:
    def take(_: Plug, reg: PluginView) -> None:
        reg.get(PortB)

    message = boot_error([Plug("p", provides=(PortB,)), Plug("taker", requires=(PortA,), setup=take),
                          Plug("q", provides=(PortA,))])
    assert "taker" in message and "PortB" in message


def test_all_undeclared_port() -> None:
    def take(_: Plug, reg: PluginView) -> None:
        reg.all(PipelineStage)

    message = boot_error([Plug("stages", provides=(PipelineStage,)), Plug("taker", setup=take)])
    assert "taker" in message and "PipelineStage" in message


def test_provide_undeclared_port() -> None:
    def give(_: Plug, reg: PluginView) -> None:
        reg.provide(PortA, "a")
        reg.provide(PortB, "b")

    message = boot_error([Plug("giver", provides=(PortA,), setup=give)])
    assert "giver" in message and "PortB" in message


def test_add_undeclared_port() -> None:
    def give(_: Plug, reg: PluginView) -> None:
        reg.add(PipelineStage, Stage("s"))

    message = boot_error([Plug("giver", setup=give)])
    assert "giver" in message and "PipelineStage" in message


def test_declared_but_not_registered() -> None:
    def give(_: Plug, reg: PluginView) -> None:
        reg.provide(PortA, "a")

    message = boot_error([Plug("lazy", provides=(PortA, PortB), setup=give)])
    assert "lazy" in message and "PortB" in message


def test_declared_multi_port_but_not_added() -> None:
    message = boot_error([Plug("lazy", provides=(PipelineStage,), setup=lambda _p, _r: None)])
    assert "lazy" in message and "PipelineStage" in message


# ---------------------------------------------------------------- boot 后冻结


def test_view_kept_after_boot_is_frozen() -> None:
    """插件把 setup 拿到的视图留到 start 里再用：报错，并写明插件和端口。"""
    holder = Plug("holder", requires=(PortA,), provides=(PortB,))
    Registry().boot([holder, Plug("provider", provides=(PortA,))])
    assert holder.view is not None
    for port, call in ((PortA, lambda v: v.get(PortA)), (PortB, lambda v: v.provide(PortB, "b"))):
        with pytest.raises(RegistryError) as info:
            call(holder.view)
        message = str(info.value)
        assert "冻结" in message
        assert "holder" in message and port.__name__ in message, message


def test_registry_is_frozen_after_boot() -> None:
    registry = Registry()
    registry.boot([Plug("provider", provides=(PortA,))])
    for call in (lambda: registry.get(PortA), lambda: registry.provide(PortA, "a"),
                 lambda: registry.add(PipelineStage, Stage("s")), lambda: registry.all(PipelineStage)):
        with pytest.raises(RegistryError, match="冻结"):
            call()
    with pytest.raises(RegistryError):
        registry.boot([Plug("again")])
