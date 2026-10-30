# write-pipeline

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：提供写入能力（[C08](../契约/C08-后端端口.md) 第 5a 节），由 orchestration 的 `CommandExecutor` 按[架构第 7 节](../架构与组装.md)的顺序调用；判重；加锁读取；合并修改；生成只含变化列的变更计划；写入业务表（含物理删除和级联删除）；必填检查；审计差异；写入命令记录并提交；提交后调用投递。
- 不负责：冻结和审批（approval）、按钮动作的展开（operations）、审批流通过后的操作的展开（approval）、计算和规则（rules-core）、权限判断（authz）、发送通知（delivery）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/pipeline/` |
| 数据 | 表 `PF_COMMAND`：用户、请求键、操作、页面、内容摘要、状态、命令结果、审计差异、时间，永久保留；业务表中平台自有列的写入 |
| 状态 | 每个命令的 `CommandState`（[C08](../契约/C08-后端端口.md) 第 6 节），命令结束即丢弃 |

## 3. 对外契约

提供 `CommandRecorder`、`DocumentStore`、`ChangeMerger`、`TableWriter`（C08 第 5a 节），由 orchestration 的 `CommandExecutor` 和 approval 调用；命令的输入输出和错误见 [C02](../契约/C02-命令与结果.md)、[C03](../契约/C03-错误.md)。

- WP-01：事务的第一条语句插入命令记录，唯一键为（用户、请求键）。已完成且内容摘要相同时返回原结果，不执行业务流程；摘要不同时返回 422 IDEMPOTENCY_KEY_REUSED；同一请求键仍在处理时最多等待 5 秒（`.env` 的 `PLATFORM_REQUEST_WAIT_SECONDS`），超时返回 409 REQUEST_IN_PROGRESS。
- WP-02：任一步失败，整个事务回滚，命令记录一起撤销，同一请求键可以重新提交。
- WP-03：按（实体、主键）排序，用 `SELECT … FOR UPDATE WAIT 5` 锁定涉及的主表行（秒数取 `.env` 的 `PLATFORM_LOCK_WAIT_SECONDS`），同一条 SQL 中带出行权限的判断列；等锁超时返回 409 DOCUMENT_BUSY；有一行超出行权限时返回 403 PERMISSION_DENIED。
- WP-04：合并时只改 `changes` 中出现的字段；新值与当前值相同不算变化，数值按数值相等比较。Patch 中出现计算字段、只读的 ERP 列（C06 第 2 节）、`erpRow.column`、主键、主从关联字段或不可写字段时，返回 422 FIELD_NOT_WRITABLE。
- WP-05：要修改或删除的行（按钮操作为选中的行，C02 第 1 节）已不存在时，按操作的 `rowNotFound` 处理：默认跳过并写入结果的 `skipped`；配置为 `reject` 时返回 409 ROW_NOT_FOUND。
- WP-06：删除主表行时，在同一事务中先物理删除它的全部明细，再删除主表行。
- WP-14：实体有 `erpRow` 时，按加锁读到的当前值判断每一行是否为 ERP 行，修改 ERP 行的 ERP 列返回 422 FIELD_NOT_WRITABLE；新增行的 `erpRow.column` 由写入管道设为 `localValue`。
- WP-15：写入数值前处理小数位：最多保留 8 位小数，按第 9 位四舍五入（负数按绝对值四舍五入，与 Oracle 相同）；列定义了小数位（`NUMBER(p,s)`）且小于 8 时，按列的小数位四舍五入，与 Oracle 存储的结果一致。命令结果中的受影响行和审计差异使用处理后的值，与数据库相同。计算过程中的值不受影响。列的小数位经 `SchemaInspector` 读取，每张表在进程内只读一次：插件 start 时把已发布实体写入的表（`EntityDirectory.tables`）先读进来，读完平台才接受请求；之后后台每 5 秒检查一次，配置变更新增了实体的表就读进来。所以保存时不再读列定义，第一次保存的 SQL 条数与 WP-10 相同；发布新实体后 5 秒之内就保存它的，那次保存照旧多读一次。
- WP-16：新增行的默认值（C06 第 2 节 `default`）：前端新增行时先按配置填上（frontend-page 的 FP-15）；写入管道在写入新增行时，Patch 中没有的字段补上默认值；字段不可编辑时，`builtin` 默认值一律按执行上下文重新取，不用前端传来的值。复制出的行（带 `copyOf`）不补默认值。
- WP-21：复制出的行（C02 第 1 节 `copyOf`）写入复制时勾选的全部字段。合并修改前按主键另读命令中各复制行的源行，每个实体一条 SELECT，不加锁（源单据被别人编辑或被审批冻结时照样能复制）；主表实体加角色的行权限条件，明细实体要求所属主表行满足行权限；读不到时 409 ROW_NOT_FOUND。新行的值：可写的字段取 Patch 中的值（复制后用户可能改过）；不可写、但在页面视图中可见、能写进表的字段（不是主键、关联字段、计算字段、`erpRow.column`、只读的 ERP 列）取源行的值，Patch 中的值不用；计算字段和只在视图中的字段不写（计算字段由计算规则算出）；其余不可写的字段照常 422 FIELD_NOT_WRITABLE。不补默认值；`erpRow.column` 设为 `localValue`。没有复制行的命令不读源行，WP-10 的条数不变。来源：旧系统复制源行全部字段（`copy-row-fields.ts` 第 23–29 行）、新增行提交全部字段（`useWorkingSetStore.ts` 第 834–876 行）、后端插入只跳过虚拟列（`DynamicDataService.java` 第 274–327 行）；上一组的核对见 `.reports/batch3-20261030/h3-new-doc/findings.md`；用户 2026-10-30 同意按旧系统做。
- WP-17：命令审查。管理员开启后，每个命令结束时（提交或回滚之后）记录一条：用户、请求键、页面、操作、结果、错误码和信息、开始时间、总耗时、SQL 条数、数据库耗时，以及每条 SQL 的文本、绑定值、耗时、影响行数和错误，与旧系统的操作日志相同。记录写入 Redis 列表 `{ns}:cmdlog`，不写数据库，最多保留最近 10000 条；写入失败只记应用日志，不影响命令。关闭时删除这个列表和开关。开关存在 Redis 键 `{ns}:cmdlog:enabled`，所有进程共用。
- WP-07：页面保存时检查必填。检查的行是本次新增、修改的行，加上计算后有计算字段变化的行（与命令开始时的值比较，例如只改主表批量，每批数量跟着变了的原辅料行）；删除的行不查。检查这些行的全部必填字段，为空时返回 422 VALIDATION_FAILED，逐项给出字段。按钮操作和审批处理不检查必填。来源：旧系统保存时对有修改的行（含计算带出变化的行，去掉删除的行）检查列的必填（`cost-web/src/v3/composables/meta-v3/useWorkingSetStore.ts` 第 886–934 行、`useCalcBroadcast.ts` 的 `markFieldChange(…, 'calc')`、`logic/calc-engine/validator.ts` 第 52–85、116 行），旧系统的按钮由后端执行，不经这一步；用户 2026-10-30 同意按旧系统做。
- WP-08：写入以 rules-core commit 阶段的结果为准。求值请求中各行的 `old` 取加锁读取时读到的当前值（多个动作时始终取命令开始时的值），不另查数据库。计算带出的变化并入同一个变更计划，包括 Patch 未涉及的行，例如汇总到的主表行。只有单据有新增、删除的行，或者改到了保存时执行的规则读取的字段（C08 `ConfigSnapshot.rule_fields`）时才求值；只改备注这类字段时不读明细、不求值，其他列保持原样（用户 2026-10-29 选定）。
- WP-09：主表写 0 或 1 条语句；每张明细表的每种操作，按写入的列分组，每组一条批量语句。新增行的主键取序列 `<表名>_SEQ`，用 `RETURNING` 取回，填入结果的 `idMap`。审批通过时写入的新增行，使用提交审批时已取得的主键（approval AP-02）。
- WP-10：SQL 条数目标：改主表一个字段 4 条；提交的值与当前值相同 2 条（插入命令记录、加锁读取，然后回滚）；改一条明细并重算汇总 6 条；可冻结业务另加 1 条冻结查询；配了审批流时，审批流 `operations` 选中的每个改动的行另加 1 条入口条件（approval AP-01，用户 2026-10-30 接受：例如成本核算改一行原辅料、审批流 COST_TO_GOODS 已启用时为 8 条）。达不到时停下来问用户。
- WP-11：页面视图的 `audit` 为 true 时，命令记录中写入审计差异：修改的行逐字段记旧值和新值，新增行记写入的值，删除的行（包括级联删除的明细）记删除前的值。审计差异随完成命令记录的同一条语句写入。
- WP-12：命令结果中的受影响行取自候选数据，不再查询数据库，每行包含实体的全部字段。
- WP-13：命令只执行一次，写入管道不自动重试。
- WP-18：动作执行中，operations 把每个动作展开为 `CommandState.intents`（C08 第 6 节）。write-pipeline 取出 `intents`，其中所属单据不在"确定涉及的单据"阶段给出的 `involved` 中的（例如按钮的 `updateRecords` 按关联查询找到的单据、`updateRows` 按 SQL 找到的单据，或审批流受影响单据中不在冻结范围内的行所属的单据），先把这些单据加入 `involved`，按（实体、主键）排序用 WP-03 的方式加数据库行锁并读入 `current`，再对它们执行一次冻结检查阶段（approval AP-03，来源为本审批时放行本审批的冻结），都通过后才把 `intents` 合并进 `candidate` 并清空；被别的审批冻结时整个命令返回 409 FROZEN_BY_APPROVAL，超出行权限返回 403 PERMISSION_DENIED（来源为审批时不查行权限，C08 第 7 节）。行锁在命令结束时释放，不登记冻结记录。这次加锁在已有的锁之后，可能与其他命令交叉等待：等锁超时，或 Oracle 检出死锁，都返回 409 DOCUMENT_BUSY，整个命令回滚。
- WP-20：实体配了 `updatedByColumn`（C06 第 2 节）时，写入变更阶段新增、修改这个实体的行，在同一条语句里把这一列写成当前用户的登录名（执行上下文的 `identity.username`），不多出 SQL；审批通过时写入的行写执行通过的审批人（来源为审批的命令沿用审批人的身份）。删除不写。这一列不是实体字段，不进命令结果和审计差异。来源：旧系统 `DynamicDataService.java` 第 290–293、392–393 行每次新增、修改写 UPDATE_BY = `SecurityUtils.getCurrentUsername()`（登录用户名）；审批通过时 `ConfiguredApprovalRuntime.java` 的 `applyPending` 在审批人的请求中调同一段保存；用户 2026-10-30 同意按旧系统做。物料清单视图按它显示 ERP 行"已被修改"的黄底（h5 的核对，`.reports/batch3-20261030/h5-goods-page/findings.md`）。
- WP-19：`TableWriter` 写没在平台注册的表（审批流通过后的操作，C06 7.5）：按主键用 WP-03 的方式加行锁读出整行，approval 做冻结检查后，按主键只写指定的列，不校验、不计算；数值按 WP-15 处理小数位；改前、改后的列值记入命令记录的审计差异（WP-11，不看页面的 `audit`）。新增行的主键取序列 `<表名>_SEQ`。等锁超时返回 409 DOCUMENT_BUSY；表、列不存在等数据库错误按 C08 第 2 节映射，整个命令回滚。

## 4. 依赖

| 契约 | 提供方 | 用途 |
|---|---|---|
| `UnitOfWork` | db-core | 命令事务 |
| `SchemaInspector` | db-core | 列的小数位（WP-15）；`TableWriter` 新增行的主键和列 |
| `EntityDirectory` | config | 已发布实体写入的表，启动时和配置变更后预读列定义（WP-15） |
| `PipelineStage` 的各实现 | authz、operations、approval、delivery | 按顺序调用 |
| `PermissionChecker` | authz | 写权限、行权限条件 |
| `RulesEngine` | rules-core | commit 阶段求值 |
| `DeliveryDispatcher` | delivery | 提交后投递 |

## 5. 内部流程

判重 → 操作权限 → 确定涉及的单据 → 加锁读取 → 冻结检查 → 审批处理 → 按动作顺序执行（展开、合并、写权限、计算与规则）→ 触发审批 → 写入变更 → 审计 → 登记通知 → 写命令记录并提交 → 投递。提交审批的单据（`CommandState.pending_documents`）整张不写；其余单据照常写入。

## 6. 接入方式

- assembly 挂载 `POST /api/commands`，把本模块的能力和各模块的阶段注入 orchestration；approval 调用 orchestration 的 `CommandExecutor`。
- 真实联调：批次 B。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成。
- 本模块完成（模拟验证）：用替代实现覆盖改一格、提交相同的值、明细重算、新增和删除明细、删除主表级联删除明细、规则拒绝、规则提示、行已被删除、改 ERP 行的 ERP 列被拒而改本地行的成功、同一请求键重复提交和并发提交。
- 联调后才能确认：在 Oracle 上用 SQL 追踪核对 WP-10 的条数；两人同时修改同一单据的不同行时两人的修改都保留（批次 B）。

