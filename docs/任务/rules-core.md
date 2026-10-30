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
- 交付物：C07 的完整实现（preview 和 commit 阶段，计算、校验、界面规则，出错处理；审批流的入口条件是 SQL，由 approval 执行，不在 rules-core 中，C07 v4）；C01 判定的 Rust 实现；Python 包 `cost_rules_core`；`rules-core/dist/web/`：WASM ES 模块、Worker 脚本和 `createCalcWorkerClient`；覆盖每种规则和每种错误的样例集。
- 接入责任：后端由 T-AS-5 注入 write-pipeline、approval、config；前端由 T-AS-3 创建 Worker 客户端实例，T-AS-7 联调。
- 验收标准：样例集在两个产物上全部通过且结果一致，浏览器中经 `createCalcWorkerClient` 运行（Playwright、Chromium）；proptest：同一请求求值两次结果相同，上游结果按全部精度参与下游计算（例如 1/3 再乘 3，结果与按 28 位有效数字计算的值一致，不因中间舍入改变）；同一规则包重复求值不重新编译；跨实体依赖（明细引用主表、主表汇总明细）一次求值得到最终值，与按依赖顺序逐条手算的结果相同；依赖成环的规则包 `load_pack` 返回 `PACK_INVALID`（Python 包中抛 C08 第 8 节的 `PackInvalidError`）；`old` 只给出改过的字段时，其余字段的 `old` 等于当前值；Python 包通过 `RulesEngine` 的契约测试（C08 第 14 节）。
- 状态与证据：待联调（T-AS-7）。自身的验收标准已满足；完成前的独立复核待做（`.reports/review/T-RC-2.md`）。计算部分（用户 2026-10-28 指定的范围）：`load_pack`、`evaluate`、`core_version`，`calc` 规则的单个表达式、`branches`、`master.字段`、主表汇总明细（含按条件求和）、依赖排序和成环检查、preview 和 commit 两个阶段，第 8 节的数值处理；Python 包 `cost_rules_core` 和 `rules-core/dist/web/`（WASM、`index.js`、`worker.js`、`createCalcWorkerClient`）已交付。校验、界面规则（2026-10-30）：计算规则全部执行完后，按 order、规则编码执行；校验成立时给出 reject 或 prompt，定位到实体、行和字段；界面规则写进行结果的 `fields`（editable、required）和 `style`（row、cells），field 为空时作用于整行；写法见 `rules-core/README.md` 第 2 节。没有样例的错误：`EVAL_FAILED`（只在内核 panic 时出现），按工程约定第 5 节上线后再补。
  - 计算带出变化按保存后的值判断（2026-10-30，C07 v8、RC-10，worktree `batch4/rules-approval`，输出在 `.reports/batch4-20261030/ra-rules-approval/`）：计算不舍入（RC-04），保存按 WP-15 最多 8 位小数，算出超过 8 位小数的行每次重算都与库里的 8 位值不同，被当成有修改去校验，后端却不会写它；旧系统按字段精度舍入，不会这样。现在 `eval.rs` 的 `calc_changed` 先把算出的数值按 WP-15 的写法（`decimal::stored`：最多 8 位，`MidpointAwayFromZero`，与后端 `ROUND_HALF_UP` 相同）处理再与 `old` 比较，`old` 和 `computed` 都不处理。列定义了更小小数位的情况 rules-core 不知道，按 8 位；d_cg 和 cmx 中定义了小数位的数值列只有主键、外键和标记列（`NUMBER(p,0)`，`q01-数值列小数位.out.txt`），计算字段的列都没有。新增样例 34、35（preview、commit）：d_cg 单据 2712，明胶空心胶囊每片含量假设为 0、单价假设为 18.3333333333，库里每批成本 36.66666667；只改硬脂酸镁的单价 63 → 64，胶囊每批成本算出 36.6666666666，不算变化，没有拒绝。改代码前这两个样例失败（被"每片含量必填且必须大于0"拒绝），原有 01–33 的结果不变。后端 `tests/config/test_packs.py` 用 seed 生成的规则包对 34、35 算出相同结果；`tests/pipeline/test_validate_changed_rows.py` 加一个页面保存的测试（2712 只改硬脂酸镁的单价，保存成功、104679 不写）。
    - 构建（`build-1.log`、`build-1-metrics.json`）：两个产物重建，`Cargo.lock` 前后 SHA256 相同；Python 208.1 秒、wheel 9,514,804 字节，WASM 108.5 秒、`rules_core.wasm` 13,078,959 字节。
    - 原生 `cargo test`：单元 3 passed，样例集 37 个全部通过（`cargo-test-2.log`）；浏览器 `run-browser.ps1` 38 passed（`playwright-1.log`）；Python 包 `run-python.ps1` 55 passed，两端 37 个样例按 C01 一致 37、逐字节相同 37（`python-2.log`、`python-results-2.json`；第一次 `python-1.log` 用的是 uv 缓存里的旧 wheel，加 `--refresh-package cost-rules-core` 后重跑）。
    - 后端：规则相关 86 passed（`pytest-rules-1.log`）；非真实库全量 1232 passed、180 deselected（`pytest-all-1.log`）；`lint-imports` 5 kept、0 broken（`lint-imports-1.log`）。前端代码没有改。
  - 计算带出变化的行也校验（2026-10-30，C07 v7、RC-10，worktree `batch3/rules-dirty`，输出在 `.reports/batch3-20261030/h1-rules-dirty/`）：按旧系统 `useCalcBroadcast.ts`（第 382、418、466、548、565 行把计算带出的变化用 `markFieldChange(…, 'calc')` 记成修改）和 `useWorkingSetStore.ts`（第 178–196 行新值等于原值时去掉这一列、行没有列了不算修改，第 886–934 行保存时校验有修改、没有删除的行），校验规则检查的行 = `changed` 中新增、修改的行 ∪ 计算后有计算字段的值与 `old` 不同的行（按 C01 第 3 节判定一致即没有变化），删除的行不检查，主表同样。原有样例 01–29 的结果不变；新增 30–33：d_cg 单据 2712 只改批量（20000 → 30000），明胶空心胶囊的每批数量 2 → 3，它的每片含量假设为 0（d_cg 中是 100，d_cg 没有每片含量不大于 0 的胶囊行），拒绝"每片含量必填且必须大于0"；d_cg 单据 2757 只改批量（1600000 → 1700000），30%过氧化氢溶液的每批数量仍是 0、不检查，能保存；preview 和 commit 各一个。后端 `tests/pipeline/test_validate_changed_rows.py` 加两个页面保存只改批量的测试（前者 422 RULE_REJECTED 定位到 104679 的 PER_HL、不写库，后者保存成功、207577 不写）；`tests/config/test_packs.py` 用 seed 生成的规则包对 30–33 算出相同结果。
    - 构建（`build-1.log`）：两个产物重建，`Cargo.lock` 前后 SHA256 相同；Python 213.1 秒、wheel 9,515,409 字节，WASM 122.0 秒、`rules_core.wasm` 13,078,776 字节。
    - 原生 `cargo test`：单元 3 passed，样例集 35 个全部通过（`cargo-test-2.log`）；浏览器 `run-browser.ps1` 36 passed（`playwright-1.log`）；Python 包 `run-python.ps1` 53 passed，两端 35 个样例按 C01 一致 35、逐字节相同 35（`python-1.log`、`python-results-1.json`）。
    - 后端：规则相关 72 passed（`pytest-rules.log`）；非真实库全量 1217 passed、174 deselected（`pytest-all.log`）；`lint-imports` 5 kept、0 broken（`lint-imports.log`）。前端代码没有改，`pnpm typecheck` 通过，`pnpm test` 33 个文件 516 passed。
    - 真实浏览器（后端 8084 + d_cg、前端 9532，`e2e/`，2 passed）：2758（与 2757 同一产品）只改批量 1600000 → 1700000，预览的 `changed` 只有主表、`old` 为 1600000，硬脂酸镁每批数量 0.51，30%过氧化氢溶液每批数量仍是 0，没有拒绝（没有保存）；再改过氧化氢溶液的单价为 12，预览拒绝"每片含量必填且必须大于0"，点保存后端 422 RULE_REJECTED 定位到 207590 的 PER_HL。2712 用 Playwright 拦截明细的 GET 响应、只在浏览器里把明胶空心胶囊的每片含量改成 0（模拟数据，数据库里是 100），并拦截全部命令请求；只改批量 20000 → 30000，胶囊每批数量 3，预览拒绝"每片含量必填且必须大于0"，没有点保存（数据库里没有这样的数据，保存的拒绝只在后端测试中验证）。验证前后只读查询 2712、2758 的主表和明细逐行相同，12:00 以后没有新审批、没有冻结（`05-浏览器验证前.out.txt`、`06-浏览器验证后.out.txt`）。
  - 显示求值（2026-10-30，C07 v6 第 3.1 节、RC-11，worktree `batch2/rules-ui`，输出在 `.reports/batch2-20261030/g1-rules-ui/`）：由旧系统 `usePageRules.ts` 的 `buildRowStyleCallback`（GRID_STYLE 在渲染行时按行数据算样式，加载即显示）推出，`purpose` 为 `display` 时不计算、不校验，只执行 preview 会选中的界面规则，值按请求原样，`computed`、`effects` 为空；`phase` 不是 preview 时 INPUT_INVALID；主表界面规则引用请求中没有给出的明细时不出结论（`load_pack` 时记下引用的明细）。三个函数、Python 包和 WASM 的导出、`web/src` 的 Worker 和客户端都不用改（请求和结果仍是 JSON 文本）。新增样例 25–29：d_cg 单据 2919 的主表列表和带明细（红底、computed 为空、两行每片含量为空也没有拒绝），规则包 `display-demo.json` 的三例（不给明细时"没有明细时黄底"不出结论、给了明细时出结论并与"停用变灰"合并、明细数量 ≤ 0 时必填标红但不拒绝、TOTAL 不重算）。
    - 构建（`build-2.log`、`build-2-metrics.json`）：两个产物重建，`Cargo.lock` 前后 SHA256 相同；`rules_core.wasm` 13,076,466 字节。
    - 原生 `cargo test`：单元 3 passed，样例集 31 个全部通过（`cargo-test-2.log`）；浏览器 `run-browser.ps1` 32 passed（31 个样例和跨源隔离检查，`playwright-2.log`）；Python 包 `run-python.ps1` 49 passed，两端 31 个样例按 C01 一致 31、逐字节相同 31（`python-2.log`、`python-results-2.json`）。
    - 后端：rules_core、config/test_packs、pipeline/test_validate_changed_rows、contracts/test_samples（C07 第 3.1 节的两个代码块按 `EvaluationRequest`、`EvaluationResult` 解析）、contracts/test_rules_engine 261 passed（`pytest-task2.log`）；非真实库全量 1205 passed、161 deselected（`pytest-all-2.log`）；`lint-imports` 5 kept、0 broken（`lint-imports.log`）。
  - 校验只检查本次新增、修改的行（2026-10-30，C07 v5、RC-10，worktree `batch2/rules-ui`，输出在 `.reports/batch2-20261030/g1-rules-ui/`）：按旧系统 `useWorkingSetStore.ts` 第 886–934 行（保存时只校验有修改、没有删除的行），校验规则只对请求 `changed` 中 `add`、`modify` 的行执行，主表行也一样；计算、界面规则不变。样例 17、18（2919）只剩本次修改的一水乳糖的两条拒绝；20 的主表行标为修改；新增 21–24：d_cg 单据 2757（"30%过氧化氢溶液"每片含量为 0），改硬脂酸镁的单价没有拒绝，改过氧化氢溶液的单价拒绝"每片含量必填且必须大于0"，preview 和 commit 各一个。后端 `tests/pipeline/test_validate_changed_rows.py`：页面保存经 write-pipeline、真实 wheel 和 seed 规则，前者保存成功、changed 只有 207584，后者 422 RULE_REJECTED 定位到 207577 的 PER_HL、不写库；`tests/config/test_packs.py` 用 seed 生成的规则包对 21–24 算出相同结果。
    - 构建 `tools/build-rules-core.ps1`：Python 包 wheel、WASM 都重建，`Cargo.lock` 前后 SHA256 相同（`build-1.log`、`build-1-metrics.json`）。
    - 原生 `cargo test`：单元 3 passed，样例集 26 个全部通过（`cargo-test-1.log`）；浏览器 `run-browser.ps1` 27 passed（`playwright-1.log`）；Python 包 `run-python.ps1` 44 passed，两端 26 个样例按 C01 一致 26、逐字节相同 26（`python-1.log`、`python-results-1.json`）。
    - 后端：上面两个文件和 `tests/rules_core` 57 passed（`pytest-task1.log`）；非真实库全量（不含当时因任务二改动未完成的 `tests/contracts/test_samples.py`）1010 passed、161 deselected（`pytest-all-1.log`）。
    - 真实浏览器（后端 8084 + d_cg，`e2e/`）：在 2757 上把硬脂酸镁的单价 54 改成 55 保存，没有被"每片含量"拒绝，但 d_cg 配了"成本明细改价审批"，保存提交了审批 29（2757 和物料 8289 被冻结，业务表没有写入，`03-保存后的审批.out.txt`），所以没能"改回再保存"；同一产品的 2758 上改 30%过氧化氢溶液（每片含量为 0）的单价，预览和保存都拒绝"每片含量必填且必须大于0"，没有写库、没有提交审批（`05-最终核对.out.txt`）。
  - 校验、界面规则和 T-RC-3 的验证（2026-10-30，worktree `batch1/rules-core`，输出在 `.reports/batch1-20261029/rules-core/`）：
    - 构建：`pwsh -NoProfile -File tools/build-rules-core.ps1`，Python 包 562.1 秒、wheel 9,501,526 字节；WASM 271.2 秒、`rules_core.wasm` 13,056,776 字节；`Cargo.lock` 前后 SHA256 相同，编译无警告（`build.log`）。
    - 原生：`cargo test -p rules-core --locked --manifest-path rules-core/Cargo.toml`，单元测试 3 passed，样例集 22 个全部通过，失败 0（`cargo-test.log`）。
    - 浏览器：`rules-core/web/test/run-browser.ps1`，23 passed、0 failed（22 个样例和 1 条跨源隔离检查；`playwright.log`、`browser-results.json`）。
    - Python 包：`rules-core/tests/run-python.ps1`，40 passed、0 failed（`python.log`）；两端 22 个样例按 C01 一致 22、不一致 0，逐字节相同 22，`core_version` 都是 0.1.0（`python-results.json`）。
    - 后端：在 backend 目录 `uv run --with <wheel> pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/rules_core tests/config tests/contracts/test_rules_engine.py tests/pipeline`，287 passed（`pytest-rules.log`）；同一命令不带路径（非真实库全量）1183 passed、157 deselected、失败 0（`pytest-all.log`）。
    - 前端：`pnpm typecheck` 通过；`pnpm test` 29 个文件 495 passed（`frontend-typecheck.log`、`frontend-test.log`）。
    - 新样例：17、18 为 d_cg 单据 2919（MEMO 为 ERP未搭建BOM，两行原辅料的每片含量为空）在 preview 和 commit 的两条校验拒绝和整行红底（红底只在 preview）；19 为界面规则整行不可编辑、单价必填和单元格样式；20 为 T-RC-3。seed 的三条规则（`backend/seed/config/rule.R_MAT_PER_HL_GT0.json`、`rule.R_MAT_PRICE_GE0.json`、`rule.R_MASTER_NO_BOM_RED.json`）经 config 生成的规则包对 17、18 算出相同结果（`tests/config/test_packs.py`），JDM 与样例集的规则包逐个相同（`tests/config/test_packs_jdm.py`）。
  - C07 v4 复验（2026-10-29）：去掉规则类别 `approvalTrigger`、规则包的 `approvalEntries`、求值目的 `approvalEntry`，删去样例"审批入口-以后实现"，样例集 18 个；重新生成 `fixtures/`，`tools/build-rules-core.ps1` 重建两个产物（`Cargo.lock` 前后 SHA256 相同，编译无警告）。输出在 `.reports/rc-c07v4/`：
    - 原生：`cargo test -p rules-core --locked`，单元测试 2 passed，样例集测试 1 passed（遍历 `fixtures/cases/` 全部 18 个），失败 0（`cargo-test.log`）。
    - 浏览器：`run-browser.ps1`，19 passed、0 failed（18 个样例和 1 条跨源隔离检查；`playwright.log`、`browser-results.json`）。
    - Python 包：`run-python.ps1`，36 passed、0 failed：契约测试 8 条、样例 16 条、C01 边界样例 9 条、依赖成环、重复求值不重新编译、性质测试（`python.log`）。
    - 两端：18 个样例按 C01 一致 18、不一致 0，逐字节相同 18，`core_version` 都是 0.1.0（`python-results.json`）。
    - 求值耗时：单据 200726，Python 1.33 毫秒，浏览器经 Worker 2.55 毫秒、主线程直接调用 1.63 毫秒（各 200 次平均）。
  - 真实验证（2026-10-28，C07 v3，与 T-RC-1 同一次 `.reports/T-RC-2/verify-all.ps1`）：
    - 原生：`cargo test -p rules-core --locked`，单元测试 2 passed，样例集 19 个全部通过，失败 0（`.reports/T-RC-2/cargo-test.log`）。
    - 浏览器：`rules-core/web/test/run-browser.ps1`，样例经 `createCalcWorkerClient` 在 Worker 中运行，20 passed、0 failed（19 个样例和 1 条跨源隔离检查；`playwright.log`、`browser-results.json`）。
    - Python 包：`rules-core/tests/run-python.ps1`（在 backend 目录 `uv run --with <wheel> pytest tests/rules_core`），38 passed、0 failed：`RulesEngine` 契约测试 9 条、样例 17 条、C01 边界样例 9 条、依赖成环抛 `PackInvalidError`、重复求值不重新编译、性质测试（Hypothesis 200 例，作用同 proptest：同一请求两次结果相同；QTY/3 再乘 3 等与逐步按 28 位有效数字计算的值相同）（`python.log`）。
    - 两端：`rules-core/tests/cross_check.py`，19 个样例按 C01 一致 19、不一致 0，逐字节相同 19，`core_version` 相同（`python-results.json`）。
    - 样例覆盖：E02（preview 和 commit 结果相同）、E03、E04（正负数都不舍入）；cmx 单据 200726 的 11 条真实明细，重算的 BATCH_QTY、COST_BATCH 与 cmx 虚拟列相同，主表 13 个计算字段按用户公式；新增行计入、删除行不计入汇总；胶囊和中盒分支；分支都不匹配保持原值（cmx 200203 的"PVC 250μm"）；`old` 只给出改过的字段；serverOnly 规则只在 commit 执行；审批入口（C07 v4 已删去）；INPUT_INVALID；跨实体依赖成环。期望值由 `rules-core/fixtures/oracle.py` 按用户公式逐步手算（每步按 28 位有效数字）。
    - 求值耗时：成本核算单据 200726（17 条计算规则、11 条明细），每次 Python 1.29 毫秒、浏览器经 Worker 2.26 毫秒、浏览器主线程直接调用 1.74 毫秒（各 200 次平均）。
  - 修正（2026-10-30）：zen-engine 表达式节点求值出错时只给"Failed to evaluate expression"，不带原因，原来按"Number overflow"判断溢出的写法因此不生效（之前没有溢出样例）；现在出错时对表达式逐段直接求值，取得原因后判断溢出、除以 0 和空数组。

