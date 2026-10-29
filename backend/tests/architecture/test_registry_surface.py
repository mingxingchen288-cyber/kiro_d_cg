"""注册表保持最小，只在接线处出现（用户 2026-10-29："注册表保持最小，靠自动检查防止它变大"）。

1. `Registry` 的公开方法只能是 provide、get、add、all、boot。要加方法，就得同时改这里的 `ALLOWED`。
2. `Registry`、`PluginView` 只能出现在 contracts/registry.py、各模块的 plugin.py 和 assembly。其余源码中，从
   cost_platform.contracts（.registry）导入它们，或在注解、调用、属性等任何地方用到导入的名字，都算违规。
   按导入解析，不按名字匹配：migration/pages.py 有自己的 `Registry` 类，与注册表无关。
   局限：只能查到经过导入的使用；没有注解、也没有导入的形参（例如 `def __init__(self, reg)`）查不出来。
"""

from __future__ import annotations

import ast

from cost_platform.contracts.registry import Registry

from .support import ASSEMBLY, Source, dotted, resolve_from, sources

ALLOWED = {"provide", "get", "add", "all", "boot"}

REGISTRY_MODULE = "cost_platform.contracts.registry"
GUARDED = {"Registry", "PluginView"}


def test_registry_public_methods() -> None:
    public = {n for n in dir(Registry) if not n.startswith("_")}
    assert public == ALLOWED, f"Registry 的公开方法有变化：多了 {sorted(public - ALLOWED)}，少了 {sorted(ALLOWED - public)}"


def _exempt(source: Source) -> bool:
    if source.module == REGISTRY_MODULE or source.owner == ASSEMBLY:
        return True
    parts = source.module.split(".")
    return len(parts) == 3 and parts[2] == "plugin" and not source.is_package


def _annotation_nodes(tree: ast.Module) -> set[int]:
    """注解里的全部节点（含字符串注解解析出来的，按所在注解的位置记）。"""
    roots: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            roots.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
    return {id(n) for root in roots for n in ast.walk(root)}


def _string_annotations(tree: ast.Module) -> list[tuple[int, ast.expr]]:
    """字符串写的注解（"PluginView"）解析成表达式，带原来的行号。"""
    found = []
    for node in ast.walk(tree):
        annotations: list[ast.expr | None] = []
        if isinstance(node, ast.arg):
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        for ann in annotations:
            for sub in ast.walk(ann) if ann is not None else ():
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    try:
                        found.append((sub.lineno, ast.parse(sub.value, mode="eval").body))
                    except SyntaxError:
                        pass
    return found


def registry_uses(source: Source) -> list[str]:
    tree = source.tree()
    lines = source.path.read_text(encoding="utf-8").splitlines()
    aliases: dict[str, str] = {}  # 本文件中指向 Registry/PluginView 的名字
    module_paths = {REGISTRY_MODULE}  # 本文件中指向 registry 模块的写法（`import cost_platform…` 后的全路径也算）
    found: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            origin = resolve_from(source, node)
            for alias in node.names:
                local = alias.asname or alias.name
                if origin in (REGISTRY_MODULE, "cost_platform.contracts") and alias.name in GUARDED:
                    aliases[local] = alias.name
                    found.append((node.lineno, f"导入 {alias.name}"))
                elif origin == REGISTRY_MODULE and alias.name == "*":
                    found.append((node.lineno, "导入 registry 的全部名字"))
                elif origin == "cost_platform.contracts" and alias.name == "registry":
                    module_paths.add(local)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == REGISTRY_MODULE and alias.asname:
                    module_paths.add(alias.asname)
                elif alias.name == "cost_platform.contracts" and alias.asname:
                    module_paths.add(f"{alias.asname}.registry")

    guarded_paths = {f"{m}.{g}": g for m in module_paths for g in GUARDED}
    in_annotation = _annotation_nodes(tree)
    call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}

    def hits(root: ast.AST) -> list[tuple[ast.expr, str]]:
        result = []
        for node in ast.walk(root):
            if isinstance(node, ast.Name) and node.id in aliases:
                result.append((node, aliases[node.id]))
            elif isinstance(node, ast.Attribute) and (path := dotted(node)) in guarded_paths:
                result.append((node, guarded_paths[path]))
        return result

    for node, name in hits(tree):
        kind = "注解" if id(node) in in_annotation else "调用" if id(node) in call_funcs else "使用"
        found.append((node.lineno, f"{kind} {name}"))
    for lineno, expr in _string_annotations(tree):
        for _node, name in hits(expr):
            found.append((lineno, f"字符串注解 {name}"))

    return [f"{source.rel}:{n}: {what}：{lines[n - 1].strip()}" for n, what in sorted(set(found))]


def test_registry_types_only_in_wiring_code() -> None:
    checked = [s for s in sources() if not _exempt(s)]
    assert checked, "没有找到要检查的源码"
    violations = [line for s in checked for line in registry_uses(s)]
    assert violations == [], "Registry、PluginView 只能出现在 contracts/registry.py、各模块的 plugin.py 和 assembly：\n" + \
        "\n".join(violations)
