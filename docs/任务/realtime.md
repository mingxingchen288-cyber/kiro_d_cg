# realtime 任务

模块说明：[realtime](../模块/realtime.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E18、E19（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-RT-1 WebSocket 与事件分发

- 归属与目标：实现 RT-01–RT-04 和 `RealtimePublisher`。
- 前置输入：开始前 T-CT-1、T-CT-3；C10 经用户确认。验收前 Redis 可用。
- 负责范围：`backend/src/cost_platform/realtime/`。
- 交付物：`/ws` 端点、连接登记、发布和订阅任务函数；握手和心跳时检查会话（`touch=False`）。
- 接入责任：T-AS-4 挂载 `/ws` 并启动订阅任务；浏览器端客户端属于 T-AS-3。
- 验收标准：模拟验证：会话无效或 Origin 不符时拒绝握手；事件只推给 audience 匹配的连接；会话过期或撤销后关闭连接；通过 `RealtimePublisher` 的契约测试（C08 第 14 节）；真实验证：两个进程时，一个进程发布的事件能推到连在另一个进程上的连接。
- 状态与证据：完成（2026-10-29；真实验证通过，还没有独立复核）。
  - 模拟验证：通过。命令为在 `backend` 目录执行 `uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/realtime`，17 个通过、0 个失败（`.reports/modules/realtime/pytest-1.txt`）。用 FastAPI 的 TestClient 连 `/ws`，会话用 `FakeAuthenticator`，频道用 `MemoryChannel`：
    - `test_handshake.py`：握手和心跳都以 `touch=False` 认证；Origin 不符返回 403 ORIGIN_REJECTED；没有会话、会话已过期（E19）返回 401 SESSION_REQUIRED；
    - `test_dispatch.py`：`config.changed` 只推给打开了该页面的连接（E18），影响两个页面时每个连接只收一条，取消订阅后不再收到；`notification` 推给接收人的每个连接（E23），与订阅的页面无关；
    - `test_session_end.py`：停用账号（`users`）、注销（`sessions`）后先推 `session.revoked` 再以 4401 关闭，别的用户、别的会话不受影响；心跳不顺延会话，会话过期后的心跳关闭连接（E19）；
    - `test_processes.py`：两套 `Realtime`（两个应用、两个事件循环）共用一个内存频道，一个发布的事件推到连在另一个上的连接；
    - `test_publisher.py`：`ChannelPublisher` 通过 `RealtimePublisherContract`（C08 第 14 节）；频道消息与 C10 第 1 节样例相同；频道不可用时只记日志。
  - 真实验证：测试已写好，没有运行，因为本机没有 Redis。`tests/realtime/test_redis.py` 共 3 个（`-m redis`）：`RedisChannel` 上的 `RealtimePublisherContract` 两个；另一个操作系统进程（`tests/realtime/publish_event.py`）经 Redis 发布、本进程的 `/ws` 连接收到。
  - 上线后再补：Redis 断开后订阅任务重试、频道里有不符合 C10 的消息时跳过、浏览器发来不符合 C10 的消息时忽略，这三处只写了处理，没有测试。
  - 接口位置：`realtime/service.py` 的 `Realtime`（`router` 挂 `/ws`、`publisher`、`start`、`stop`）；频道 `realtime/channel.py`（`MemoryChannel`、`RedisChannel`）。契约缺口和接入说明见 `.reports/modules/realtime/contract-gaps.md`。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：`tests/realtime/test_redis.py`（`TestRedisChannelPublisher`、`test_event_from_another_process_reaches_connection`）和 `tests/realtime/test_plugin.py` 第 70 行的 Redis 用例通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）；两个后端进程之间的推送另由联调 `tests/e2e/test_batch_a.py` 验证（同一次）。Redis 断开重试、不合格消息跳过：本条已标上线后再补。"还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。