### T-RC-3 数值处理规则表的样例

- 归属与目标：实现 rules-core 模块说明第 8 节。
- 前置输入：开始前 T-RC-1 通过。
- 负责范围：`rules-core/fixtures/` 中的样例；第 8 节的处理在 T-RC-2 的代码中实现。
- 交付物：第 8 节每一行至少一个样例，并附上旧系统前端计算引擎对同一输入的结果。
- 接入责任：样例供 T-RC-2 和 T-MG-3 的对账使用。
- 验收标准：每个样例在两个产物上通过；与旧系统结果不同的只有浮点误差一类，逐条列出。
- 状态与证据：进行中——样例和验证已完成，等独立复核（工程约定第 7 节，`.reports/review/T-RC-3.md`）后改为完成。
  - 样例：`rules-core/fixtures/cases/20-T-RC-3-数值处理规则表.json`（规则包 `fixtures/packs/numeric.json`），第 8 节每一行一条规则：空值和缺失字段按 0、除以 0 和 0/0 为 0、溢出为 0、求值出错为 0 并给出 prompt、条件出错按成立（计算规则和校验规则各一条）、汇总时空值按 0、没有行时 sum/count/avg/max/min 为 0、分支都不匹配保持原值、不舍入。已有样例另外覆盖：除以 0（04、08）、汇总没有行（06、07 的原辅料明细为空）、分支都不匹配（11）、不舍入（12、13）。
  - 旧系统结果：样例中的 `oldSystem`，2026-10-30 用 node 24 直接运行旧 `cost-web/src/v3/logic/calc-engine/calculator.ts`（mathjs 15.1.0）得到，脚本和原始输出在 `.reports/batch1-20261029/rules-core/old-engine/`（`run-old.mts`、`old-results.json`）。
  - 与旧系统不同的：① `5 / 3` 旧系统 1.6666666666666667、新平台 1.6666666666666666666666666667，浮点误差，按 C01 一致（Rust 版判定已核对）；② `1e28 * 10` 旧系统 1e29、新平台 0：浮点到 1.8e308 才溢出，新平台超出 28 位有效数字按第 8 节为 0，这一条不属于浮点误差，是两者能表示的范围不同。其余 12 个字段相同。求值出错时新平台另给一条 prompt，旧系统只在控制台告警。
  - 两个产物上的运行：同 T-RC-2 的 2026-10-30 验证（原生、浏览器、Python 包都通过，两端逐字节相同）。
