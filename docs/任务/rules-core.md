# rules-core 任务

模块说明：[rules-core](../模块/rules-core.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E02、E03（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-RC-1 工具链与可行性验证

- 归属与目标：完成模块说明第 5 节的可行性验证，期限 3 个工作日。
- 前置输入：开始前用户同意安装 wasm32-wasip1 目标、wasi-sdk 和 C 编译器；C01、C07 经用户确认。
- 负责范围：`rules-core/` 的 Cargo 工作区（core、bindings/python、bindings/wasm）、构建脚本 `tools/build-rules-core.ps1`、最小样例集。
- 交付物：用同一个 `Cargo.lock` 编出 Python 包和 WASM 的最小实现（求值一条表达式规则）；样例至少含 0.1+0.2、除法、`123456789012345.67` 加 `0.01` 和 C01 的边界样例；构建时间、包大小、求值耗时的记录。
- 接入责任：结论交用户；不含接线。
- 验收标准：两个产物都能构建；样例在 Python 和浏览器（Chromium，经 Playwright 运行）中的结果按 C01 判定一致。不通过或超期时停下来问用户。
- 状态与证据：未开始。

### T-RC-2 规则求值与交付产物

- 归属与目标：实现 RC-01–RC-03、RC-05–RC-09。
- 前置输入：开始前 T-RC-1 通过；C06 第 5 节、C07 经用户确认。
- 负责范围：`rules-core/core`、两个包装层、`rules-core/fixtures/`。
- 交付物：C07 的完整实现（preview 和 commit 阶段，计算、校验、界面规则、触发审批、审批入口，出错处理）；C01 判定的 Rust 实现；Python 包 `cost_rules_core`；`rules-core/dist/web/`：WASM ES 模块、Worker 脚本和 `createCalcWorkerClient`；覆盖每种规则和每种错误的样例集。
- 接入责任：后端由 T-AS-5 注入 write-pipeline、approval、config；前端由 T-AS-3 创建 Worker 客户端实例，T-AS-7 联调。
- 验收标准：样例集在两个产物上全部通过且结果一致，浏览器中经 `createCalcWorkerClient` 运行（Playwright、Chromium）；proptest：同一请求求值两次结果相同，上游结果按全部精度参与下游计算（例如 1/3 再乘 3，结果与按 28 位有效数字计算的值一致，不因中间舍入改变）；同一规则包重复求值不重新编译；跨实体依赖（明细引用主表、主表汇总明细）一次求值得到最终值，与按依赖顺序逐条手算的结果相同；依赖成环的规则包 `load_pack` 返回 `PACK_INVALID`（Python 包中抛 C08 第 8 节的 `PackInvalidError`）；`old` 只给出改过的字段时，其余字段的 `old` 等于当前值；Python 包通过 `RulesEngine` 的契约测试（C08 第 14 节）。
- 状态与证据：未开始。

### T-RC-3 数值处理规则表的样例

- 归属与目标：实现 rules-core 模块说明第 8 节。
- 前置输入：开始前 T-RC-1 通过。
- 负责范围：`rules-core/fixtures/` 中的样例；第 8 节的处理在 T-RC-2 的代码中实现。
- 交付物：第 8 节每一行至少一个样例，并附上旧系统前端计算引擎对同一输入的结果。
- 接入责任：样例供 T-RC-2 和 T-MG-3 的对账使用。
- 验收标准：每个样例在两个产物上通过；与旧系统结果不同的只有浮点误差一类，逐条列出。
- 状态与证据：未开始。
