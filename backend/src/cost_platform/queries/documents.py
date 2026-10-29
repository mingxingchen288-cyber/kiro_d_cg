"""`DocumentReader`（C08 第 9 节）：不加锁地读出整张单据（主表行和各明细的全部行），供 approval 的审批详情使用。

主表和明细有 readView 时经视图读取（QE-03）；明细按主表实体 `details` 的顺序，每个明细一条查询（按主单主键 IN，
每批最多 1000 个），行按主键排序；没有行的明细为空列表。不加行权限：调用方（审批详情）按自己的规则决定能否查看。
数值为 Decimal（C08 第 2 节）。
"""

from __future__ import annotations

from sqlalchemy import text

from cost_platform.contracts.ports import UnitOfWorkFactory
from cost_platform.contracts.types import DocumentData, DocumentRef, Row

from .catalog import EntityDirectory
from .sql import Binds, Source, batches, key_text, row_values


class OracleDocumentReader:
    def __init__(self, uow_factory: UnitOfWorkFactory, entities: EntityDirectory) -> None:
        self._uow = uow_factory
        self._entities = entities

    def load(self, ref: DocumentRef) -> DocumentData | None:
        return self.load_many([ref]).get(ref)

    def load_many(self, refs: list[DocumentRef]) -> dict[DocumentRef, DocumentData]:
        by_entity: dict[str, list[DocumentRef]] = {}
        for ref in dict.fromkeys(refs):
            by_entity.setdefault(ref.entity, []).append(ref)
        found: dict[DocumentRef, DocumentData] = {}
        with self._uow.begin() as uow:
            for entity_code, wanted in by_entity.items():
                entity = self._entities.entity(entity_code)
                master = Source.of(entity_code, entity)
                pk = master.columns[entity.primary_key]
                keys = [master.key(ref.record_key) for ref in wanted]
                masters: dict[str, Row] = {}
                for chunk in batches(keys):
                    binds = Binds()
                    sql = f"SELECT {master.select_list('m')} FROM {master.name} m WHERE m.{pk} IN ({', '.join(binds.add(k) for k in chunk)})"
                    for record in uow.connection.execute(text(sql), binds.values):
                        values = row_values(master.ordered(), record)
                        key = key_text(values[entity.primary_key])
                        masters[key] = Row(entity=entity_code, row_key=key, client_row_id=None, values=values)
                details: dict[str, dict[str, list[Row]]] = {key: {} for key in masters}
                present = [master.key(k) for k in masters]
                for link in entity.details:
                    detail = Source.of(link.entity, self._entities.entity(link.entity))
                    parent = detail.columns[link.parent_key]
                    for key in masters:
                        details[key][link.entity] = []
                    for chunk in batches(present):
                        binds = Binds()
                        sql = (f"SELECT {detail.select_list('d')} FROM {detail.name} d "
                               f"WHERE d.{parent} IN ({', '.join(binds.add(k) for k in chunk)}) "
                               f"ORDER BY d.{parent}, d.{detail.columns[detail.entity.primary_key]}")
                        for record in uow.connection.execute(text(sql), binds.values):
                            values = row_values(detail.ordered(), record)
                            row = Row(entity=link.entity, row_key=key_text(values[detail.entity.primary_key]), client_row_id=None,
                                      values=values)
                            details[key_text(values[link.parent_key])][link.entity].append(row)
                for ref in wanted:
                    row = masters.get(key_text(master.key(ref.record_key)))
                    if row is not None:
                        found[ref] = DocumentData(ref=ref, master=row, details=details[row.row_key or ""])
        return found
