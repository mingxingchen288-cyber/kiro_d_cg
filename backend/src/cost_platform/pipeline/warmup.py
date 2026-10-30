"""启动时和配置变更后预读已发布实体的表的列定义（WP-15、WP-10）。

保存时按列的小数位处理数值（`values.ColumnScales`），每张表第一次用到时读一次 USER_TAB_COLUMNS。原来这一条落在进程启动后
第一次写这张表的命令里，使第一次保存的 SQL 条数比 WP-10 多 1 条。现在插件 start 时先把已发布实体写入的表
（`EntityDirectory.tables`）读进来，读完平台才开始接受请求；之后后台线程每 `interval` 秒取一次已发布实体的表（配置代号
没变时只有一次 Redis 读取，见 config 的 `PublishedEntities`），配置变更新增了实体、有新的表就读进来。

后台线程执行的 SQL 不在任何命令的追踪范围内（`tracing.py` 只记同一上下文的语句），不计入命令的 SQL 条数。发布新实体后
`interval` 秒之内就保存它的，那次保存照旧在第一次用到时读一次列定义。
"""

from __future__ import annotations

import logging
import threading

from cost_platform.contracts.ports import EntityDirectory

from .values import ColumnScales

WARMUP_SECONDS = 5.0
"""后台检查已发布实体的表的间隔（秒）。"""

_log = logging.getLogger(__name__)


class SchemaWarmup:
    def __init__(self, scales: ColumnScales, entities: EntityDirectory, interval: float = WARMUP_SECONDS) -> None:
        self._scales = scales
        self._entities = entities
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> list[str]:
        """读还没读过的已发布实体的表，返回这次读了的表。"""
        done = self._scales.preload(self._entities.tables())
        if done:
            _log.info("已预读列定义：%s", "、".join(done))
        return done

    def _safe_run(self) -> None:
        try:
            self.run_once()
        except Exception:  # noqa: BLE001 - 预读只是让保存少一条 SQL，出错只记日志，保存时照旧按需读取
            _log.exception("预读列定义出错")

    def start(self) -> None:
        """先预读一次（在调用方的线程中，完成后才返回），再启动后台线程每 `interval` 秒检查一次，直到 `stop`。"""
        self._safe_run()

        def loop() -> None:
            while not self._stop.wait(self.interval):
                self._safe_run()

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name="pipeline-schema-warmup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1)
