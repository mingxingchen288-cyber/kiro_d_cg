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
- 状态与证据：进行中——验收标准已满足，等独立复核（工程约定第 7 节）后改为完成。
  - 工具链：zen-engine 2.1.6 无条件依赖 QuickJS（C 代码），按用户 2026-10-28 的同意装了 wasi-sdk 34（`%USERPROFILE%\.local\wasi-sdk\wasi-sdk-34.0`，其中的 libclang.dll 供 bindgen 使用）；maturin 1.15.0 经 `uvx --from maturin==1.15.0` 运行。
  - 真实验证（2026-10-28，`pwsh -NoProfile -File .reports/T-RC-2/verify-all.ps1`，先清空 `rules-core/target` 和 `dist`）：
    - 构建：`tools/build-rules-core.ps1`，两个产物都用 `rules-core/Cargo.lock`（`--locked`，构建前后 SHA256 相同）。Python 包 488.1 秒，wheel 9,477,612 字节；WASM 242.4 秒（在 Python 包之后顺序构建，宿主端的构建脚本和过程宏已编好），`rules_core.wasm` 13,023,015 字节。输出：`.reports/T-RC-1/build.log`、`.reports/T-RC-1/build-metrics.json`。
    - 样例：`rules-core/fixtures/cases/` 的 01–05（0.1+0.2、除法、`123456789012345.67` 加 `0.01`、除以 0、C01 第 16 位）和 91（C01 第 3 节的 9 组边界样例）。浏览器（Playwright 1.64.1、本机 Chrome 156 无头模式、页面跨源隔离）：6 条通过，失败 0；Python 包：求值 5 条、边界样例 9 条通过，失败 0；两端逐条比较：6 条按 C01 一致，且逐字节相同；两端 `core_version` 都是 0.1.0。输出：`.reports/T-RC-2/playwright.log`、`browser-results.json`、`python.log`、`python-results.json`。
    - 求值耗时：一条表达式规则求值一次，Python 0.07–0.23 毫秒，浏览器经 Worker 0.2–0.35 毫秒（第一次 11.9 毫秒）；WASM 在页面中初始化 77.5 毫秒。
  - 复核记录：待写（`.reports/review/T-RC-1.md`）。

### T-RC-2 规则求值与交付产物

- 归属与目标：实现 RC-01–RC-03、RC-05–RC-09。
- 前置输入：开始前 T-RC-1 通过；C06 第 5 节、C07 经用户确认。
- 负责范围：`rules-core/core`、两个包装层、`rules-core/fixtures/`。
- 交付物：C07 的完整实现（preview 和 commit 阶段，计算、校验、界面规则、触发审批、审批入口，出错处理）；C01 判定的 Rust 实现；Python 包 `cost_rules_core`；`rules-core/dist/web/`：WASM ES 模块、Worker 脚本和 `createCalcWorkerClient`；覆盖每种规则和每种错误的样例集。
- 接入责任：后端由 T-AS-5 注入 write-pipeline、approval、config；前端由 T-AS-3 创建 Worker 客户端实例，T-AS-7 联调。
- 验收标准：样例集在两个产物上全部通过且结果一致，浏览器中经 `createCalcWorkerClient` 运行（Playwright、Chromium）；proptest：同一请求求值两次结果相同，上游结果按全部精度参与下游计算（例如 1/3 再乘 3，结果与按 28 位有效数字计算的值一致，不因中间舍入改变）；同一规则包重复求值不重新编译；跨实体依赖（明细引用主表、主表汇总明细）一次求值得到最终值，与按依赖顺序逐条手算的结果相同；依赖成环的规则包 `load_pack` 返回 `PACK_INVALID`（Python 包中抛 C08 第 8 节的 `PackInvalidError`）；`old` 只给出改过的字段时，其余字段的 `old` 等于当前值；Python 包通过 `RulesEngine` 的契约测试（C08 第 14 节）。
- 状态与证据：进行中。计算部分已完成（用户 2026-10-28 指定的范围）：`load_pack`、`evaluate`、`core_version`，`calc` 规则的单个表达式、`branches`、`master.字段`、主表汇总明细（含按条件求和）、依赖排序和成环检查、preview 和 commit 两个阶段，第 8 节的空值按 0、除以 0 为 0、分支都不匹配保持原值、不舍入；Python 包 `cost_rules_core` 和 `rules-core/dist/web/`（WASM、`index.js`、`worker.js`、`createCalcWorkerClient`）已交付。校验、界面规则、触发审批、审批入口先按 C07 返回合法的空结果（没有提示和效果，审批入口不满足）。
  - 真实验证（与 T-RC-1 同一次 `.reports/T-RC-2/verify-all.ps1`）：
    - 原生：`cargo test -p rules-core --locked`，单元测试 2 passed，样例集 19 个全部通过，失败 0（`.reports/T-RC-2/cargo-test.log`）。
    - 浏览器：`rules-core/web/test/run-browser.ps1`，样例经 `createCalcWorkerClient` 在 Worker 中运行，20 passed、0 failed（19 个样例和 1 条跨源隔离检查；`playwright.log`、`browser-results.json`）。
    - Python 包：`rules-core/tests/run-python.ps1`（在 backend 目录 `uv run --with <wheel> pytest tests/rules_core`），38 passed、0 failed：`RulesEngine` 契约测试 9 条、样例 17 条、C01 边界样例 9 条、依赖成环抛 `PackInvalidError`、重复求值不重新编译、性质测试（Hypothesis 200 例，作用同 proptest：同一请求两次结果相同；QTY/3 再乘 3 等与逐步按 28 位有效数字计算的值相同）（`python.log`）。
    - 两端：`rules-core/tests/cross_check.py`，19 个样例按 C01 一致 19、不一致 0，逐字节相同 19，`core_version` 相同（`python-results.json`）。
    - 样例覆盖：E02（preview 和 commit 结果相同）、E03、E04（正负数都不舍入）；cmx 单据 200726 的 11 条真实明细，重算的 BATCH_QTY、COST_BATCH 与 cmx 虚拟列相同，主表 13 个计算字段按用户公式；新增行计入、删除行不计入汇总；胶囊和中盒分支；分支都不匹配保持原值（cmx 200203 的"PVC 250μm"）；`old` 只给出改过的字段；serverOnly 规则只在 commit 执行；审批入口；INPUT_INVALID；跨实体依赖成环。期望值由 `rules-core/fixtures/oracle.py` 按用户公式逐步手算（每步按 28 位有效数字）。
    - 求值耗时：成本核算单据 200726（17 条计算规则、11 条明细），每次 Python 1.29 毫秒、浏览器经 Worker 2.26 毫秒、浏览器主线程直接调用 1.74 毫秒（各 200 次平均）。
  - 未做：校验、界面规则、触发审批、审批入口的求值，结果中行的 `fields` 和 `style`；第 8 节中求值出错、条件出错、溢出的样例（T-RC-3）。

### T-RC-3 数值处理规则表的样例

- 归属与目标：实现 rules-core 模块说明第 8 节。
- 前置输入：开始前 T-RC-1 通过。
- 负责范围：`rules-core/fixtures/` 中的样例；第 8 节的处理在 T-RC-2 的代码中实现。
- 交付物：第 8 节每一行至少一个样例，并附上旧系统前端计算引擎对同一输入的结果。
- 接入责任：样例供 T-RC-2 和 T-MG-3 的对账使用。
- 验收标准：每个样例在两个产物上通过；与旧系统结果不同的只有浮点误差一类，逐条列出。
- 状态与证据：未开始。
