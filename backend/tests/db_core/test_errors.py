"""DB-02：Oracle 错误映射为平台错误码，响应中不出现 ORA- 文本（真实验证，d_cg）。

场景：两个人同时保存成本单 2550。第一个人的事务锁住了 2550 主表这一行，第二个人加锁读取时等不到锁
（写入管道用 `SELECT … FOR UPDATE WAIT n`，WP-03），得到 DOCUMENT_BUSY。测试只加锁、不写，结束时回滚。
死锁（ORA-00060）、连接断开的注入：上线后再补（任务卡 T-DB-1）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

from cost_platform.contracts.types import ErrorCode, PlatformError
from cost_platform.db_core.engine import OracleUnitOfWorkFactory

from .support import engine  # noqa: F401 - fixture

pytestmark = pytest.mark.oracle

LOCK = "SELECT DOCID FROM T_COST_PINGGU WHERE DOCID = 2550 FOR UPDATE WAIT 1"


def no_oracle_text(error: PlatformError) -> bool:
    return "ORA-" not in error.to_response().model_dump_json() and "ORA-" not in str(error)


def test_lock_wait_timeout_is_document_busy(engine: Engine) -> None:  # noqa: F811
    factory = OracleUnitOfWorkFactory(engine)
    with factory.begin() as first:
        assert first.connection.execute(text(LOCK)).scalar_one() == 2550
        with pytest.raises(PlatformError) as caught, factory.begin() as second:
            second.connection.execute(text(LOCK))
    assert caught.value.code is ErrorCode.DOCUMENT_BUSY
    assert caught.value.message == "单据正被其他人修改，请稍后再试" and no_oracle_text(caught.value)
    with factory.begin() as again:  # 第一个事务结束后锁已释放
        assert again.connection.execute(text(LOCK)).scalar_one() == 2550


def test_other_errors_are_internal_error(engine: Engine) -> None:  # noqa: F811
    """例如读一个不存在的列（ORA-00904）：INTERNAL_ERROR，提示中没有 ORA- 文本和 SQL。"""
    with pytest.raises(PlatformError) as caught, OracleUnitOfWorkFactory(engine).begin() as uow:
        uow.connection.execute(text("SELECT NO_SUCH_COLUMN FROM T_COST_PINGGU WHERE DOCID = 2550"))
    assert caught.value.code is ErrorCode.INTERNAL_ERROR
    assert no_oracle_text(caught.value) and "NO_SUCH_COLUMN" not in caught.value.message
