# authz

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：按执行上下文中的角色配置（[C06](../契约/C06-配置模型.md) 第 8 节）判断页面访问权限和按钮权限（格式同旧系统的 BUTTON_POLICY）；给出字段的写权限；把行权限转成带绑定变量的 SQL 条件；实现"操作权限"管道阶段。
- 不负责：三层叠加（config 生成页面视图时完成）；执行行权限 SQL（由查询方和 write-pipeline 执行）；审批处理人的判断（approval）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/authz/` |
| 数据、配置、状态 | 无，只读执行上下文中的配置快照 |

## 3. 对外契约

提供 `PermissionChecker` 和"操作权限"阶段（[C08](../契约/C08-后端端口.md) 第 6、7 节）。

- AZ-01：在"操作权限"阶段按角色的 `buttons`（C06 第 8 节）检查命令：页面保存需要 `system:save`；Patch 中有新增行需要 `system:addRow` 或该区域的 `copyRow`；有删除需要 `system:deleteRow`；按钮操作需要引用该操作的按钮键。缺任一项抛 403 PERMISSION_DENIED。审批处理操作（`approval.*`）的处理人由 approval 判断，这里只确认用户已登录并选定了角色。
- AZ-06：`can_export` 判断角色能否使用某个导出配置（`export:<编码>` 或 `*`）。
- AZ-02：角色配置中没有该页面时，不能访问该页面的页面视图、列表、单据和导出。
- AZ-03：`row_condition` 把角色在该页面的 `rows` 转成 SQL 条件：可视化写法取其 `sql`，自定义写法取整个字符串；`${userId}`、`${username}` 换成绑定变量。没有 `rows` 时返回 None，表示可以访问全部行。行权限只作用于主表，明细随主表。
- AZ-04：`writable_fields` 返回页面视图中可编辑的字段，不含计算字段和 `erpRow.column`；没有 `erpRow` 的实体也不含 ERP 列。ERP 行上的 ERP 列由 write-pipeline 按行拒绝。
- AZ-05：来源为审批的写入，不检查行权限和 `writable_fields`。

## 4. 依赖

只依赖执行上下文（[C04](../契约/C04-执行上下文.md)）和配置快照中的页面视图、角色配置。

## 5. 内部流程

纯计算，不访问数据库：输入执行上下文和页面编码，输出判断结果或 SQL 条件。

## 6. 接入方式

- write-pipeline 调用"操作权限"阶段和 `writable_fields`、`row_condition`；queries-export 调用 `row_condition`。
- 真实联调：批次 B。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成。
- 本模块完成（模拟验证）：覆盖各种角色 `buttons` 下的保存、新增、复制、删除、按钮操作和导出判断（包括只有 `copyRow` 没有 `addRow` 时可以提交新增行）、可写字段，以及两种行权限写法的转换和绑定变量。
- 联调后才能确认：行权限条件在 Oracle 上筛出的行与预期一致（批次 B）。
