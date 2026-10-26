# contracts 任务

模块说明：[contracts](../模块/contracts.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：无，按契约的样例验收（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-CT-1 后端类型与端口

- 归属与目标：实现 CT-02 的后端部分。
- 前置输入：开始前 T-AS-1；C01–C10 经用户确认。
- 负责范围：`backend/src/cost_platform/contracts/types.py`、`ports.py`；按 C08 重写已有草稿，删除 `backend/src/cost_platform/adapters/`（系统时钟和编号生成改由 T-AS-2 实现）。替代实现属于 T-CT-3。
- 交付物：类型和端口代码；样例测试 `backend/tests/contracts/test_samples.py`。
- 接入责任：供全部后端模块使用；不含接线。
- 验收标准：C02、C03、C05、C07、C09、C10 的每个 JSON 样例都能解析成类型，按 C01 第 1 节转回 JSON 后内容不变；C06 的每个样例和正文中的例子都能解析，内容不丢失；格式不合法的样例被拒绝；C04、C08 列出的端口和类型都有定义，字段、方法和类型注解与文档一致。
- 状态与证据：进行中（第二次复核后已修正，C06 中没写的默认值待用户决定）。模拟验证：`uv run pytest` 83 个全部通过，其中契约测试 70 个：C02、C03、C05、C06、C07、C09、C10 的 36 个样例解析后再转回 JSON 内容不变；30 个格式不合法的样例都被拒绝；错误码与 HTTP 状态的对应、内容摘要、C04 和 C08 代码块中出现的 59 个类型和端口名都已定义（`.reports/T-CT-1/pytest.txt`）；删掉其中一个类型后这项测试失败（`.reports/T-CT-1/probe-missing-type.txt`）；`uv run lint-imports` 2 条规则都保持（`.reports/T-CT-1/lint-imports.txt`）。旧草稿和 `backend/src/cost_platform/adapters/` 已删除。C09 审批详情的样例补上了正文要求的 `source`。实现中发现的契约缺口列在 C05、C07、C08、C09 末尾的"待确认"中，暂按现有定义实现。复核后修正（2026-10-26）：复核记录 `.reports/review/T-CT-1.md`（结论 NEEDS_CHANGES）。外部数据改为经 `parse_wire` 解析、经 `dump_wire` 输出：只认 camelCase 字段名，整数和是非用严格类型，日期和日期时间按 C01 第 4 节的格式；输出时可选字段没有值时省略，写明为 null 的字段总是出现，样例测试改为按这种方式逐字段比较。删除行和写入行分成 `DeletedRow`、`ResultRow` 两个类型；命令和命令结果中样例总是出现的字段改为必填。去掉契约没有写的约束和取值范围（单表页没有明细、表单布局 24 列、审批流级别连续、冻结候选对象要有查找目标、规则的形状、`endRow` 不小于 `startRow`、受众至少一项、指纹格式、用户名非空、各列表至少一项、`ge` 范围等）：C06 第 10 节的校验归 config（T-CF-1），审批详情单元格数与列数一致归 T-AP-3，求值结果的 ok 与 error 搭配归 rules-core，指纹的格式归 T-AP-1。`approvalId`、`userId` 改为 C01 的十进制文本；`ImportReport.skipped` 按 C08 改为 list；`Origin` 只检查来源为审批时必须有 approval_id；`CommandState.outcome` 不再默认为 saved。测试补上：C02 主表新增、删除、只改明细三种命令，C07 两个行内结果，C09 表格中 26 个行内样例（"…"换成合法值），密码不会被输出，构造出的结果按样例形状输出；不合法样例增加到 49 个，覆盖 snake_case 字段名、字符串形式的整数和布尔、带时区或小数秒或时间戳的日期时间；C04、C08 代码块中每个类的字段名和每个方法的参数名都与实现逐项比较。结果：`uv run pytest` 194 个通过，其中 `test_samples.py` 123 个（`.reports/T-CT-1/pytest-2.txt`）；把 `IdGenerator.uuid` 改名、把 `ImportReport.skipped` 改名后，签名检查都失败（`probe-signatures.txt`）；`uv run lint-imports --no-cache` 2 条规则保持（`lint-imports-2.txt`）。待用户确认的事项列在 C01、C02、C05、C08、C09 和 contracts 模块说明末尾的"待确认"中。用户确认（2026-10-26，全部按建议）：C08 第 15 节的结构写进 C08 正文，C08 升为 v3，`ConfigImporter` 改为接收 `ConfigDraft`；C09 审批详情样例补的 `source` 确认，C09 升为 v3；C05 的 `erpRow`、C09 的 `flows` 没有值时省略；审批人通过时的人工参数放在审批命令的 `params.params`（C02 升为 v3）；输入输出方式写进 C01 第 1 节（C01 升为 v2）；C06 的数据结构归 contracts、第 10 节校验归 config，CT-02 和 T-CF-1 已改写，进出 JSON 的类型用 pydantic；之前记下的缺口都加上：C07（v2）计算结果和效果、C02 提示可用 `clientRowId` 定位新增行，C05（v2）的 Lookup 与 C06 写法相同，C03（v2）错误明细加 `configType`、`configKey`、`path`，C09 审批详情加 `params`。代码按新版契约修改，测试补上这些字段的样例和不合法样例。结果：`uv run pytest -v` 203 个通过（`.reports/T-CT-1/pytest-3.txt`），其中 `tests/contracts` 188 个；`uv run lint-imports --no-cache` 3 条规则保持（`lint-imports-3.txt`）。第二次复核（`.reports/review/T-CT-1-2.md`，不通过）后修正：删除行的 `deleted` 和求值结果的 `ok` 只接受 JSON 的布尔，不再把 `1`、`1.0` 当成 true；求值结果按 C07 第 3 节拆成计算结果、审批入口结果和失败结果三种形状，计算结果的 `rows`、`effects` 总会输出；C07 v2 的定位规则写进类型：求值请求的行和计算结果的行 `rowKey`、`clientRowId` 二者有且只有一个，提示和拒绝效果最多一个；审批详情从表的 `mergedColumns`、`targets` 只在候选单据的从表出现，为空数组时照常输出；错误明细补键时沿用默认的别名，`model_dump()` 不再输出两种键名；`Origin.approval_id` 去掉文档没有写的默认值。C09 审批详情样例是两个审批流合并的审批，来源单据的主表行补上 `flows`，正文写明来源单据的行总带 `flows`、候选单据的行省略（C09 仍为 v3，这次是同一版本内的样例修正）。T-CT-1 的前置输入和验收标准按 CT-02 改写，包含 C06；T-AS-2 的交付物和验收标准写明请求体经 `parse_wire` 解析、响应经 `dump_wire` 输出，并要求测试用 snake_case 字段名提交命令被拒绝。测试补上：C09 中用类型名占位的样例（登录、选角色、当前用户、账号列表、配置校验、按主键读行、待办列表、命令审查）、C10 另两种频道事件、C06 正文中的例子（ERP 行、必须审批、三种默认值、两种对比、数据项、按角色和按 SQL 的审批人、节点动作、人工参数、通知对象、逃生舱、Lookup 筛选、自定义 SQL 行权限），C06 写明的默认值，C04、C08 的规则，C04、C08 中每个类的字段类型、默认值和方法签名与文档逐项比较。结果：`uv run pytest -v` 271 个通过（`.reports/T-CT-1/pytest-4.txt`），`uv run lint-imports --no-cache` 3 条规则保持（`lint-imports-4.txt`）；复核者的 9 种没被发现的错误改动和本轮新加的 5 种，现在都会让测试失败，6 种对照改动也照样失败（`mutants.txt`，脚本 `mutants.py`）。没有处理：C06 模型中契约没写的默认值（复核问题 2）待用户决定；错误明细解析时 9 个字段可以省略，后端只输出错误体、很少解析，暂不收紧。

### T-CT-2 十进制文本与数值一致判定

- 归属与目标：实现 CT-01。
- 前置输入：开始前 T-AS-1、T-FS-1；C01 经用户确认。
- 负责范围：`backend/src/cost_platform/contracts/decimal_text.py`、`frontend/src/contracts/decimal-text.ts` 及其测试。Rust 版属于 T-RC-2。
- 交付物：两端的解析、格式化和数值一致判定函数。
- 接入责任：供全部模块使用；不含接线。
- 验收标准：C01 第 2、3 节的全部样例在两端结论相同；基于属性的测试（Hypothesis、fast-check）：任意合法十进制文本格式化后再解析数值相等，判定满足自反、对称、传递。
- 状态与证据：进行中（第二次复核后已修正，待第三次复核）。模拟验证：两端测试都直接读取 C01 的样例（3 个合法、6 个不合法、9 组判定），先写测试并确认因缺少实现而失败（`.reports/T-CT-2/red-pytest.txt`、`red-vitest.txt`；这两份红灯只是找不到被测模块导致的收集失败，测试文件在实现之后又改过，所以只能说明测试先于实现存在，测试能否发现错误的证据见下文的错误实现结果）。后端 `uv run pytest tests/contracts/test_decimal_text.py` 42 个通过（`pytest.txt`），前端 `pnpm test` 37 个通过（`vitest.txt`），都含格式化后再解析、与按 15 位小数向零截断的参考实现比较、第 15/16 位边界、自反、对称、传递的属性测试。3000 组随机样例由两端分别判定，结论和格式化结果 0 处不同（`cross-pairs.json`、`cross-compare.txt`）。把比较位数改成 14 后两端各有 2 个测试失败（`probe-14-places-*.txt`）。前端用 BigInt 表示十进制数，没有引入十进制库；新增开发依赖 vitest 5.0.5、fast-check 4.10.2。`pnpm typecheck`、`pnpm exec knip`、`pnpm build` 都通过，后端全部 125 个测试通过。复核后修正（2026-10-26）：复核记录 `.reports/review/T-CT-2.md`（结论 NEEDS_CHANGES）。补上跨越第 15 位截断边界的固定样例（如 `0.9999999999999999` 与 `1`）、跨边界数对的生成器和跨边界的传递链；往返测试改为与独立的规整写法逐字比较，加入超过 28 位的固定样例，生成器先抽长度再生成数字，保证产生长数；C01 第 2 节"`1.50` 与 `1.5` 相等"也从文档读入；前端参考实现改为按整数除法截断，不再与被测实现同样按字符串截取。实现修正：一侧为空时也校验另一侧的格式；后端 `Decimal("0E+3")` 格式化为 `0`；前端 `isDecimalText` 改为返回 boolean，避免把不合法的字符串收窄成 null。结果：后端 57 个通过（`.reports/T-CT-2/pytest-2.txt`），前端 50 个通过（`vitest-2.txt`）；复核者的错误实现（差值容忍、四舍五入、截断为零加差值容忍、按 28 位舍入的解析）在后端分别有 9、11、7、4 个测试失败（`probe-mutants-pytest.txt`），前端的差值容忍和截断为零加差值容忍分别有 9、7 个失败（`probe-mutants-vitest.txt`）；跨端比较脚本已修正路径并与样例生成脚本、14 位探针脚本一起存进 `.reports/T-CT-2/cross/`，重跑 3000 组 0 处不同（`cross-compare-2.txt`）；`pnpm typecheck`、`pnpm exec knip` 通过（`typecheck-2.txt`、`knip-2.txt`）。待用户决定：C01 写"前端用十进制库"，实现用 BigInt；新增的 vitest、fast-check 和 `test` 脚本改动了归 assembly 维护的 `frontend/package.json`。用户确认（2026-10-26）：前端用 BigInt 表示十进制数，C01 第 2 节已改写（C01 升为 v2）；前端的单元和契约测试用 vitest 和 fast-check，命令 `pnpm test`，已写进工程约定第 1 节。C01 改动后两端测试仍从文档读到同一批样例：后端 57 个通过（`.reports/T-CT-2/pytest-3.txt`），前端 50 个通过（`vitest-3.txt`）。第二次复核（`.reports/review/T-CT-2-2.md`）后修正：两端补上正负号相反的固定样例（`-0.5` 与 `0.5`、`-0.000000000000001` 与 `0.000000000000001`）和随机取反的数对，补上超过 28 位有效数字的判定样例（末位不同的 41 位整数、30 位整数的小数第 15、16 位），近邻数对改为可改整数部分或任一位小数、整数部分先抽长度（最长 45 位），补上 12 个 C01 之外的不合法写法（换行、非 ASCII 数字、空串、只有符号、下划线、首尾空格）。实现没有改动。结果：后端 76 个通过（`.reports/T-CT-2/pytest-4.txt`），前端 69 个通过（`vitest-4.txt`）。复核者的全部错误实现在新测试上每次运行都被发现：后端 11 种（含第二次复核新写的正负号、28 位截断判定、`\d` 正则、`re.match` 加 `$`）各 10 个种子全部失败（`probe-mutants-pytest-2.txt`），前端 10 种（含正负号、28 位截断判定、`m` 标志）各 10 次全部失败（`probe-mutants-vitest-2.txt`）；第一次复核时前端对照运行（none）的退出码 1 是首轮复核的变体模块不认识 `none` 造成的，与实现无关。14 位探针：后端 7 个失败（`probe-14-places-pytest-2.txt`，命令 `cd backend; uv run python ../.reports/T-CT-2/cross/probe_14_places.py`），前端 8 个失败（`probe-14-places-vitest-2.txt`，用 `cross/vitest.places14.config.ts` 把被测模块换成比较位数为 14 的副本 `cross/decimal-text.places14.ts`）。跨端比较的命令写进了输出（`cross-compare-3.txt`：先 `uv run --no-project python .reports/T-CT-2/cross/make_pairs.py` 生成样例，再在 frontend 下 `pnpm exec tsx ../.reports/T-CT-2/cross/compare.ts`），3000 组 0 处不同。

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
