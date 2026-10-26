# contracts 任务

模块说明：[contracts](../模块/contracts.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：无，按契约的样例验收（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-CT-1 后端类型与端口

- 归属与目标：实现 CT-02 的后端部分。
- 前置输入：开始前 T-AS-1；C02–C05、C07、C08 经用户确认（含文末待确认的补充）。
- 负责范围：`backend/src/cost_platform/contracts/types.py`、`ports.py`；按 C08 重写已有草稿，删除 `backend/src/cost_platform/adapters/`（系统时钟和编号生成改由 T-AS-2 实现）。替代实现属于 T-CT-3。
- 交付物：类型和端口代码；样例测试 `backend/tests/contracts/test_samples.py`。
- 接入责任：供全部后端模块使用；不含接线。
- 验收标准：C02、C05、C07、C09 的每个 JSON 样例都能解析成类型再转回 JSON，内容不变；格式不合法的样例被拒绝；C08 列出的端口和类型都有定义。
- 状态与证据：进行中（验收已通过，待独立复核）。模拟验证：`uv run pytest` 83 个全部通过，其中契约测试 70 个：C02、C03、C05、C06、C07、C09、C10 的 36 个样例解析后再转回 JSON 内容不变；30 个格式不合法的样例都被拒绝；错误码与 HTTP 状态的对应、内容摘要、C04 和 C08 代码块中出现的 59 个类型和端口名都已定义（`.reports/T-CT-1/pytest.txt`）；删掉其中一个类型后这项测试失败（`.reports/T-CT-1/probe-missing-type.txt`）；`uv run lint-imports` 2 条规则都保持（`.reports/T-CT-1/lint-imports.txt`）。旧草稿和 `backend/src/cost_platform/adapters/` 已删除。C09 审批详情的样例补上了正文要求的 `source`。实现中发现的契约缺口列在 C05、C07、C08、C09 末尾的"待确认"中，暂按现有定义实现。

### T-CT-2 十进制文本与数值一致判定

- 归属与目标：实现 CT-01。
- 前置输入：开始前 T-AS-1、T-FS-1；C01 经用户确认。
- 负责范围：`backend/src/cost_platform/contracts/decimal_text.py`、`frontend/src/contracts/decimal-text.ts` 及其测试。Rust 版属于 T-RC-2。
- 交付物：两端的解析、格式化和数值一致判定函数。
- 接入责任：供全部模块使用；不含接线。
- 验收标准：C01 第 2、3 节的全部样例在两端结论相同；基于属性的测试（Hypothesis、fast-check）：任意合法十进制文本格式化后再解析数值相等，判定满足自反、对称、传递。
- 状态与证据：进行中（验收已通过，待独立复核）。模拟验证：两端测试都直接读取 C01 的样例（3 个合法、6 个不合法、9 组判定），先写测试并确认因缺少实现而失败（`.reports/T-CT-2/red-pytest.txt`、`red-vitest.txt`）。后端 `uv run pytest tests/contracts/test_decimal_text.py` 42 个通过（`pytest.txt`），前端 `pnpm test` 37 个通过（`vitest.txt`），都含格式化后再解析、与按 15 位小数向零截断的参考实现比较、第 15/16 位边界、自反、对称、传递的属性测试。3000 组随机样例由两端分别判定，结论和格式化结果 0 处不同（`cross-pairs.json`、`cross-compare.txt`）。把比较位数改成 14 后两端各有 2 个测试失败（`probe-14-places-*.txt`）。前端用 BigInt 表示十进制数，没有引入十进制库；新增开发依赖 vitest 5.0.5、fast-check 4.10.2。`pnpm typecheck`、`pnpm exec knip`、`pnpm build` 都通过，后端全部 125 个测试通过。

### T-CT-3 后端替代实现与契约测试

- 归属与目标：实现 CT-03、CT-05。
- 前置输入：开始前 T-CT-1。
- 负责范围：`backend/src/cost_platform/contracts/fakes/`、`backend/tests/contracts/`。
- 交付物：C08 每个端口和管道阶段的内存替代实现，可以预设返回值和错误；每个端口一套契约测试 `test_<端口名>.py`，被测实现以参数传入。
- 接入责任：各模块用替代实现开发；各提供方的真实实现运行同一套测试。
- 验收标准：全部替代实现通过各自的契约测试；用一个故意写错的实现运行契约测试，测试失败。
- 状态与证据：未开始。

### T-CT-4 前端类型与模拟实现

- 归属与目标：实现 CT-02 的前端部分和 CT-04。
- 前置输入：开始前 T-FS-1；C01–C03、C05、C07、C09–C11 经用户确认。
- 负责范围：`frontend/src/contracts/`、`frontend/tests/contracts/`。
- 交付物：TypeScript 类型；C09 每个接口的模拟实现（返回 C09 的样例）；计算 Worker、`ShellApi` 的模拟实现；实时事件的模拟发送器。
- 接入责任：供全部前端模块开发和测试使用。
- 验收标准：C02、C05、C07、C09、C10 的每个样例都能被类型无损解析；每个 C09 接口的模拟实现都能调用并返回样例；与 T-CT-1 用同一批样例核对，字段名一致。
- 状态与证据：未开始。
