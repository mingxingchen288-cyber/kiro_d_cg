# C09 HTTP 接口

版本：v8。维护：contracts。状态：已确认。v8 按用户 2026-10-28 的纠正，通过请求提交勾选的行（`checkedRows`）。v7 随 C06 v15 把审批详情的候选单据改为影响对象、按行勾选（用户 2026-10-28 确认审批流合并展示与动作）。

## 1. 通用规则

- 会话 Cookie 名为 `cp_session`，HttpOnly、SameSite=Lax。会话标识不出现在 URL 和响应体中。
- 写请求（POST、PUT、DELETE，登录除外）带 `X-CSRF-Token` 头，值取自登录响应或 `GET /api/me` 的 `csrfToken`。
- 每个响应带 `X-Config-Version` 头。
- 前端自动发起、不是用户操作直接引起的请求（例如配置变更后重新读取页面视图和规则包、读取未读通知数）带请求头 `X-Background-Request: 1`。会话只按用户自己的写入和查询请求顺延，这类请求不顺延会话。
- 列表的 `startRow` 包含在内，`endRow` 不包含。
- `/api/config/*` 和 `/api/admin/*` 只对管理员角色开放，其他角色返回 403 PERMISSION_DENIED。
- 数据格式见 [C01](C01-数据格式.md)，错误见 [C03](C03-错误.md)。
- 返回业务行时，行包含实体的全部字段，字段可见性由前端处理；查询、筛选、排序和高级查询只能使用可见字段，否则返回 422 VALIDATION_FAILED。

共用类型：

```ts
type CurrentUser = { userId: string; username: string; displayName: string; departmentId: string | null }
type RoleRef = { code: string; name: string; admin: boolean }
type Menu = { key: string; title: string; kind: 'group' | 'page' | 'config' | 'admin'; pageCode?: string; children?: Menu[] }
type DataRow = { rowKey: string; values: Record<string, string | boolean | null>; frozen: { approvalId: string } | null; compare?: Record<string, { value: string | null; diff: string | null; percent: string | null }> }
```

## 2. identity

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/auth/login` | `{"username": "admin", "password": "…"}` | `{"user": CurrentUser, "roles": [RoleRef], "selectedRole": RoleRef 或 null, "csrfToken": "…"}`。只有一个角色时自动选定；失败返回 401 LOGIN_FAILED |
| POST | `/api/auth/role` | `{"roleCode": "COST_ACCOUNTANT"}` | `{"selectedRole": RoleRef}`；角色不属于该账号时返回 403 PERMISSION_DENIED |
| POST | `/api/auth/logout` | 无 | 204 |
| GET | `/api/me` | 无 | `{"user": CurrentUser, "role": RoleRef 或 null, "menus": [Menu], "configVersion": 13, "csrfToken": "…"}` |
| GET | `/api/admin/accounts` | `?keyword=&startRow=0&endRow=50` | `{"rows": [Account], "total": 120}` |
| POST | `/api/admin/accounts` | `{"username": "zhangsan", "displayName": "张三", "departmentId": "10", "password": "…", "roleCodes": ["COST_ACCOUNTANT"]}` | `Account`；账号名重复时返回 422 VALIDATION_FAILED |
| PUT | `/api/admin/accounts/{userId}` | `{"displayName": "张三", "departmentId": "10", "roleCodes": [], "enabled": false}` | `Account`；停用或撤销角色后，该账号的会话立即失效 |
| POST | `/api/admin/accounts/{userId}/password` | `{"password": "…"}` | 204 |
| GET | `/api/admin/departments` | 无 | `{"items": [{"departmentId": "10", "name": "成本部", "parentId": null}]}` |

`Account` 为 `{"userId", "username", "displayName", "departmentId", "enabled", "roleCodes"}`。

## 3. config

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/pages/{pageCode}/view` | 无 | 页面视图（[C05](C05-页面视图.md)）；页面不存在返回 404，无权访问返回 403 |
| GET | `/api/rules-packs/{packId}/{version}` | 无 | 规则包（[C07](C07-规则内核接口.md) 第 1 节）。同一版本内容不变，可以长期缓存 |
| GET | `/api/config/items` | `?type=page` | `{"items": [{"type": "page", "key": "COST_PINGGU", "name": "成本核算", "version": 13, "updatedBy": "1", "updatedAt": "2026-10-24T10:00:00"}]}` |
| GET | `/api/config/items/{type}/{key}` | 无 | 配置项（[C06](C06-配置模型.md)） |
| PUT | `/api/config/items/{type}/{key}` | `{"name": "成本核算", "content": {}}` | `{"type": "page", "key": "COST_PINGGU", "version": 14}`。保存即生效；校验不通过返回 422 VALIDATION_FAILED，`details` 的 `configType`、`configKey`、`path` 给出配置项和位置（C03） |
| DELETE | `/api/config/items/{type}/{key}` | 无 | 204；仍被其他配置引用时返回 422 VALIDATION_FAILED |
| POST | `/api/config/validate` | `{"items": [配置项]}` | `{"ok": false, "errors": [C03 的 details 项]}`。只校验，不保存 |
| POST | `/api/config/wizard/columns` | `{"readView": "T_COST_GOODS_PRICE_V", "table": "T_COST_GOODS"}` | `{"primaryKey": "GOODSID", "sequence": {"name": "T_COST_GOODS_SEQ", "exists": true}, "columns": [{"name": "ZX_PRICE", "type": "number", "label": "执行价", "inTable": true}]}`；只读取结构，不写任何东西 |
| POST | `/api/config/wizard/generate` | `{"parentMenu": "cost", "pageCode": "GOODS_PRICE_MANAGE", "title": "物料清单及成本", "layout": "single", "detailMode": "tabs", "audit": true, "master": {实体}, "details": []}`。`audit`、`detailMode` 必须写，原样写入生成的页面（C06 第 3 节），单表页也要写 `detailMode` | 生成的实体、页面、页面的保存操作、菜单配置项，以及 ADMIN 角色的 `*` 权限，在一个事务中写入（config CF-14），任一项失败时全部不写；序列不存在时返回 422，提示用户先建序列 |

