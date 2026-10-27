# rules-core

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：计算和规则求值（选规则、组装输入、调用 zen-engine、解释结果）；用同一份源码编出 Python 包和 wasm32-wasip1 产物；交付前端计算 Worker 和主线程客户端 `CalcWorkerClient`（C07 第 5 节、C11）；维护样例集；完成可行性验证；整理数值处理规则表。
- 不负责：生成规则包（config）；查询数据库，规则需要的数据由后端查出后放进请求的 `data`；在前端创建 Worker 客户端实例（assembly）；调用预览（frontend-page 经 `ShellApi.calc`）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `rules-core/core`、`rules-core/bindings/python`、`rules-core/bindings/wasm`、`rules-core/Cargo.lock`、`rules-core/web/`（Worker 脚本和 `CalcWorkerClient`） |
| 测试数据 | `rules-core/fixtures/`：成对的请求和期望结果 |
| 数据、配置、状态 | 无 |

## 3. 对外契约

提供 [C07](../契约/C07-规则内核接口.md) 的三个函数，并实现 [C01](../契约/C01-数据格式.md) 的数值一致判定（Rust 版）。

- RC-01：业务衔接逻辑只在 `core` 中写一次。两个包装层只做 JSON 文本进出，不含业务判断。
- RC-02：精确数值全程用 `rust_decimal`，不经过 `f64`。JDM 只允许五种节点；函数节点的序列化会把数值转成 `f64`，所以禁用。
- RC-03：`load_pack` 对每个规则包版本只编译一次；`evaluate` 复用同一个引擎，不在每次调用时新建运行时。
- RC-04：计算过程和输出都不舍入，保留全部精度。zen-engine 用 `rust_decimal` 计算，最多 28 位有效数字；保存只需要 8 位小数（WP-15），整数部分不超过 20 位都不受影响；空值、除零、溢出和求值出错的处理见第 8 节的数值处理规则表。
- RC-05：出错时按 C07 返回错误，不让 panic 穿出，不返回部分结果。
- RC-06：两个产物的 `core_version()` 相同；样例集在两个产物上的结果按 C01 判定一致。
- RC-07：Python 包 `cost_rules_core` 提供 `RulesEngine`（C08 第 8 节）；WASM 以 ES 模块交付；另交付 Worker 脚本和 `createCalcWorkerClient(wasmUrl)`，返回 C11 的 `CalcWorkerClient`，消息格式见 C07 第 5 节。这三样一起放在 `rules-core/dist/web/`。
- RC-08：按 C06 第 5 节的取值约定组装表达式的输入：主表规则每张单据求值一次，明细规则每行求值一次，并提供 `master`、`old`、`context`、`data`。`old` 取自请求中各行的 `old`，没有时等于当前值；rules-core 不查数据库。
- RC-09：`load_pack` 按 C06 第 5 节的规定，从表达式和条件引用的字段算出规则之间的依赖并排序；依赖成环时返回 `PACK_INVALID`（Python 包中抛 C08 第 8 节的 `PackInvalidError`），列出环上的规则。config 保存配置时调用它，把这个错误转成 422 VALIDATION_FAILED。

## 4. 依赖

契约 C01、C07。运行时不依赖其他模块。

## 5. 内部流程

1. 求值：解析请求 → 按 `phase` 和 `purpose` 选出规则 → 按 `load_pack` 算出的顺序调用 zen-engine（每条明细规则对每一行执行完，再执行依赖它的主表规则） → 汇总 `computed`、`fields`、`effects` → 输出 JSON（不舍入）。
2. 构建：Python 包用 maturin；WASM 用 wasm32-wasip1 目标和 wasi-sdk。两者使用同一个 `Cargo.lock`。浏览器加载这个 WASM 需要 COOP 和 COEP 响应头，由 assembly 配置。
3. 可行性验证：期限 3 个工作日。通过条件是两个产物都能构建，并且样例集在两端的结果一致；编译时间、包大小和求值耗时只记录，不作为通过条件。不通过时停下来问用户。

## 6. 接入方式

- 后端：assembly 用 Python 包创建 `RulesEngine`，注入 write-pipeline、approval 和 config。
- 前端：assembly 在 `main.ts` 中调用 `createCalcWorkerClient` 创建实例，放进 `ShellApi.calc`；frontend-page 只通过 `ShellApi.calc` 调用。构建时 assembly 把 `rules-core/dist/web/` 放进前端工程。
- 真实联调：批次 B（后端）、批次 D（前端）。

## 7. 验收边界

- 开始开发的前置条件：C01、C07 已确认；用户同意安装 wasm32-wasip1 目标、wasi-sdk 和 C 编译器。
- 本模块完成：可行性验证通过；两个产物的样例集结果一致；第 8 节每一行都有样例并在两个产物上通过。
- 联调后才能确认：后端写入和前端预览对同一单据算出一致的结果。


## 8. 数值处理规则表

按旧系统前端计算引擎（`D:\chonggou\my-project\cost-web\src\v3\logic\calc-engine\calculator.ts`）的处理方式确定。

| 情况 | 处理 | 旧系统依据 |
|---|---|---|
| 表达式引用的字段为空，或行中没有这个字段 | 按 0 参与计算；需要别的默认值时用 `NVL(字段, 默认值)` | `normalizeScopeValue` 返回 `value ?? 0`；`ensureFieldRefInScope` 把缺失的字段设为 0 |
| 除以 0（包括 0/0） | 结果为 0 | `normalizeNumber` 把 NaN、Infinity 改为 0 |
| 溢出（超出 28 位有效数字） | 结果为 0 | 同上，非有限值改为 0 |
| 计算规则求值出错（例如类型不对） | 该字段为 0，其余规则照常计算，并在结果中给出一条 `prompt` 说明哪条规则出错 | `calcRowFields` 的 catch 把字段设为 0 |
| 条件（`when`）求值出错 | 按成立处理 | `evalCondition` 的 catch 返回 true |
| 汇总时某行的字段为空 | 按 0 计入 | `aggregate` 中 `Number(r[field]) \|\| 0` |
| 汇总时没有行 | SUM、COUNT、AVG、MAX、MIN 都为 0 | `aggregate` 在行数为 0 时返回 0 |
| 分支都不匹配 | 字段保持原值 | `calcRowFields` 中未匹配分支时保留原值 |
| 中间结果和输出 | 不舍入（RC-04）；保存时最多 8 位小数并四舍五入（write-pipeline 的 WP-15） | 旧系统按字段精度舍入，新平台按用户要求改为不舍入 |

有一处与旧系统不同：旧系统用 JavaScript 浮点计算，`0.1 + 0.2` 得到 `0.30000000000000004`；新平台用十进制计算，得到 `0.3`。对账时这类差异归入"浮点误差"。
