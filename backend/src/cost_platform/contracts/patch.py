"""增量修改（Patch）：前端编辑缓冲提交给写入管道的内容。

只表达“用户想改什么”，不代表允许修改；能否写入由权限、元数据和规则决定。
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, StrictBool, model_validator

from .common import Code, Contract, FieldValues, Identifier


class FieldPatch(Contract):
    values: FieldValues = Field(default_factory=dict, alias="set")


class ParentRef(Contract):
    """新增明细所属的上级行：已有行用 rowKey，同一次提交中新建的行用 clientRowId。"""

    entity: Code
    row_key: Identifier | None = None
    client_row_id: Identifier | None = None

    @model_validator(mode="after")
    def _exactly_one_identity(self) -> Self:
        if (self.row_key is None) == (self.client_row_id is None):
            raise ValueError("上级行必须且只能用 rowKey 或 clientRowId 之一标识")
        return self


class RowPatch(Contract):
    """明细行的一条修改意图：修改已有行、删除已有行或新增行。"""

    entity: Code
    row_key: Identifier | None = None
    client_row_id: Identifier | None = None
    values: FieldValues = Field(default_factory=dict, alias="set")
    delete: StrictBool = False
    parent: ParentRef | None = None

    @property
    def identity(self) -> tuple[str, str, str]:
        if self.row_key is not None:
            return self.entity, "existing", self.row_key
        assert self.client_row_id is not None
        return self.entity, "new", self.client_row_id

    @property
    def is_insert(self) -> bool:
        return self.row_key is None

    @model_validator(mode="after")
    def _validate_intent(self) -> Self:
        if (self.row_key is None) == (self.client_row_id is None):
            raise ValueError("明细行必须且只能用 rowKey（已有行）或 clientRowId（新增行）之一标识")
        if self.delete and (self.row_key is None or self.values):
            raise ValueError("删除只能针对已有行，且不能同时修改字段")
        return self


class Patch(Contract):
    master: FieldPatch = Field(default_factory=FieldPatch)
    details: tuple[RowPatch, ...] = ()

    @model_validator(mode="after")
    def _no_duplicate_intents(self) -> Self:
        identities = [row.identity for row in self.details]
        if len(identities) != len(set(identities)):
            raise ValueError("同一行不能在一次提交中出现多条修改意图")
        new_ids = {row.client_row_id for row in self.details if row.client_row_id is not None}
        for row in self.details:
            if row.parent is not None and row.parent.client_row_id is not None and row.parent.client_row_id not in new_ids:
                raise ValueError("新增行引用的上级临时行不在本次提交中")
        return self

    @property
    def is_empty(self) -> bool:
        return not self.master.values and not self.details
