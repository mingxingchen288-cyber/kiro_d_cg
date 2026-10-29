"""5–7：只出报告、不让测试失败。运行时覆盖写 `.reports/modules/architecture-report.md`。

5. 端口的方法在提供方模块以外没人调用；
6. 一个端口的方法被两批完全不重叠的使用方模块分别调用：提示拆分；
7. 两个端口总是由同一个模块提供、被同一批使用方插件一起依赖：提示合并。

方法调用按方法名近似查找（support.call_index），报告里写明了误判的可能。
"""

from __future__ import annotations

from datetime import datetime

from .support import (
    NO_USER_REQUIRED,
    NOT_REGISTERED,
    REPORT,
    RETURNED_BY,
    all_ports,
    callers,
    import_errors,
    plugins,
    port_methods,
    provider_owners,
    providers,
    users,
)


def _names(items: list[str] | set[str]) -> str:
    return "、".join(sorted(items)) or "—"


def _key_names(keys: tuple[type, ...]) -> str:
    return "、".join(k.__name__ for k in keys) or "—"


def _plugin_section() -> list[str]:
    lines = ["## 插件清单", "", "| 插件 | 模块 | 定义在 | provides | requires |", "|---|---|---|---|---|"]
    for p in sorted(plugins(), key=lambda p: (p.owner, p.name)):
        lines.append(f"| {p.name} | {p.owner} | {p.defined_in} | {_key_names(p.provides)} | {_key_names(p.requires)} |")
    errors = import_errors()
    lines += ["", "导入失败的模块（其中的插件没有统计在内）：" if errors else "没有导入失败的模块。", ""]
    lines += [f"- {e}" for e in errors]
    return lines + ([""] if errors else [])


def _port_section() -> list[str]:
    lines = ["## 端口的提供方和使用方", "",
             "使用方：requires 中有这个端口、所属模块不同于提供方的插件（assembly 的插件也算）。", "",
             "| 端口 | 提供方插件 | 使用方插件 | 例外 |", "|---|---|---|---|"]
    for port in all_ports():
        found = [f"{p.name}（{p.owner}）" for p in providers(port)]
        used = [p.name for p in users(port)]
        note = NO_USER_REQUIRED.get(port.__name__, "")
        lines.append(f"| {port.__name__} | {_names(found)} | {_names(used)} | {note} |")
    return lines + [""]


def _unused_methods() -> list[str]:
    lines = ["## 5. 提供方模块以外没人调用的端口方法", "",
             "按方法名近似查找：只认 `x.方法名(…)` 形式的调用，不判断 x 是什么对象（contracts 和根包不算调用方）。",
             "- 同名误判：别的对象上的同名方法也算作调用，例如 `RelatedQuery.find`、`FreezeReader.find` 和 `str.find`，"
             "`ConfigSnapshot.entity` 和 `EntityDirectory.entity` 互相分不开，所以真正没人调用的方法可能漏报；",
             "- 只把方法当回调传出去、不加括号（`f = reader.read`）的不算调用，可能误报。", ""]
    rows = []
    for port in all_ports():
        owners = provider_owners(port)
        if not owners:
            continue
        for method in port_methods(port):
            if not callers(method, owners):
                exempt = port.__name__ in NO_USER_REQUIRED and port.__name__ not in RETURNED_BY
                note = f"（不要求有使用方：{NO_USER_REQUIRED[port.__name__]}）" if exempt else ""
                rows.append(f"- `{port.__name__}.{method}`：提供方模块 {_names(owners)}{note}")
    skipped = [p.__name__ for p in all_ports() if not provider_owners(p)]
    lines += rows or ["没有发现。"]
    lines += ["", f"没有提供方、未检查的端口：{_names(skipped)}。", ""]
    return lines


def _split_groups(port: type) -> list[tuple[list[str], set[str]]]:
    """按"共用调用方模块"把方法连成组；组数 ≥ 2 说明各组的调用方完全不重叠。"""
    owners = provider_owners(port)
    groups: list[tuple[list[str], set[str]]] = []
    for method in port_methods(port):
        modules = set(callers(method, owners))
        if not modules:
            continue
        merged = [g for g in groups if g[1] & modules]
        new: tuple[list[str], set[str]] = ([method], set(modules))
        for g in merged:
            new[0].extend(g[0])
            new[1].update(g[1])
            groups.remove(g)
        groups.append(new)
    return groups


def _split_section() -> list[str]:
    lines = ["## 6. 提示拆分：方法被两批完全不重叠的使用方模块分别调用", "",
             "调用方同第 5 条（按方法名近似，提供方模块以外）。", ""]
    found = False
    for port in all_ports():
        if not provider_owners(port):
            continue
        groups = _split_groups(port)
        if len(groups) < 2:
            continue
        found = True
        lines.append(f"- `{port.__name__}`（提供方模块 {_names(provider_owners(port))}）：")
        for methods, modules in groups:
            lines.append(f"  - {_names(methods)} ← {_names(modules)}")
    return lines + ([] if found else ["没有发现。"]) + [""]


def _merge_section() -> list[str]:
    lines = ["## 7. 提示合并：由同一个模块提供、被同一批使用方插件一起依赖的端口", "",
             "按插件声明（provides、requires）比较，提供方模块相同、使用方插件集合相同。", ""]
    groups: dict[tuple[frozenset[str], frozenset[str]], list[str]] = {}
    for port in all_ports():
        if port.__name__ in NOT_REGISTERED:
            continue
        owners, used = provider_owners(port), frozenset(p.name for p in users(port))
        if owners and used:
            groups.setdefault((frozenset(owners), used), []).append(port.__name__)
    rows = [f"- {'、'.join(f'`{n}`' for n in ports)}：提供方模块 {_names(set(owners))}；使用方 {_names(set(used))}"
            for (owners, used), ports in groups.items() if len(ports) > 1]
    return lines + (rows or ["没有发现。"]) + [""]


def _call_detail() -> list[str]:
    lines = ["## 附：端口方法在提供方模块以外的调用（按方法名近似）", ""]
    for port in all_ports():
        owners = provider_owners(port)
        if not owners:
            continue
        for method in port_methods(port):
            found = callers(method, owners)
            detail = "、".join(f"{m}（{len(locs)}）" for m, locs in found.items()) or "—"
            lines.append(f"- `{port.__name__}.{method}`：{detail}")
    return lines + [""]


def build_report() -> str:
    lines = ["# 后端架构检查报告", "",
             f"由 `backend/tests/architecture/test_report.py` 在运行 pytest 时生成（覆盖写），只出报告、不让测试失败。"
             f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}。失败类检查（第 1–4 条）的结果看 pytest 输出。", ""]
    for section in (_plugin_section, _port_section, _unused_methods, _split_section, _merge_section, _call_detail):
        lines += section()
    return "\n".join(lines)


def test_write_architecture_report() -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(), encoding="utf-8")
    assert REPORT.exists()
