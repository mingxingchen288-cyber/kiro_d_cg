# rules-core

规则内核（[模块说明](../docs/模块/rules-core.md)，接口见 [C07](../docs/契约/C07-规则内核接口.md)）。一份 Rust 源码、一个 `Cargo.lock`，编出 Python 包和 wasm32-wasip1 产物。

## 1. 目录

| 路径 | 内容 |
|---|---|
| `core/` | 内核：规则包解析、依赖排序、组装输入、调用 zen-engine、解释结果；C01 判定的 Rust 实现（`decimal.rs`） |
| `bindings/python/` | Python 包 `cost_rules_core`（PyO3 + maturin），只做 JSON 文本进出 |
| `bindings/wasm/` | WASM 包装层（C 接口），只做 JSON 文本进出 |
| `web/src/` | `index.js`（WASM ES 模块，内含 WASI 适配）、`worker.js`、`client.js`（`createCalcWorkerClient`）和类型声明 |
| `web/test/` | 浏览器验证：静态服务器（COOP、COEP）、Playwright 配置和用例 |
| `fixtures/` | 样例集：`packs/` 规则包，`cases/` 成对的请求和期望结果；`gen_*.py`、`oracle.py` 生成它们 |
| `tests/cross_check.py` | 两端逐条比较 |
| `dist/` | 构建产物（不入库）：`python/*.whl`、`web/`（`rules_core.wasm` 和上面的脚本） |

## 2. JDM 约定（config 生成规则包时按这个写）

C07 的 `rules[]` 没有作用字段，rules-core 从 JDM 中取：

- 计算规则（`category` 为 `calc`）的 JDM 为 输入 → 表达式 → 输出 三个节点，表达式节点只有一个表达式，`key` 是作用的字段，`value` 是 ZEN 表达式。
- C06 第 5 节的 `when`、`branches` 编成一个条件表达式，不成立时取字段自己（字段不变）：
  - `when` + `expression`：`(when) ? (expression) : 字段`
  - `branches`：`(w1) ? (e1) : ((w2) ? (e2) : 字段)`，按顺序取第一个成立的分支；没有 `when` 的分支总是成立。
- 校验、界面规则（`category` 为 `validate`、`ui`）的表达式节点依次为：`matched`（条件，C06 第 5 节的 `when` 编成的表达式，为空时 `true`）、`field`（作用的字段，字符串常量；为空时不写，界面规则作用于整行）；校验另有 `level`（`'reject'` 或 `'prompt'`）、`message`；界面规则另有 `effect` 中写了的 `editable`、`required`（`true`/`false`）、`rowStyle`、`cellStyle`（样式对象的 JSON 文本，作字符串常量）。除 `matched` 外都是常量，`load_pack` 时求出。例如 `[("matched", "PER_HL <= 0"), ("field", "'PER_HL'"), ("level", "'reject'"), ("message", "'每片含量必填且必须大于0'")]`。
- ZEN 的字符串常量没有转义，到下一个同样的引号为止；含单引号的文字用双引号括起。
- 取值（RC-08）：明细规则对每行求值，本行字段直接写，主表字段写 `master.字段`；主表规则对单据求值一次，明细写实体编码，值是行的数组，例如 `sum(map(filter(COST_MATERIAL, #.DTL_USEFLAG == '原料'), #.COST_BATCH))`。另有 `old`、`context`、`data`。
- `packId` 是主表实体的编码。
- 只允许输入、输出、表达式、决策表、Switch 五种节点，函数节点等在 `load_pack` 时拒绝（RC-02）。

依赖（RC-09）：从表达式中的名称算出。明细规则引用 `master.X` 依赖算 X 的主表规则；主表规则引用明细实体编码时，依赖这个明细里算 `#.Y` 中各字段的规则。没有依赖时按 `order`、规则编码排序；成环时 `load_pack` 返回 PACK_INVALID，列出环上的规则。

数值处理（模块说明第 8 节）：数值字段为空或缺失时按 0；除以 0（结果为 null，或之后的运算出错且某个除数为 0）、溢出、没有行时的 `avg`/`max`/`min` 为 0，不出提示；其他求值出错为 0，并给出一条 `prompt`；条件求值出错按成立（计算规则的分支，以及校验、界面规则的 `matched`）；不舍入，输出去掉末尾的零。zen-engine 求值出错时不给原因，rules-core 这时对表达式逐段直接求值，取得原因再按上面判断。

校验和界面规则在全部计算规则之后执行，用计算后的最终值（C06 第 5 节执行顺序 3），按 `order`、规则编码排序；preview 执行三层，commit 只执行实体和操作规则。结果（C07 第 3 节）：

- 校验成立时在 `effects` 中给出 `{"kind": "reject" 或 "prompt", "rule", "message", "entity", "rowKey" 或 "clientRowId", "field"}`，规则没有作用字段时不写 `field`。每条规则对每行检查一次，按规则顺序、行在请求中的顺序排列。
- 界面规则成立时写到这一行：`editable`、`required` 在 `fields[字段]`，`rowStyle` 在 `style.row`，`cellStyle` 在 `style.cells[字段]`。`field` 为空时 `fields` 和 `cellStyle` 给到这个实体的每个字段。多条规则命中同一处时按执行顺序合并，后面的覆盖前面的同名属性。

## 3. 构建和验证

```powershell
pwsh -NoProfile -File tools/build-rules-core.ps1                       # 两个产物，--locked
cargo test -p rules-core --locked --manifest-path rules-core/Cargo.toml # 原生目标上跑样例集
# Python 包：在 backend 目录
uv run --with ..\rules-core\dist\python\cost_rules_core-0.1.0-cp313-cp313-win_amd64.whl pytest tests/rules_core
# 浏览器（本机 Chrome）
$env:NODE_PATH = 'D:\chonggou\kiro_d_cg\frontend\node_modules'
pnpm --dir D:\chonggou\kiro_d_cg\frontend exec playwright test -c D:\chonggou\kiro_d_cg\rules-core\web\test\playwright.config.cjs
```

WASM 依赖的 QuickJS（zen-engine 无条件依赖 rquickjs）是 C 代码，需要 wasi-sdk：构建脚本默认用 `%USERPROFILE%\.local\wasi-sdk\wasi-sdk-34.0`，并把其中的 `libclang.dll` 给 bindgen 用。

## 4. 调用

Python（C08 第 8 节）：

```python
from cost_rules_core import RulesEngine, PackInvalidError
engine = RulesEngine()
handle = engine.load_pack(pack_bytes)          # 不合法时抛 PackInvalidError
result_json = engine.evaluate(handle, request_json)
engine.core_version()
```

前端（C07 第 5 节、C11）：

```js
import { createCalcWorkerClient } from './dist/web/client.js'
const calc = createCalcWorkerClient('/rules-core/rules_core.wasm')
const handle = await calc.load({ packId: 'COST_PINGGU', version: 7, bytes })   // 同一 packId+version 只加载一次
const resultJson = await calc.evaluate(handle, requestJson)
```

页面需要 `Cross-Origin-Opener-Policy: same-origin` 和 `Cross-Origin-Embedder-Policy: require-corp` 响应头。
