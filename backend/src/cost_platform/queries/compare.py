"""对比显示（QE-10，C06 第 2 节 `fields[].compare`），对应旧系统 `DynamicDataService.mergeHistoryData`。

- `field` 模式：对比值取同一行的另一个字段。
- `query` 模式：按数据源分组，每个数据源追加一条查询，关联键用 IN 和绑定变量，每批最多 1000 个键；同一数据源的
  关联键取第一个配置的 `keys`（与旧系统相同）。关联键有空值的行没有对比值。同一键查出多行时取最后一行（与旧系统的
  HashMap 覆盖相同）。
- 差值 = 当前值 − 对比值；百分比 = 差值 ÷ 对比值 × 100，四舍五入到 2 位小数；对比值为 0 或为空时不给百分比。
  全部用十进制计算。结果只用于显示，不导出，不参与保存。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import CompareResult, FieldCompare, QueryCompare, Value

from .sql import Binds, Source, batches, key_text, number

_HUNDRED = Decimal(100)
_CENT = Decimal("0.01")


def compare_result(current: Value, compare: object) -> CompareResult:
    base = number(compare)
    now = current if isinstance(current, Decimal) else number(current)
    diff = None if base is None or now is None else now - base
    percent = None
    if diff is not None and base is not None and base != 0:
        percent = (diff / base * _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)
    return CompareResult(value=None if base is None else format_decimal(base),
                         diff=None if diff is None else format_decimal(diff),
                         percent=None if percent is None else format_decimal(percent))


def _source_sql(source: str) -> str:
    """`compare.source` 可以是表、视图名或查询语句（C06 第 10 节）。"""
    head = source.lstrip()[:6].upper()
    return f"({source})" if head.startswith("SELECT") or head.startswith("WITH") else source


def compare_rows(uow: UnitOfWork, source: Source, rows: Sequence[Mapping[str, Value]]) -> list[dict[str, CompareResult] | None]:
    """每行的对比结果；实体没有配置对比的字段时每行为 None（`compare` 省略）。"""
    configs = [(f.name, f.compare) for f in source.ordered() if f.compare is not None]
    if not configs:
        return [None] * len(rows)
    results: list[dict[str, CompareResult]] = [{} for _ in rows]
    by_source: dict[str, list[tuple[str, QueryCompare]]] = {}
    for name, cfg in configs:
        if isinstance(cfg, FieldCompare):
            for result, row in zip(results, rows, strict=True):
                result[name] = compare_result(row.get(name), row.get(cfg.field))
        else:
            assert isinstance(cfg, QueryCompare)
            by_source.setdefault(cfg.source, []).append((name, cfg))
    for data_source, items in by_source.items():
        found = _query(uow, data_source, items, rows)
        for result, row in zip(results, rows, strict=True):
            key = _row_key(row, items[0][1])
            values = found.get(key) if key is not None else None
            for position, (name, _) in enumerate(items):
                result[name] = compare_result(row.get(name), None if values is None else values[position])
    order = [name for name, _ in configs]
    return [{name: r[name] for name in order} for r in results]


def _row_key(row: Mapping[str, Value], cfg: QueryCompare) -> tuple[str, ...] | None:
    values = [row.get(k.current) for k in cfg.keys]
    if any(v is None for v in values):
        return None
    return tuple(key_text(v) for v in values)


def _query(uow: UnitOfWork, data_source: str, items: list[tuple[str, QueryCompare]],
           rows: Sequence[Mapping[str, Value]]) -> dict[tuple[str, ...], list[object]]:
    keys = items[0][1].keys
    wanted: dict[tuple[str, ...], list[Value]] = {}
    for row in rows:
        key = _row_key(row, items[0][1])
        if key is not None:
            wanted.setdefault(key, [row.get(k.current) for k in keys])
    found: dict[tuple[str, ...], list[object]] = {}
    select = ", ".join([*(f"q.{k.compare}" for k in keys), *(f"q.{cfg.field}" for _, cfg in items)])
    for chunk in batches(list(wanted.values())):
        binds = Binds()
        if len(keys) == 1:
            where = f"q.{keys[0].compare} IN ({', '.join(binds.add(values[0]) for values in chunk)})"
        else:
            where = " OR ".join("(" + " AND ".join(f"q.{k.compare} = {binds.add(v)}" for k, v in zip(keys, values, strict=True)) + ")"
                                for values in chunk)
        sql = f"SELECT {select} FROM {_source_sql(data_source)} q WHERE {where}"
        for record in uow.connection.execute(text(sql), binds.values):
            found[tuple(key_text(v) for v in record[:len(keys)])] = list(record[len(keys):])
    return found
