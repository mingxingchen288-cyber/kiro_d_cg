# delivery 任务

模块说明：[delivery](../模块/delivery.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E10（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-DL-1 登记与立即发送

- 归属与目标：实现 DL-01、DL-02、DL-05，"登记通知""投递"阶段和 `DeliveryDispatcher`。
- 前置输入：开始前 T-CT-1、T-CT-3。验收前 T-DB-1、T-DB-2。
- 负责范围：`backend/src/cost_platform/delivery/`；表 `PF_DELIVERY`、`PF_INBOX` 的迁移脚本。
- 交付物：上述阶段和发送逻辑；`/api/inbox` 接口。
- 接入责任：T-AS-5 注册阶段；frontend-shell 读取站内通知（T-AS-7）。
- 验收标准：模拟验证：没有通知意图时不写投递记录；提交后立即发送，写站内通知并发布 `notification`；推送失败不影响发送结果；同一投递编号只写一条站内通知；通过 `DeliveryDispatcher` 和"登记通知""投递"两个阶段（`PipelineStage`）的契约测试（C08 第 14 节）；真实验证：业务回滚时投递记录不保留。
- 状态与证据：完成（2026-10-29；模拟验证和真实验证通过，待独立复核）。代码 `backend/src/cost_platform/delivery/`（`service.py`、`stages.py`、`store.py`、`tables.py`、`router.py`），迁移 `delivery/migrations/dl_0001_pf_delivery.py`（未执行）。
  - 模拟验证：在 `backend` 目录 `uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/delivery`，27 passed、0 failed（本卡：`test_dispatch.py` 8 个，用 E23 的数据；`test_contracts.py` 中 `DeliveryDispatcherContract` 3 个、`PipelineStageContract` 6 个；`test_router.py` 中站内通知 2 个），输出 `.reports/modules/delivery/pytest-2.txt`；`uv run lint-imports --no-cache` 3 kept，`.reports/modules/delivery/lint-imports.txt`。
  - 真实验证：已写好、未运行，等合并后 `platform db upgrade` 再运行：`tests/delivery/test_oracle.py` 的 `test_rolled_back_command_keeps_no_delivery`、`test_e23_on_oracle`、`TestOracleDeliveryDispatcher`（3 个）。
  - 还没有独立复核。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本条"真实验证：已写好、未运行"的 `tests/delivery/test_oracle.py`（第 27 行标 oracle）`TestOracleDeliveryDispatcher`、`test_rolled_back_command_keeps_no_delivery`、`test_e23_on_oracle` 在 d_cg 上通过，联调 `tests/e2e/test_batch_b.py` 的 `test_notification_reaches_approver_after_commit`、`test_delivery_failure_does_not_affect_business` 也通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）。"还没有独立复核"：`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-DL-2 重试、放弃与管理接口

- 归属与目标：实现 DL-03、DL-04 和 `/api/admin/deliveries`。
- 前置输入：开始前 T-DL-1。
- 负责范围：delivery 的重试任务函数和管理路由。
- 交付物：重试任务函数；管理接口。
- 接入责任：T-AS-5 启动后台任务；frontend-admin 使用管理接口（T-AS-7）。
- 验收标准：模拟验证（可控时钟）：失败后依次在 1、2、4、8、16 分钟后重试，第 5 次重试失败后为 `abandoned`；重新排队后再次发送；进程在提交后、发送前退出时，1 分钟后补发；真实验证：两个进程同时运行重试任务，同一记录只发送一次。
- 状态与证据：完成（2026-10-29；模拟验证和真实验证通过，待独立复核）。重试任务函数 `DeliveryService.retry_due`、后台循环 `worker.run_retry_loop`，管理路由在 `router.py`。
  - 模拟验证：同 T-DL-1 的命令和输出（27 passed、0 failed）；本卡：`test_retry.py` 6 个（每分钟一轮的任务下，发送时间依次为 0、1、3、7、15、31 分钟，第 31 分钟为 `abandoned`，尝试次数 6；重新排队后发送成功；重新排队后又失败时 1 分钟后重试；提交后没有立即发送的记录 1 分钟后补发），`test_router.py` 中管理接口 2 个。
  - 真实验证：已写好、未运行：`tests/delivery/test_oracle.py::test_two_workers_send_each_record_once`（两个连接池同时领取 30 条到期记录）。
  - 还没有独立复核。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本条"真实验证：已写好、未运行"的 `tests/delivery/test_oracle.py::test_two_workers_send_each_record_once` 通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）。"还没有独立复核"：`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。
