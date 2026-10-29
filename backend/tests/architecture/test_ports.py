"""4. 端口设计不走样：用 contracts/ports.py 的全部端口，对照各插件和 assembly 的 provides、requires（只读类属性，不运行 setup）。

- 单实现端口必须正好有一个提供方；
- 每个端口在提供方模块以外至少有一个使用方：requires 中有它、所属模块不同于提供方的插件（assembly 的插件也算）；
- provides、requires 里只能是 ports.py 的端口或 APIRouter（规格第 1 节的写法），否则上面两条统计不到。

例外见 support.py 的 `NOT_REGISTERED`、`NO_USER_REQUIRED`。插件清单的取法见 support.py。
"""

from __future__ import annotations

import pytest

from .support import (
    NO_USER_REQUIRED,
    NOT_REGISTERED,
    all_ports,
    import_errors,
    is_multi,
    known_keys,
    plugins,
    provider_owners,
    providers,
    users,
)

SINGLE_PORTS = [p for p in all_ports() if not is_multi(p) and p.__name__ not in NOT_REGISTERED]
USED_PORTS = [p for p in all_ports() if p.__name__ not in NO_USER_REQUIRED]


def _ids(ports: list[type]) -> list[str]:
    return [p.__name__ for p in ports]


def test_plugin_modules_import() -> None:
    assert import_errors() == ()
    assert plugins(), "没有找到插件"


def test_plugin_declarations_use_ports() -> None:
    keys = known_keys()
    wrong = [f"{p.name}（{p.defined_in}）的 {field} 有 {key!r}"
             for p in plugins() for field in ("provides", "requires") for key in getattr(p, field) if key not in keys]
    assert wrong == []


@pytest.mark.parametrize("port", SINGLE_PORTS, ids=_ids(SINGLE_PORTS))
def test_single_port_has_exactly_one_provider(port: type) -> None:
    found = [f"{p.name}（{p.owner}）" for p in providers(port)]
    assert len(found) == 1, f"单实现端口 {port.__name__} 的提供方：{'、'.join(found) or '没有'}"


@pytest.mark.parametrize("port", USED_PORTS, ids=_ids(USED_PORTS))
def test_port_is_used_outside_its_provider(port: type) -> None:
    owners = sorted(provider_owners(port))
    assert users(port), (f"端口 {port.__name__} 在提供方模块（{'、'.join(owners) or '没有提供方'}）以外"
                         f"没有使用方：没有别的模块的插件把它写进 requires")