表单布局是页面配置的一部分，随 `PUT /api/config/items/page/{pageCode}` 保存。两个管理员同时编辑同一配置项时，后保存的覆盖先保存的。

## 4. queries-export

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/pages/{pageCode}/rows` | `ListRequest` | `{"rows": [DataRow], "total": 1234, "aggregates": {"TOTAL_COST": "98765.43"}}` |
| POST | `/api/pages/{pageCode}/rows/by-keys` | `{"entity": "COST_PINGGU", "rowKeys": ["1001", "1002"]}` | `{"rows": [DataRow]}`；不存在或超出行权限的行不返回 |
| GET | `/api/pages/{pageCode}/records/{recordKey}` | 无 | `{"master": DataRow, "details": {"COST_MATERIAL": [DataRow]}}`；不存在或超出行权限返回 404 |
| POST | `/api/lookups/{lookupCode}/search` | `{"keyword": "胶", "filter": {"column": "GOODSTYPE", "value": "瓶"}, "startRow": 0, "endRow": 50}`，`filter` 可选；`column` 必须是该 Lookup 的列，否则返回 422。`keyword` 去掉首尾空白后判断：该 Lookup 的 `keywordColumns` 为空而关键字不为空时，返回 400 INVALID_REQUEST（queries-export 的 QE-09） | `{"rows": [{"values": {"GOODSID": "115", "NAME": "胶囊壳"}}], "total": 3, "keywordSearch": true}`。`keywordSearch` 表示该 Lookup 是否支持关键字搜索（`keywordColumns` 不为空），为 false 时前端不显示搜索框 |
| GET | `/api/dicts/{dictType}` | 无 | `{"items": [{"value": "1", "label": "启用"}]}`；类型不存在时 `items` 为空 |
| GET | `/api/pages/{pageCode}/personal` | 无 | `PersonalConfig`；没有保存过时各项为空 |
| PUT | `/api/pages/{pageCode}/personal` | `PersonalConfig`，只含要替换的部分 | `PersonalConfig` |
| GET | `/api/pages/{pageCode}/exports` | 无 | `{"items": [{"exportCode": "cost-pinggu-export", "name": "物料成本核算表导出"}]}`，只含当前角色可用的导出配置 |
| POST | `/api/pages/{pageCode}/export` | 默认导出当前页面：`{"mode": "page", "request": ListRequest, "columns": ["DOCID", "GOODSNAME"]}`；按导出配置：`{"mode": "config", "exportCode": "cost-pinggu-export", "scope": "current", "request": ListRequest}`，`scope` 为 `current`（按当前查询条件）或 `all`（行权限内的全部行） | xlsx 文件，`Content-Disposition: attachment`，数值写成文本单元格；默认导出的列必须对当前角色可见；角色没有该导出配置时返回 403 |

```json
{
  "startRow": 0,
  "endRow": 100,
  "sortModel": [{"colId": "DOCID", "sort": "desc"}],
  "filterModel": {"GOODSNAME": {"filterType": "text", "type": "contains", "filter": "胶囊"}},
  "advanced": {"op": "and", "conditions": [{"field": "TOTAL_COST", "operator": ">=", "value": "100"}, {"entity": "COST_MATERIAL", "group": "g1", "field": "GOODSID", "operator": "=", "value": "115"}, {"entity": "COST_MATERIAL", "group": "g1", "logic": "and", "field": "PRICE", "operator": ">", "value": "3"}]}
}
```

`ListRequest` 的 `sortModel`、`filterModel` 沿用 AG Grid 服务端行模型的格式；没有排序时按主键排序。
高级查询的条件不写 `entity` 时属于主表。写了明细实体的条件，同一明细实体的条件合成一个 `EXISTS`，必须由同一条明细行同时满足，`group` 和 `logic` 用于组内的且、或；不同明细实体的条件之间是且。上例查的是"含有物料 115 且该行价格大于 3 的明细"的成本单。

```json
{
  "grids": {"master": {"columns": [{"field": "DOCID", "width": 120, "pinned": "left", "hide": false}]}, "COST_MATERIAL": {"columns": []}},
  "detailMode": "tabs"
}
```

`PersonalConfig` 的 `columns` 按数组顺序排列。

## 5. write-pipeline（由 assembly 挂载）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/commands` | 命令（[C02](C02-命令与结果.md)） | 命令结果（C02） |

