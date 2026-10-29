"""一个实体在写入时的字段规则：哪些字段不可写（WP-04、WP-14），新增行的默认值（WP-16）。

不可写的字段（C02 第 1 节、C06 第 2 节）：主键、明细的主从关联字段、`erpRow.column`、计算字段、只在 readView 中的字段
（`column` 为 null），以及只读的 ERP 列：没有 `erpRow` 的实体在所有行上只读，有 `erpRow` 的只在 ERP 行上只读。
这些规则不看权限；用户发起的命令另外只能写 authz 给出的可写字段，来源为审批时不看个人权限（C08 第 7 节）。
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal

from cost_platform.contracts.types import (
    BuiltinDefault,
    EntityConfig,
    EntityField,
    ExecutionContext,
    OptionsDefault,
    StaticDefault,
    Value,
)
from cost_platform.contracts.values import same_value

from .values import config_value


@dataclass(frozen=True)
class EntityRules:
    code: str
    config: EntityConfig
    parent_key: str | None = None
    """明细实体关联主表的字段（主表实体的 `details[].parentKey`）；主表实体为 None。"""

    @property
    def fields(self) -> dict[str, EntityField]:
        return {f.name: f for f in self.config.fields}

    @property
    def primary_key(self) -> EntityField:
        return self.fields[self.config.primary_key]

    @property
    def erp_field(self) -> EntityField | None:
        """`erpRow.column` 对应的字段（按字段名，没有时按列名找）。"""
        erp = self.config.erp_row
        if erp is None:
            return None
        fields = self.fields
        return fields.get(erp.column) or next((f for f in self.config.fields if f.column == erp.column), None)

    def is_erp_row(self, values: dict[str, Value]) -> bool:
        """按加锁读到的当前值判断是否为 ERP 行（WP-14）。"""
        field, erp = self.erp_field, self.config.erp_row
        if field is None or erp is None:
            return False
        return same_value(field.type, values.get(field.name), config_value(field, erp.value))

    def not_writable_reason(self, name: str, current: dict[str, Value] | None) -> str | None:
        """字段在这一行上不可写的原因；`current` 为这一行的当前值，新增行为 None。"""
        field = self.fields.get(name)
        if field is None:
            return f"{name} 不是 {self.code} 的字段"
        if name == self.config.primary_key:
            return f"{field.label} 是主键，不能修改"
        if name == self.parent_key:
            return f"{field.label} 是主从关联字段，不能修改"
        erp_field = self.erp_field
        if erp_field is not None and name == erp_field.name:
            return f"{field.label} 是 ERP 行标识，由平台维护"
        if field.role == "calculated":
            return f"{field.label} 是计算字段，由后端计算"
        if field.column is None:
            return f"{field.label} 只在视图中，不能修改"
        if field.source == "erp":
            if self.config.erp_row is None:
                return f"{field.label} 是 ERP 列，不能修改"
            if current is not None and self.is_erp_row(current):
                return f"{field.label} 是 ERP 行的 ERP 列，不能修改"
        return None

    def structural_writable(self, current: dict[str, Value] | None) -> frozenset[str]:
        """不看权限时这一行可写的字段：来源为审批的写入只拒绝上面这些字段（C08 第 7 节）。"""
        return frozenset(f.name for f in self.config.fields if self.not_writable_reason(f.name, current) is None)

    # ---------------------------------------------------------------- 默认值（WP-16）

    def builtin_names(self) -> set[str]:
        return {f.name for f in self.config.fields if isinstance(f.default, BuiltinDefault)}

    def defaults(self, provided: Collection[str], writable: Collection[str], ctx: ExecutionContext | None) -> dict[str, Value]:
        """新增行要补上的值：Patch 中没有的、写到表的字段按配置的默认值；没有配置时数值为 0，其他为空（不写）。
        字段不可编辑时，`builtin` 默认值一律按执行上下文取，不用前端传来的值。主键、关联字段、erpRow 列另行处理。"""
        values: dict[str, Value] = {}
        skip = {self.config.primary_key, self.parent_key}
        erp_field = self.erp_field
        if erp_field is not None:
            skip.add(erp_field.name)
        for field in self.config.fields:
            if field.column is None or field.name in skip:
                continue
            builtin = isinstance(field.default, BuiltinDefault)
            if field.name in provided and not (builtin and field.name not in writable):
                continue
            value = default_value(field, ctx)
            if value is not None:
                values[field.name] = value
        return values

    def local_erp_value(self) -> tuple[str, Value] | None:
        """新增行的 erpRow 列由写入管道设为 localValue（WP-14）。"""
        field, erp = self.erp_field, self.config.erp_row
        if field is None or erp is None:
            return None
        return field.name, config_value(field, erp.local_value)


def default_value(field: EntityField, ctx: ExecutionContext | None) -> Value:
    """一个字段的默认值（C06 第 2 节，取值与旧系统前端 `resolveColumnDefaultValue` 相同）。"""
    default = field.default
    if isinstance(default, StaticDefault):
        return config_value(field, default.value)
    if isinstance(default, OptionsDefault):
        return config_value(field, default.value[0]) if default.value else None
    if isinstance(default, BuiltinDefault):
        return _builtin(field, default.value, ctx)
    return Decimal(0) if field.type == "number" else None


def _builtin(field: EntityField, code: str, ctx: ExecutionContext | None) -> Value:
    if ctx is None:
        return None
    who = ctx.identity
    if code == "currentTime":
        now = ctx.now.replace(microsecond=0)
        if field.type == "date":
            return now.date()
        if field.type == "datetime":
            return now
        return now.strftime("%Y-%m-%d %H:%M:%S")
    raw = {
        "currentUserId": who.user_id,
        "currentUserName": who.display_name,
        "currentDeptId": who.department_id,
        "currentRoleCode": who.role_code,
        # 执行上下文只有部门编号，没有部门名称（C04），见 .reports/modules/write-pipeline/contract-gaps.md
        "currentDeptName": None,
    }.get(code)
    if raw is None:
        return None
    return config_value(field, raw) if field.type in ("number", "boolean") else raw
