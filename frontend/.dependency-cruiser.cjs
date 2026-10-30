/**
 * 前端依赖规则（架构第 3 节、C11），由 assembly 维护（AS-07）。`pnpm lint:deps` 检查，`pnpm build`、`pnpm build:test` 先检查再构建。
 *
 * 区域的划分：
 * - `src/modules/<名称>/`：前端业务模块 shell、page、config、approval、admin（C11 的 FrontendModule 和外壳）。
 * - `src/contracts/`：contracts。
 * - `src/main.ts`、`src/assembly/`：assembly。
 * - `src/` 下其他目录（store、router、service、layouts、views、components 等）是从旧前端复制来的外壳代码（T-FS-1），按 frontend-shell 对待。
 * - `../rules-core/`：rules-core，前端只用它交付的 `rules-core/dist/web/`。
 *
 * 已知的违反记在 `.dependency-cruiser-known-violations.json`（`--ignore-known` 跳过，输出中给出跳过的条数），只有一处：
 * 过渡视图 `src/views/page/[pageCode].vue` 导入 frontend-page。外壳启动时已按 C11 注册 frontend-page，这个视图运行时不再使用，
 * 删除它（连同 `src/service/shell.ts`）之后从这个文件中去掉。新出现的违反照样报错。
 * 模块发现用 `import.meta.glob`（`src/modules/shell/discover.ts`），不是静态导入，不在检查范围内。
 *
 * @type {import('dependency-cruiser').IConfiguration}
 */
module.exports = {
  forbidden: [
    {
      name: 'no-cross-module',
      comment: '前端模块之间不互相导入，跨模块跳转只用路由路径（C11；架构第 3 节第 1 条）',
      severity: 'error',
      from: { path: '^src/modules/([^/]+)/' },
      to: { path: '^src/modules/', pathNot: '^src/modules/$1/' }
    },
    {
      name: 'modules-only-contracts',
      comment: 'page、config、approval、admin 在 src 中只导入本模块和 contracts（架构第 3 节第 1 条）',
      severity: 'error',
      from: { path: '^src/modules/(page|config|approval|admin)/' },
      to: { path: '^src/', pathNot: '^src/(modules|contracts)/' }
    },
    {
      name: 'shell-not-to-modules',
      comment:
        '外壳代码不导入 page、config、approval、admin；只有 assembly 可以依赖业务模块（C11；架构第 3 节第 3 条）',
      severity: 'error',
      from: { path: '^src/', pathNot: '^src/(modules/|contracts/|assembly/|main\\.ts$)' },
      to: { path: '^src/modules/(page|config|approval|admin)/' }
    },
    {
      name: 'contracts-independent',
      comment: 'contracts 不依赖任何模块（架构第 3 节第 2 条）',
      severity: 'error',
      from: { path: '^src/contracts/' },
      to: { path: '^(src/|\\.\\./)', pathNot: '^src/contracts/' }
    },
    {
      name: 'rules-core-artifacts-only',
      comment: '前端只用 rules-core 交付的 rules-core/dist/web，不导入 rules-core 的源码（架构第 3 节第 5 条）',
      severity: 'error',
      from: {},
      to: { path: '^\\.\\./rules-core/', pathNot: '^\\.\\./rules-core/dist/web/' }
    },
    {
      name: 'rules-core-via-calc-client',
      comment:
        '计算客户端由 assembly 用 createCalcWorkerClient 创建（AS-06），模块经 ShellApi.calc 使用；' +
        '只有 assembly 和过渡的计算客户端 src/service/calc.ts 导入 rules-core/dist/web',
      severity: 'error',
      from: { pathNot: '^src/(assembly/|main\\.ts$|service/calc\\.ts$)' },
      to: { path: '^\\.\\./rules-core/' }
    }
  ],
  options: {
    doNotFollow: { path: 'node_modules' },
    tsConfig: { fileName: 'tsconfig.json' },
    // 只导入类型也算依赖
    tsPreCompilationDeps: true
  }
};
