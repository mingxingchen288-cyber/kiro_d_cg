# realtime

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：`/ws` 端点（会话 Cookie 认证、校验 Origin）；登记连接（用户、会话、订阅的页面）；实现 `RealtimePublisher`，把事件写入 Redis 频道；订阅 Redis 频道，按 audience 推给本进程的连接；心跳；会话失效时关闭连接。
- 不负责：决定推送什么事件（config、delivery、identity）；浏览器端的连接和重连（由 assembly 按 [C10](../契约/C10-实时事件.md) 创建的前端客户端负责）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/realtime/` |
| 状态 | Redis 频道 `{ns}:events`；每个进程内的连接表 |

## 3. 对外契约

提供 `RealtimePublisher`（[C08](../契约/C08-后端端口.md)）和 `/ws`，消息格式见 C10。

- RT-01：握手时以 `touch=False` 调用 identity 的 `Authenticator`；会话无效或 Origin 不在 `PLATFORM_ALLOWED_ORIGINS` 中时拒绝握手。
- RT-02：`publish` 只写 Redis 频道；发布失败只记日志，不影响调用方已提交的事务。
- RT-03：每个进程订阅频道，只把事件推给 audience 匹配的连接。
- RT-04：收到 `session.revoked` 后，推送给对应连接，然后关闭连接。

## 4. 依赖

| 契约 | 提供方 | 用途 |
|---|---|---|
| `Authenticator` | identity | 握手认证 |

## 5. 内部流程

握手认证 → 登记连接 → 处理 `subscribe`、`unsubscribe`、`ping` → 订阅任务收到频道消息 → 按 audience 找连接 → 推送。

## 6. 接入方式

- assembly 挂载 `/ws`，启动订阅任务；config、delivery、identity 调用 `RealtimePublisher`。
- 真实联调：批次 A。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成。
- 本模块完成（模拟验证）：用内存频道验证认证、订阅、按 audience 分发、会话撤销后关闭连接。
- 联调后才能确认：两个后端进程时，一个进程发布的事件能推到连在另一个进程上的浏览器（批次 A）。
