# 文档目录

- [架构与组装](架构与组装.md)
- [工程约定](工程约定.md)
- [业务例子](业务例子.md)
- [性能与冗余盘点](性能与冗余盘点.md)（2026-10-30，待处理）

## 契约

- [C01 数据格式](契约/C01-数据格式.md)
- [C02 命令与结果](契约/C02-命令与结果.md)
- [C03 错误](契约/C03-错误.md)
- [C04 执行上下文](契约/C04-执行上下文.md)
- [C05 页面视图](契约/C05-页面视图.md)
- [C06 配置模型](契约/C06-配置模型.md)
- [C07 规则内核接口](契约/C07-规则内核接口.md)
- [C08 后端端口](契约/C08-后端端口.md)
- [C09 HTTP 接口](契约/C09-HTTP接口.md)
- [C10 实时事件](契约/C10-实时事件.md)
- [C11 前端装载](契约/C11-前端装载.md)

## 模块

- 公共：[contracts](模块/contracts.md)、[rules-core](模块/rules-core.md)、[db-core](模块/db-core.md)
- 后端：[config](模块/config.md)、[identity](模块/identity.md)、[authz](模块/authz.md)、[write-pipeline](模块/write-pipeline.md)、[approval](模块/approval.md)、[operations](模块/operations.md)、[delivery](模块/delivery.md)、[realtime](模块/realtime.md)、[queries-export](模块/queries-export.md)、[migration](模块/migration.md)
- 前端：[frontend-shell](模块/frontend-shell.md)、[frontend-page](模块/frontend-page.md)、[frontend-config](模块/frontend-config.md)、[frontend-approval](模块/frontend-approval.md)、[frontend-admin](模块/frontend-admin.md)
- 组装：[assembly](模块/assembly.md)

## 任务

T-AS-1 和 T-FS-1 不依赖契约，可以最先开始；其余任务的分组和顺序见[架构第 11 节](架构与组装.md)。

- 公共：[contracts](任务/contracts.md)、[rules-core](任务/rules-core.md)、[db-core](任务/db-core.md)
- 后端：[config](任务/config.md)、[identity](任务/identity.md)、[authz](任务/authz.md)、[write-pipeline](任务/write-pipeline.md)、[approval](任务/approval.md)、[operations](任务/operations.md)、[delivery](任务/delivery.md)、[realtime](任务/realtime.md)、[queries-export](任务/queries-export.md)、[migration](任务/migration.md)
- 前端：[frontend-shell](任务/frontend-shell.md)、[frontend-page](任务/frontend-page.md)、[frontend-config](任务/frontend-config.md)、[frontend-approval](任务/frontend-approval.md)、[frontend-admin](任务/frontend-admin.md)
- 组装：[assembly](任务/assembly.md)