## 6. approval

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/approvals` | `?box=todo` 或 `?box=mine`，以及 `startRow`、`endRow` | `{"rows": [ApprovalSummary], "total": 7}` |
| GET | `/api/approvals/{approvalId}` | 无 | `ApprovalDetail`；只读，不加锁 |
| POST | `/api/approvals/{approvalId}/pass` | `{"requestKey": "…", "fingerprint": "sha256:…", "checkedRows": [{"flow": "GOODS_TO_COST", "block": "costs", "entity": "COST_MATERIAL", "recordKey": "2550", "rowKeys": ["6101"]}], "comment": "价格已核对", "params": {"effectiveDate": "2026-11-01"}}`，`checkedRows` 为这次勾选的影响对象的行，`params` 为本次通过要填写的人工参数（C06 7.1） | 命令结果（C02），`outcome` 为 `approvalProcessed`；必填的人工参数没有填写时返回 422 |
| POST | `/api/approvals/{approvalId}/reject` | `{"requestKey": "…", "comment": "价格偏高"}`，`comment` 为驳回原因，必填 | 命令结果；没填原因返回 422 VALIDATION_FAILED |
| POST | `/api/approvals/{approvalId}/withdraw` | `{"requestKey": "…", "comment": "录入有误"}`，`comment` 可以不填 | 命令结果 |

```json
{"approvalId": "203", "page": "GOODS_PRICE_MANAGE", "pageTitle": "物料清单及成本", "operation": "COST_GOODS_PRICE.save", "operationLabel": "保存", "source": {"entity": "COST_GOODS_PRICE", "recordKey": "115", "label": "硬脂酸镁"}, "applicant": {"userId": "112", "displayName": "杨娜"}, "submittedAt": "2026-10-24T09:30:00", "status": "pending", "level": 1}
```

```json
{
  "approvalId": "203",
  "status": "pending",
  "page": "GOODS_PRICE_MANAGE",
  "pageTitle": "物料清单及成本",
  "operation": "COST_GOODS_PRICE.save",
  "operationLabel": "保存",
  "source": {"entity": "COST_GOODS_PRICE", "recordKey": "115", "label": "硬脂酸镁"},
  "applicant": {"userId": "112", "displayName": "杨娜"},
  "submittedAt": "2026-10-24T09:30:00",
  "currentLevel": 1,
  "steps": [
    {"level": 1, "flow": "GOODS_TO_COST", "flowName": "物料清单改价 → 勾选成本单", "entry": "逐成本单确认同步", "mode": "or", "status": "pending",
     "members": [{"type": "user", "id": "111", "name": "系统管理员", "status": "pending", "processedBy": null, "processedAt": null, "comment": null}]},
    {"level": 1, "flow": "GOODS_PRICE_AUDIT", "flowName": "物料改价复核", "entry": "采购复核", "mode": "or", "status": "pending",
     "members": [{"type": "user", "id": "111", "name": "系统管理员", "status": "pending", "processedBy": null, "processedAt": null, "comment": null}]},
    {"level": 2, "flow": "GOODS_PRICE_AUDIT", "flowName": "物料改价复核", "entry": "管理员复核", "mode": "or", "status": "upcoming",
     "members": [{"type": "role", "id": "ADMIN", "name": "系统管理员", "status": "pending", "processedBy": null, "processedAt": null, "comment": null}]}
  ],
  "view": {
    "master": {"columns": ["物料ID", "名称", "价格变化"],
      "rows": [{"op": "modify", "flows": ["GOODS_TO_COST", "GOODS_PRICE_AUDIT"], "cells": [{"before": "115", "after": "115"}, {"before": "硬脂酸镁", "after": "硬脂酸镁"}, {"before": "75", "after": "60"}]}]},
    "details": [],
    "affected": [{"flow": "GOODS_TO_COST", "key": "costs", "title": "受影响的成本单", "selection": "checked", "editable": true,
      "columns": ["单据号", "产品", "物料", "单价", "金额", "每盒成本", "千片加工费"],
      "rows": [
        {"op": "modify", "ref": {"entity": "COST_MATERIAL", "recordKey": "2550", "rowKeys": ["6101"]}, "checked": true, "cells": [{"before": "2550", "after": "2550"}, {"before": "250mg乙酰唑胺片", "after": "250mg乙酰唑胺片"}, {"before": "硬脂酸镁", "after": "硬脂酸镁"}, {"before": "75", "after": "60"}, {"before": "1500", "after": "1200"}, {"before": "1.2034", "after": "1.1987"}, {"before": "30.50", "after": "30.21"}]},
        {"op": "modify", "ref": {"entity": "COST_MATERIAL", "recordKey": "2551", "rowKeys": ["6102"]}, "checked": true, "cells": [{"before": "2551", "after": "2551"}, {"before": "500mg乙酰唑胺片", "after": "500mg乙酰唑胺片"}, {"before": "硬脂酸镁", "after": "硬脂酸镁"}, {"before": "75", "after": "60"}, {"before": "3000", "after": "2400"}, {"before": "0.9821", "after": "0.9790"}, {"before": "28.10", "after": "27.95"}]},
        {"op": "none", "missing": {"recordKey": null, "label": null}, "cells": [{"before": null, "after": null}, {"before": null, "after": null}, {"before": null, "after": null}, {"before": null, "after": null}, {"before": null, "after": null}, {"before": null, "after": null}, {"before": null, "after": null}]}
      ]}]
  },
  "fingerprint": "sha256:5b1e0c6d9a3f47e28b1c6d0e9f3a2b4c5d6e7f8091a2b3c4d5e6f708192a3b4c",
  "params": [],
  "actions": {"canPass": true, "canReject": true, "canWithdraw": false}
}
```

- 每个审批对应一张单据：主从页为一行主表及其明细，单表页为一行；一张单据命中多个审批流时合成一个审批（[approval](../模块/approval.md) AP-01、AP-09）。样例中的页面、物料、成本单、账号和角色取自旧系统的真实数据（经 d_cg 读取 CMX）；旧系统没有会同时命中同一张单据的两个审批流，`GOODS_PRICE_AUDIT` 是为说明合并展示假设的第二个审批流，C06 中没有定义。
- 待办列表每个审批一行（`ApprovalSummary`）。详情分主表和从表：
  - 主表：来自页面（`pageTitle`、`operationLabel`）、提交时间（`submittedAt`）、提交人（`applicant`）、来源单据号（`source.recordKey`）。新增的单据在提交审批时已取得主键（approval AP-02），来源单据号总是有值。
  - 从表：`steps`，每个入口一项，按级别、再按审批流的 `createdSeq` 排列；`flow`、`flowName` 标出入口来自哪个审批流。只列已进入的入口，以及按当前数据推算后面会进入的入口（approval AP-08）。`status` 取 `passed`、`pending`（本级待处理）、`rejected`、`upcoming`（还没到，按当前数据推算会进入）。`members[].status` 取 `pending`、`passed`、`rejected`；`processedBy` 为实际处理的账号（`{"userId", "displayName"}`），按角色配置的成员由该角色的某个账号处理。
- `view` 是按 C06 7.6 的 `display` 生成的"修改内容"：`master`、`details` 为来源单据的主表和明细，`affected` 为影响对象，每块一项，`selection` 为 `hidden` 的块不返回。`columns` 为列标题，`rows[].cells` 与列一一对应，每格给出 `before` 和 `after`，两者不同时前端显示为"A→B"，相同时只显示当前值。`op` 取 `modify`、`add`（`before` 为 null）、`delete`（`after` 为 null）、`none`（`rows` 为 `all` 时未改动的行，以及记录已不存在的行）。来源单据的行总带 `flows`：这一行触发的审批流编码列表，为空数组表示没有触发、随审批等待；影响对象的行没有这个值，按 C01 第 1 节省略。一张单据命中多个审批流时，来源单据只返回一份，影响对象每个审批流各自的块，带 `flow`（C06 7.6）。
- 影响对象每行一个勾选框：`ref` 标出这一行（实体、所属单据的主键、明细主键），`checked` 为当前是否勾选，默认为 true，上一级取消的为 false。`editable` 为 true 时当前用户这次通过可以改勾选：块的 `selection` 为 `checked`，且当前用户是该审批流本级入口的待处理审批人；上一级取消的行不能再勾回。样例中的明细主键 6101、6102 是为说明而假设的。
- 影响对象中记录已不存在的行（approval AP-21）排在这一块最后：`missing` 给出 `recordKey`（单据主键，取不到时为 null）和 `label`（关联 SQL 中 `labelColumn` 的值，没有时为 null）；`op` 为 `none`，`cells` 每格的 `before`、`after` 都为 null；没有 `ref` 和 `checked`，不能勾选。前端整行红底，显示"记录已不存在"（frontend-approval FA-09）。样例的第三行是为说明而假设的：假设关联 SQL 从成本单明细出发、左连接成本单主表取单据号，保存前有一条含物料 115 的明细所属的成本单已被删除；C06 7.5 的 `GOODS_TO_COST` 只查明细表，不会查出这种行。
- 同一账号在本级多个入口中待处理时，通过一次即计入这些入口（approval AP-16）；通过请求的 `checkedRows` 列出当前用户能改勾选的各块中勾选的行，用 `flow`、`block` 指出属于哪个审批流的哪一块；这些块中没有列出的行就是取消了，只能从上一级保留的行中选；不能改勾选的块不用提交，保持上一级的结果。
- 任何已登录的用户都能查看审批详情和进度，`actions` 给出当前用户能做的操作。
- `params` 是当前用户这次通过要填写的人工参数，格式同 C06 7.1 的 `params`：取各审批流中 `source` 为 `manual`、`level` 为当前级别的参数；这次通过会使审批到达终点时，还包括不带 `level` 的参数。不是本级待处理的审批人，或者没有要填写的参数时，为空数组。
- 打开详情之后结果发生变化时，通过返回 409 RECONFIRM_REQUIRED，前端重新读取详情。
- 不是本级尚未处理的审批人提交通过或驳回，不是发起人提交撤回，或者已有人做过通过之后提交撤回，返回 403 PERMISSION_DENIED。

## 7. delivery

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/inbox` | `?unread=true&startRow=0&endRow=20` | `{"rows": [{"deliveryId": "…", "title": "…", "body": "…", "link": "/approval/203", "createdAt": "2026-10-24T09:30:01", "read": false}], "total": 3, "unread": 2}` |
| POST | `/api/inbox/{deliveryId}/read` | 无 | 204 |
| GET | `/api/admin/deliveries` | `?status=abandoned&startRow=0&endRow=50` | `{"rows": [{"deliveryId": "…", "recipient": "111", "status": "abandoned", "attempts": 5, "nextRetryAt": null, "lastError": "…"}], "total": 1}`；`status` 取 `pending`、`sent`、`failed`、`abandoned` |
| POST | `/api/admin/deliveries/{deliveryId}/requeue` | 无 | 204；不是 `abandoned` 状态时返回 422 VALIDATION_FAILED |

## 7a. 命令审查（write-pipeline）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/admin/command-review` | `?startRow=0&endRow=50&user=&result=` | `{"enabled": true, "rows": [CommandLog], "total": 12}` |
| PUT | `/api/admin/command-review` | `{"enabled": false}` | 204；关闭时清除全部已记录的内容 |

`CommandLog` 为 `{"requestKey", "user", "page", "operation", "result": "saved|rejected|failed", "errorCode", "message", "startedAt", "durationMs", "sqlCount", "sqlMs", "sql": [{"text", "binds", "ms", "rows", "error"}]}`。

## 8. realtime 与 assembly

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ws` | WebSocket，消息见 [C10](C10-实时事件.md) |
| GET | `/health` | 预热完成后返回 200 `{"status": "ok", "coreVersion": "0.1.0", "configVersion": 13}`；预热完成前返回 503 `{"status": "starting"}`。不需要会话 |

## 9. 契约测试

- 后端生成的 OpenAPI 与本文的路径、方法、请求和响应字段一致。
- contracts 提供的前端模拟实现，对每个接口返回本文的样例。
