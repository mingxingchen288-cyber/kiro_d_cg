"""个人列配置（QE-07），表 PF_PERSONAL_CONFIG（迁移脚本 `migrations/qe_0001_pf_personal_config.py`）。

按（用户、页面、表格）一行保存列宽、顺序、固定、显隐：`grid_key` 为 `master` 或明细实体，`columns_json` 为
C09 `PersonalGrid` 的 JSON，列按数组顺序。明细显示方式是页面级的，存在 `grid_key` 为 `#page` 的一行的 `detail_mode` 中。
保存时只替换请求中给出的部分：请求中的每个表格整份替换这个表格的列配置，给出 `detailMode` 时替换明细显示方式，
其余不变。对应旧系统 `UserGridConfigService`（T_COST_USER_GRID_CONFIG，按用户、页面、表格整份替换）。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Text, bindparam, text

from cost_platform.contracts.ports import UnitOfWork, UnitOfWorkFactory
from cost_platform.contracts.types import ExecutionContext, PersonalConfig, PersonalGrid, dump_wire, parse_wire

PAGE_ROW = "#page"
"""页面级设置（明细显示方式）所在行的表格键。"""

_SELECT = text("SELECT grid_key, columns_json, detail_mode FROM pf_personal_config "
               "WHERE user_id = :qe_user AND page_code = :qe_page ORDER BY grid_key")
_UPDATE = text("UPDATE pf_personal_config SET columns_json = :qe_columns, detail_mode = :qe_mode, updated_at = :qe_time "
               "WHERE user_id = :qe_user AND page_code = :qe_page AND grid_key = :qe_grid").bindparams(
    bindparam("qe_columns", type_=Text))
_INSERT = text("INSERT INTO pf_personal_config (user_id, page_code, grid_key, columns_json, detail_mode, updated_at) "
               "VALUES (:qe_user, :qe_page, :qe_grid, :qe_columns, :qe_mode, :qe_time)").bindparams(
    bindparam("qe_columns", type_=Text))


def _read(raw: object) -> str:
    read = getattr(raw, "read", None)
    return str(read()) if callable(read) else str(raw)


class PersonalConfigStore:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow = uow_factory

    def get(self, user_id: str, page_code: str) -> PersonalConfig:
        """没有保存过时各项为空（C09 第 4 节）。"""
        with self._uow.begin() as uow:
            return self._load(uow, user_id, page_code)

    def save(self, user_id: str, page_code: str, patch: PersonalConfig, now: datetime) -> PersonalConfig:
        """只替换 patch 中给出的部分，返回保存后的完整个人配置。"""
        with self._uow.begin() as uow:
            for grid_key, grid in (patch.grids or {}).items():
                self._put(uow, user_id, page_code, grid_key, json.dumps(dump_wire(PersonalGrid, grid), ensure_ascii=False), None, now)
            if patch.detail_mode is not None:
                self._put(uow, user_id, page_code, PAGE_ROW, None, patch.detail_mode, now)
            saved = self._load(uow, user_id, page_code)
            uow.commit()
        return saved

    @staticmethod
    def _put(uow: UnitOfWork, user_id: str, page_code: str, grid_key: str, columns: str | None, mode: str | None,
             now: datetime) -> None:
        params = {"qe_user": user_id, "qe_page": page_code, "qe_grid": grid_key, "qe_columns": columns, "qe_mode": mode,
                  "qe_time": now}
        if uow.connection.execute(_UPDATE, params).rowcount == 0:
            uow.connection.execute(_INSERT, params)

    @staticmethod
    def _load(uow: UnitOfWork, user_id: str, page_code: str) -> PersonalConfig:
        grids: dict[str, PersonalGrid] = {}
        mode = None
        for grid_key, columns, detail_mode in uow.connection.execute(_SELECT, {"qe_user": user_id, "qe_page": page_code}):
            if grid_key == PAGE_ROW:
                mode = detail_mode
            elif columns is not None:
                grids[grid_key] = parse_wire(PersonalGrid, json.loads(_read(columns)))
        return PersonalConfig(grids=grids or None, detail_mode=mode)


class PersonalConfigs:
    """C09 的个人配置接口：当前用户在页面上的个人配置。页面不存在为 404、角色不能访问为 403，与其他查询接口相同。"""

    def __init__(self, store: PersonalConfigStore) -> None:
        self._store = store

    def get(self, ctx: ExecutionContext, page_code: str) -> PersonalConfig:
        ctx.config.page_view(page_code)
        return self._store.get(ctx.identity.user_id, page_code)

    def save(self, ctx: ExecutionContext, page_code: str, patch: PersonalConfig) -> PersonalConfig:
        ctx.config.page_view(page_code)
        return self._store.save(ctx.identity.user_id, page_code, patch, ctx.now)
