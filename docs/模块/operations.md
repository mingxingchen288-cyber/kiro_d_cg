# operations

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：按钮通用动作（[C06](../契约/C06-配置模型.md) 第 6 节）的展开；为按钮操作确定涉及的单据；按关联键查找目标（经 `RelatedQuery`）；字段映射；传播边界；执行按 SQL 的两个动作 `replaceDetails`、`updateRows` 的查询（OP-09、OP-10）；执行已登记的逃生舱（按钮和审批流的 `escapeHatch` 都由本模块执行）。
- 不负责：合并修改、计算和写入（write-pipeline、rules-core）；审批流通过后的操作的展开、受影响单据和勾选（approval，C06 7.5）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/operations/` |
| 数据 | 无自有表；逃生舱的调用审计写入命令记录 |

## 3. 对外契约

实现"确定涉及的单据"（按钮操作）和"动作执行"中的展开部分（[C08](../契约/C08-后端端口.md) 第 6 节）。

- OP-01：动作按数组顺序执行；每个动作展开后，由 write-pipeline 合并并计算，下一个动作使用上一个动作计算后的结果。
- OP-02：字段映射：`fieldMapping` 的 `from` 取来源计算后的值；按关联键或按绑定明细字段的关联 SQL 找到的目标，取找到它的那一行来源的值，`match` 中引用来源明细的字段也取这一行的值，`from` 和 `match` 引用主表字段时取主表的值（C06 第 6 节）。按钮的 `updateRecords` 找到的目标按 OP-07 取值。同一目标行（带 `detailEntity` 时为 `match` 选出的明细行）被写入不同的值时，返回 422 VALIDATION_FAILED，同一目标被几行找到而各自写不同的明细行时不冲突。`to` 必须在操作允许写入的字段内。
- OP-03：`propagation` 为 `end` 时，写到目标的修改带上本审批或本操作的来源，目标只执行自身的计算和校验规则，不触发审批，也不再执行同步动作。
- OP-04：逃生舱只在用户点名时启用。它在命令事务内、加锁和冻结检查之后执行，自身不提交也不回滚；每次调用记录逃生舱、参数、执行人、时间和请求键，随命令记录一起写入。
- OP-05：按钮操作的 `requiresSelection` 为 true 而 `params.selectedRows` 为空时，返回 422 VALIDATION_FAILED。`requiresSelection` 只规定执行的前提；操作实际处理的行和执行权限，照常按操作配置、按钮权限和行权限检查。
- OP-06：审批流通过后的操作由 approval 展开（approval AP-10，C06 7.5）；其中的 `escapeHatch` 交本模块按 OP-04 执行。
- OP-07：按钮操作的 `updateRecords` 按 `find` 经 `RelatedQuery` 查找记录，传入选中单据在数据库中的当前数据，`rows` 只能为 `all`，绑定明细字段的关联 SQL 也用全部行（C08 第 9 节）。按关联键或按绑定明细字段的关联 SQL 查找时，按选出的行分别调用 `find`，记下每个目标由哪几行找到，字段映射按这些行取值（C06 第 6 节，C08 第 9 节）。`RelatedQuery` 返回的 `missing` 对象（记录已不存在，C08 第 9 节）跳过，不更新，也不报错。找到的单据不在本命令涉及的单据中时，由 write-pipeline 加锁并做冻结检查后再合并（WP-18）。加锁顺序（write-pipeline WP-03，用户 2026-10-30 规则 3）：找到的单据排在选中单据之后时（例如成本单找物料清单）由加锁读取在这一轮往后追加；排在之前或同层时（成本单找别的成本单，`updateRows` 同样），"确定涉及的单据"在加锁前普通读出选中单据，用它把 `find` 和 `updateRows` 的 SQL 执行一次，选中的和找到的单据按顺序一次锁完，锁住后核对选中单据没有变（变了时整个事务回滚重来，WP-13）；展开动作时只认锁住的这一批，范围查询和加锁之间新冒出来的单据不写，相当于那次修改发生在本命令之后。`replaceDetails` 只写选中的单据，不用预查。
- OP-08：按钮操作只按选中行的主键执行（C02 第 1 节）。"确定涉及的单据"阶段按 `params.selectedRows` 找出所属单据，写入 `involved`；命令带了 `documents` 时返回 400 INVALID_REQUEST。动作的来源都取 write-pipeline 加锁读到的当前数据，不用前端的值；选中的行已不存在时按 WP-05 处理。`updateRows` 不看选中行（OP-10）。
- OP-09：`replaceDetails`（C06 v18 第 6 节）：对每张选中的单据，删除它在 `entity` 中的全部行（加锁读到的当前数据），再在命令事务的连接上执行一次 `sql`（绑定变量取这张单据主表计算后的值），把查出的每一行新增为 `entity` 的一行：列名就是字段名，按字段类型转换取值，`clientRowId` 按请求键、动作序号、单据和行序号生成（同一请求重放时相同）。要写的字段不在 `writableFields` 中或不可写时返回 422 FIELD_NOT_WRITABLE。展开只生成删除、新增的 `intents`；关联字段、名称这类只在视图中的字段（按页面 Lookup 带出）、计算和写入都由 write-pipeline 完成（WP-08、WP-18）。新增的意图 `fill_defaults` 为 False：SQL 没给的字段不补默认值（WP-16 的例外），不进 INSERT，取数据库的列默认值，例如"由BOM生成明细"新增的明细额外投料量为空、客户指定为列默认值 0。来源：旧 P_COST_BOM_INSERT（`my-project/sql20260523/03_program_units.sql` 第 699–760 行）的 INSERT 只写 BOM 查出的列，不写 EXADD_MATER、CUSTOMER_SPECIFIED；用户 2026-10-30 同意直接做。
- OP-10：`updateRows`（C06 v18 第 6 节）：在命令事务的连接上执行一次 `sql`，不用绑定变量，不看选中行。每一行按 `recordKeyColumn`（单据主键）和 `rowKeyColumns`（明细主键）找到一条记录，其余列写到同名字段；主键列为空的行跳过；同一记录的同一字段被写成不同的值时返回 422 VALIDATION_FAILED，不可写的字段返回 422 FIELD_NOT_WRITABLE（与 OP-02 相同）。找到的单据不在 `involved` 中，由 write-pipeline 加锁、做冻结检查后再合并（WP-18）；加锁顺序同 OP-07。
- 用户 2026-10-29："那两个存储过程是有问题的，它内部又计算了一次，这是不应该的，后续都可以不用存储过程计算了"；"按钮无论有多少动作，都应该在同一个事务内"。成本核算的"由BOM生成明细"（旧 P_COST_BOM_INSERT）用两个 `replaceDetails`（seed 的 `operation.COST_PINGGU.generateFromBom.json`），不调存储过程；逃生舱保留。旧系统的"同步采购价"（旧 P_PINGGU_COMPUTE_ALL）用户 2026-10-30 不要了，按钮和操作配置已删除；`updateRows` 是通用动作，保留。

## 4. 依赖

| 契约 | 提供方 | 用途 |
|---|---|---|
| `RelatedQuery` | queries-export | 按关联键或关联 SQL 查找目标 |
| `UnitOfWork` | db-core | 逃生舱在命令事务内调用存储过程；`replaceDetails`、`updateRows` 在命令事务的连接上只读执行配置的 SQL |
| `BusinessLocker` | write-pipeline | 找到排在选中单据之前或同层的单据时，加锁前普通读取选中单据、按统一顺序一起锁住（WP-03，OP-07） |

## 5. 内部流程

读取按钮操作的动作 → 按顺序生成每个动作的修改意图（要改哪些单据、哪些行、哪些字段）→ 交 write-pipeline 合并与计算 → 下一个动作。

## 6. 接入方式

- write-pipeline 调用本模块实现的阶段，由 assembly 注册。
- 真实联调：批次 B（按钮操作）。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成。
- 本模块完成（模拟验证）：每种动作的展开结果、字段映射、取值冲突、传播边界、选中行为空。
- 联调后才能确认：按钮的 `updateRecords` 在 Oracle 上只更新找到的行（批次 B）。
- `replaceDetails`、`updateRows` 的真实验证（T-OP-3）：在 d_cg 上经真实的写入管道跑"由BOM生成明细"和测试里自己定义的 `updateRows` 操作。
