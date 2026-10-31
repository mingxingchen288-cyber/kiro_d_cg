/* eslint-disable */
// 由 .reports/modules/frontend-page/gen-samples.mjs 生成，不要手改；契约测试会与 docs/契约 中的样例逐项比较。
import type { Command, CommandResult } from '../command';
import type { ErrorResponse } from '../errors';
import type { PageView } from '../page-view';
import type { EvaluationRequest, EvaluationResult, RulesPack } from '../rules';
import type { ChannelEvent, ClientMessage, ServerMessage } from '../realtime';
import type { Account, AccountList, ApprovalDetail, ApprovalList, ApprovalSummary, CommandReviewList, ConfigItem, ConfigItemList, ConfigSaveResponse, ConfigValidateResponse, DeliveryList, DepartmentList, DictResponse, ExportList, HealthResponse, InboxList, ListRequest, ListResponse, LoginResponse, LookupSearchResponse, MeResponse, PersonalConfig, PreviewResponse, RecordResponse, RowsResponse, SchemaColumnsResponse, SchemaObjectsResponse, SelectRoleResponse, WizardColumnsResponse } from '../http';

/** C02 第 1 节 页面保存 */
export const commandSaveSample: Command = {
  "requestKey": "3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c",
  "page": "COST_PINGGU",
  "operation": "COST_PINGGU.save",
  "documents": [
    {
      "entity": "COST_PINGGU",
      "master": {
        "op": "modify",
        "rowKey": "1001",
        "changes": {
          "QTY": "12"
        }
      },
      "details": [
        {
          "entity": "COST_MATERIAL",
          "op": "add",
          "clientRowId": "tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d",
          "values": {
            "GOODSID": "115",
            "USAGE": "1"
          }
        },
        {
          "entity": "COST_MATERIAL",
          "op": "modify",
          "rowKey": "5001",
          "changes": {
            "PRICE": "3.60"
          }
        },
        {
          "entity": "COST_MATERIAL",
          "op": "delete",
          "rowKey": "5002"
        }
      ]
    }
  ],
  "params": {}
};

/** C02 第 1 节 审批处理 */
export const commandApprovalSample: Command = {
  "requestKey": "9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a",
  "page": null,
  "operation": "approval.pass",
  "documents": [],
  "params": {
    "approvalId": "203",
    "fingerprint": "sha256:5b1e0c6d9a3f47e28b1c6d0e9f3a2b4c5d6e7f8091a2b3c4d5e6f708192a3b4c",
    "checkedRows": [
      {
        "flow": "GOODS_TO_COST",
        "block": "costMaterial",
        "key": "206323"
      }
    ],
    "comment": "价格已核对",
    "params": {
      "effectiveDate": "2026-11-01"
    }
  }
};

/** C02 第 2 节 已写入 */
export const resultSavedSample: CommandResult = {
  "requestKey": "3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c",
  "outcome": "saved",
  "rows": [
    {
      "entity": "COST_PINGGU",
      "rowKey": "1001",
      "values": {
        "DOCID": "1001",
        "QTY": "12",
        "TOTAL_COST": "54.00"
      },
      "frozen": null
    },
    {
      "entity": "COST_MATERIAL",
      "rowKey": "7001",
      "clientRowId": "tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d",
      "values": {
        "DTLID": "7001",
        "GOODSID": "115",
        "USAGE": "1",
        "PRICE": "1.20"
      },
      "frozen": null
    },
    {
      "entity": "COST_MATERIAL",
      "rowKey": "5002",
      "deleted": true
    }
  ],
  "idMap": {
    "tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d": "7001"
  },
  "prompts": [
    {
      "rule": "R_MARGIN_LOW",
      "message": "毛利率低于 5%",
      "entity": "COST_PINGGU",
      "rowKey": "1001",
      "field": "MARGIN"
    }
  ],
  "skipped": [
    {
      "entity": "COST_MATERIAL",
      "rowKey": "5003",
      "reason": "ROW_NOT_FOUND"
    }
  ],
  "approvals": []
};

/** C02 第 2 节 已提交审批 */
export const resultApprovalSubmittedSample: CommandResult = {
  "requestKey": "7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
  "outcome": "approvalSubmitted",
  "rows": [
    {
      "entity": "COST_PINGGU",
      "rowKey": "1001",
      "values": {
        "DOCID": "1001",
        "QTY": "10",
        "TOTAL_COST": "45.00"
      },
      "frozen": {
        "approvalId": "203"
      }
    }
  ],
  "idMap": {},
  "prompts": [],
  "skipped": [],
  "approvals": [
    {
      "approvalId": "203",
      "document": {
        "entity": "COST_PINGGU",
        "recordKey": "1001"
      },
      "status": "pending",
      "level": 1,
      "flows": [
        "COST_TO_GOODS"
      ]
    }
  ]
};

/** C03 第 1 节 */
export const errorSample: ErrorResponse = {
  "code": "FIELD_NOT_WRITABLE",
  "message": "有字段不能修改",
  "details": [
    {
      "message": "PRICE 是 ERP 列，不能修改",
      "entity": "COST_GOODS_PRICE",
      "rowKey": "115",
      "clientRowId": null,
      "field": "PRICE",
      "approvalId": null,
      "configType": null,
      "configKey": null,
      "path": null
    }
  ]
};

/** C05 */
export const pageViewSample: PageView = {
  "pageCode": "COST_PINGGU",
  "title": "成本核算",
  "version": 13,
  "layout": "masterDetail",
  "detailMode": "tabs",
  "audit": true,
  "saveOperation": "COST_PINGGU.save",
  "rulesPack": {
    "packId": "COST_PINGGU",
    "version": 7
  },
  "master": {
    "entity": "COST_PINGGU",
    "primaryKey": "DOCID",
    "fields": [
      {
        "name": "DOCID",
        "label": "单据号",
        "type": "number",
        "scale": 0,
        "source": "own",
        "calculated": false,
        "visible": true,
        "editable": false,
        "required": false,
        "width": 120,
        "pinned": "left",
        "dictType": null,
        "lookup": null
      },
      {
        "name": "GOODSNAME",
        "label": "产品名称",
        "type": "text",
        "scale": null,
        "source": "erp",
        "calculated": false,
        "visible": true,
        "editable": false,
        "required": false,
        "width": 200,
        "pinned": null,
        "dictType": null,
        "lookup": null
      },
      {
        "name": "TOTAL_COST",
        "label": "总成本",
        "type": "number",
        "scale": 2,
        "source": "own",
        "calculated": true,
        "visible": true,
        "editable": false,
        "required": false,
        "width": 120,
        "pinned": null,
        "dictType": null,
        "lookup": null,
        "aggregate": "sum"
      }
    ],
    "buttons": [
      {
        "key": "master:copyRow",
        "action": "copyRow",
        "label": "复制",
        "operation": null,
        "requiresSelection": true
      },
      {
        "key": "master:syncPrice",
        "action": "syncPrice",
        "label": "同步价格",
        "operation": "COST_PINGGU.syncPrice",
        "requiresSelection": true
      }
    ],
    "grid": {
      "sideBar": true,
      "cellSelection": true,
      "groupBy": []
    },
    "formLayout": [
      {
        "field": "GOODSNAME",
        "x": 0,
        "y": 0,
        "w": 12,
        "h": 1
      }
    ],
    "canModify": false
  },
  "details": [
    {
      "entity": "COST_MATERIAL",
      "title": "材料",
      "primaryKey": "DTLID",
      "parentKey": "DOCID",
      "fields": [
        {
          "name": "GOODSID",
          "label": "物料",
          "type": "number",
          "scale": 0,
          "source": "own",
          "calculated": false,
          "visible": true,
          "editable": true,
          "required": true,
          "width": 120,
          "pinned": null,
          "dictType": null,
          "lookup": {
            "code": "GOODS",
            "fill": {
              "GOODSID": "GOODSID",
              "GOODSNAME": "NAME"
            }
          }
        },
        {
          "name": "PRICE",
          "label": "价格",
          "type": "number",
          "scale": 4,
          "source": "own",
          "calculated": false,
          "visible": true,
          "editable": true,
          "required": false,
          "width": 100,
          "pinned": null,
          "dictType": null,
          "lookup": null
        }
      ],
      "buttons": [
        {
          "key": "COST_MATERIAL:addRow",
          "action": "addRow",
          "label": "新增",
          "operation": null,
          "requiresSelection": false
        },
        {
          "key": "COST_MATERIAL:copyRow",
          "action": "copyRow",
          "label": "复制",
          "operation": null,
          "requiresSelection": true
        },
        {
          "key": "COST_MATERIAL:deleteRow",
          "action": "deleteRow",
          "label": "删除",
          "operation": null,
          "requiresSelection": true
        }
      ],
      "grid": {
        "sideBar": true,
        "cellSelection": true,
        "groupBy": []
      },
      "formLayout": []
    }
  ],
  "systemButtons": [
    "save",
    "advancedSearch"
  ]
};

/** C07 第 1 节 */
export const rulesPackSample: RulesPack = {
  "packId": "COST_PINGGU",
  "version": 7,
  "coreVersion": "0.1.0",
  "fields": {
    "COST_PINGGU": {
      "QTY": {
        "type": "number",
        "scale": 2,
        "role": "input",
        "source": "own"
      },
      "TOTAL_COST": {
        "type": "number",
        "scale": 2,
        "role": "calculated",
        "source": "own"
      }
    },
    "COST_MATERIAL": {
      "PRICE": {
        "type": "number",
        "scale": 4,
        "role": "input",
        "source": "own"
      }
    }
  },
  "rules": [
    {
      "id": "R_TOTAL",
      "layer": "entity",
      "entity": "COST_PINGGU",
      "category": "calc",
      "order": 10,
      "serverOnly": false,
      "jdm": "R_TOTAL"
    },
    {
      "id": "R_LOCK_PRICE",
      "layer": "page",
      "page": "COST_PINGGU",
      "category": "ui",
      "order": 200,
      "serverOnly": false,
      "jdm": "R_LOCK_PRICE"
    }
  ],
  "jdm": {
    "R_TOTAL": {
      "nodes": [],
      "edges": []
    }
  }
};

/** C07 第 2 节 */
export const evaluationRequestSample: EvaluationRequest = {
  "purpose": "operation",
  "operation": "COST_PINGGU.save",
  "page": "COST_PINGGU",
  "phase": "commit",
  "context": {
    "userId": "1",
    "departmentId": "10",
    "role": "COST_ACCOUNTANT",
    "today": "2026-10-24",
    "origin": "user"
  },
  "document": {
    "entity": "COST_PINGGU",
    "master": {
      "rowKey": "1001",
      "values": {
        "QTY": "10",
        "PRICE": "4.5"
      }
    },
    "details": {
      "COST_MATERIAL": [
        {
          "rowKey": "5001",
          "values": {
            "GOODSID": "115",
            "USAGE": "2",
            "PRICE": "3.50"
          },
          "old": {
            "PRICE": "3.20"
          }
        },
        {
          "clientRowId": "tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d",
          "values": {
            "GOODSID": "116",
            "USAGE": "1",
            "PRICE": "1.20"
          }
        }
      ]
    }
  },
  "changed": [
    {
      "entity": "COST_MATERIAL",
      "rowKey": "5001",
      "op": "modify",
      "fields": [
        "PRICE"
      ]
    }
  ],
  "data": {}
};

/** C07 第 3 节 */
export const evaluationResultSample: EvaluationResult = {
  "ok": true,
  "rows": [
    {
      "entity": "COST_PINGGU",
      "rowKey": "1001",
      "computed": {
        "TOTAL_COST": "45.00"
      },
      "fields": {
        "PRICE": {
          "editable": false
        },
        "REMARK": {
          "required": true
        }
      },
      "style": {
        "row": null,
        "cells": {}
      }
    }
  ],
  "effects": [
    {
      "kind": "prompt",
      "rule": "R_MARGIN_LOW",
      "message": "毛利率低于 5%",
      "entity": "COST_PINGGU",
      "rowKey": "1001",
      "field": "MARGIN"
    },
    {
      "kind": "reject",
      "rule": "R_PRICE_RANGE",
      "message": "价格超出范围",
      "entity": "COST_MATERIAL",
      "rowKey": "5001",
      "field": "PRICE"
    }
  ]
};

/** C09 第 4 节 ListRequest */
export const listRequestSample: ListRequest = {
  "startRow": 0,
  "endRow": 100,
  "sortModel": [
    {
      "colId": "DOCID",
      "sort": "desc"
    }
  ],
  "filterModel": {
    "GOODSNAME": {
      "filterType": "text",
      "type": "contains",
      "filter": "胶囊"
    }
  },
  "advanced": {
    "op": "and",
    "conditions": [
      {
        "field": "TOTAL_COST",
        "operator": ">=",
        "value": "100"
      },
      {
        "entity": "COST_MATERIAL",
        "group": "g1",
        "field": "GOODSID",
        "operator": "=",
        "value": "115"
      },
      {
        "entity": "COST_MATERIAL",
        "group": "g1",
        "logic": "and",
        "field": "PRICE",
        "operator": ">",
        "value": "3"
      }
    ]
  }
};

/** C09 第 4 节 PersonalConfig */
export const personalConfigSample: PersonalConfig = {
  "grids": {
    "master": {
      "columns": [
        {
          "field": "DOCID",
          "width": 120,
          "pinned": "left",
          "hide": false
        }
      ]
    },
    "COST_MATERIAL": {
      "columns": []
    }
  },
  "detailMode": "tabs"
};

/** C09 第 6 节 ApprovalSummary */
export const approvalSummarySample: ApprovalSummary = {
  "approvalId": "203",
  "page": "GOODS_PRICE_MANAGE",
  "pageTitle": "物料清单及成本",
  "operation": "COST_GOODS_PRICE.save",
  "operationLabel": "保存",
  "source": {
    "entity": "COST_GOODS_PRICE",
    "recordKey": "25",
    "label": "聚维酮K30"
  },
  "applicant": {
    "userId": "112",
    "displayName": "杨娜"
  },
  "submittedAt": "2026-10-24T09:30:00",
  "status": "pending",
  "level": 1
};

/** C09 第 6 节 ApprovalDetail */
export const approvalDetailSample: ApprovalDetail = {
  "approvalId": "203",
  "status": "pending",
  "page": "GOODS_PRICE_MANAGE",
  "pageTitle": "物料清单及成本",
  "operation": "COST_GOODS_PRICE.save",
  "operationLabel": "保存",
  "source": {
    "entity": "COST_GOODS_PRICE",
    "recordKey": "25",
    "label": "聚维酮K30"
  },
  "applicant": {
    "userId": "112",
    "displayName": "杨娜"
  },
  "submittedAt": "2026-10-24T09:30:00",
  "currentLevel": 1,
  "steps": [
    {
      "level": 1,
      "flow": "GOODS_TO_COST",
      "flowName": "物料清单改价审批",
      "node": "管理员审批",
      "mode": "or",
      "status": "pending",
      "members": [
        {
          "type": "role",
          "id": "ADMIN",
          "name": "系统管理员",
          "status": "pending",
          "processedBy": null,
          "processedAt": null,
          "comment": null
        }
      ]
    },
    {
      "level": 1,
      "flow": "GOODS_PRICE_AUDIT",
      "flowName": "物料改价复核",
      "node": "采购复核",
      "mode": "or",
      "status": "pending",
      "members": [
        {
          "type": "role",
          "id": "008",
          "name": "采购",
          "status": "pending",
          "processedBy": null,
          "processedAt": null,
          "comment": null
        }
      ]
    },
    {
      "level": 2,
      "flow": "GOODS_PRICE_AUDIT",
      "flowName": "物料改价复核",
      "node": "管理员复核",
      "mode": "or",
      "status": "upcoming",
      "members": [
        {
          "type": "role",
          "id": "ADMIN",
          "name": "系统管理员",
          "status": "pending",
          "processedBy": null,
          "processedAt": null,
          "comment": null
        }
      ]
    }
  ],
  "view": {
    "master": {
      "key": "goods",
      "title": "物料清单",
      "columns": [
        "物料ID",
        "物料名称",
        "参考价格",
        "单价"
      ],
      "rows": [
        {
          "op": "modify",
          "flows": [
            "GOODS_TO_COST",
            "GOODS_PRICE_AUDIT"
          ],
          "cells": [
            {
              "before": "25",
              "after": "25"
            },
            {
              "before": "聚维酮K30",
              "after": "聚维酮K30"
            },
            {
              "before": "75.00",
              "after": "75.00"
            },
            {
              "before": "75.00",
              "after": "80.00"
            }
          ]
        }
      ],
      "widths": [
        null,
        null,
        null,
        null
      ]
    },
    "details": [],
    "affected": [
      {
        "flow": "GOODS_TO_COST",
        "key": "costMaterial",
        "title": "成本核算（原辅料）",
        "selection": "checked",
        "editable": true,
        "columns": [
          "单据号",
          "产品",
          "物料",
          "单价",
          "金额",
          "每盒成本",
          "千片加工费"
        ],
        "rows": [
          {
            "op": "modify",
            "ref": {
              "key": "206323"
            },
            "checked": true,
            "cells": [
              {
                "before": "2550",
                "after": "2550"
              },
              {
                "before": "250mg乙酰唑胺片",
                "after": "250mg乙酰唑胺片"
              },
              {
                "before": "聚维酮K30",
                "after": "聚维酮K30"
              },
              {
                "before": "75.00",
                "after": "80.00"
              },
              {
                "before": "750.00",
                "after": "800.00"
              },
              {
                "before": "13.0065",
                "after": "13.0507"
              },
              {
                "before": "94.73",
                "after": "94.29"
              }
            ]
          },
          {
            "op": "none",
            "ref": {
              "key": "103681"
            },
            "checked": false,
            "cells": [
              {
                "before": "2556",
                "after": "2556"
              },
              {
                "before": "10mg氯丙嗪片",
                "after": "10mg氯丙嗪片"
              },
              {
                "before": "聚维酮K30",
                "after": "聚维酮K30"
              },
              {
                "before": "75.00",
                "after": "75.00"
              },
              {
                "before": "23.25",
                "after": "23.25"
              },
              {
                "before": "1.1566",
                "after": "1.1566"
              },
              {
                "before": "689.03",
                "after": "689.03"
              }
            ]
          },
          {
            "op": "none",
            "missing": true,
            "cells": [
              {
                "before": "2601",
                "after": "2601"
              },
              {
                "before": null,
                "after": null
              },
              {
                "before": "聚维酮K30",
                "after": "聚维酮K30"
              },
              {
                "before": "75.00",
                "after": "75.00"
              },
              {
                "before": "150.00",
                "after": "150.00"
              },
              {
                "before": null,
                "after": null
              },
              {
                "before": null,
                "after": null
              }
            ]
          }
        ],
        "widths": [
          120,
          200,
          null,
          null,
          null,
          null,
          null
        ]
      }
    ]
  },
  "fingerprint": "sha256:5b1e0c6d9a3f47e28b1c6d0e9f3a2b4c5d6e7f8091a2b3c4d5e6f708192a3b4c",
  "params": [],
  "actions": {
    "canPass": true,
    "canReject": true,
    "canWithdraw": false
  },
  "history": [
    {
      "action": "submit",
      "level": 1,
      "by": {
        "userId": "112",
        "displayName": "杨娜"
      },
      "at": "2026-10-24T09:30:00",
      "comment": null
    }
  ]
};

/** C10 第 1 节 */
export const channelEventSample: ChannelEvent = {
  "eventId": "6c2f0d6e-1b7a-4b55-9a1e-2f8f3c1d4e5a",
  "topic": "config.changed",
  "audience": {
    "pages": [
      "COST_PINGGU"
    ]
  },
  "payload": {
    "pages": [
      "COST_PINGGU"
    ],
    "version": 13
  }
};

/** C10 第 2 节 浏览器发送 */
export const clientMessageSamples: ClientMessage[] = [
  {
    "type": "subscribe",
    "pages": [
      "COST_PINGGU"
    ]
  },
  {
    "type": "unsubscribe",
    "pages": [
      "COST_PINGGU"
    ]
  },
  {
    "type": "ping"
  }
];

/** C10 第 2 节 服务端推送 */
export const serverMessageSamples: ServerMessage[] = [
  {
    "topic": "config.changed",
    "eventId": "1f2e3d4c-5b6a-4978-8695-a4b3c2d1e0f9",
    "payload": {
      "pages": [
        "COST_PINGGU"
      ],
      "version": 13
    }
  },
  {
    "topic": "notification",
    "eventId": "2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6d",
    "payload": {
      "deliveryId": "3b4c5d6e-7f8a-4b9c-8d0e-2f3a4b5c6d7e",
      "title": "您有来自于物料清单及成本页面，业务单据为115的审批",
      "body": "",
      "link": "/approval/203"
    }
  },
  {
    "topic": "session.revoked",
    "eventId": "4c5d6e7f-8a9b-4c0d-9e1f-3a4b5c6d7e8f",
    "payload": {
      "reason": "accountDisabled"
    }
  },
  {
    "type": "pong"
  }
];

/** C09 第 2 节 登录 */
export const loginResponseSample: LoginResponse = {
  "user": {
    "userId": "112",
    "username": "yangna",
    "displayName": "杨娜",
    "departmentId": "10",
    "departmentName": "成本部"
  },
  "roles": [
    {
      "code": "COST_ACCOUNTANT",
      "name": "成本会计",
      "admin": false
    }
  ],
  "selectedRole": {
    "code": "COST_ACCOUNTANT",
    "name": "成本会计",
    "admin": false
  },
  "csrfToken": "c"
};

/** C09 第 2 节 选角色 */
export const selectRoleResponseSample: SelectRoleResponse = {
  "selectedRole": {
    "code": "COST_ACCOUNTANT",
    "name": "成本会计",
    "admin": false
  }
};

/** C09 第 2 节 /api/me */
export const meResponseSample: MeResponse = {
  "user": {
    "userId": "112",
    "username": "yangna",
    "displayName": "杨娜",
    "departmentId": "10",
    "departmentName": "成本部"
  },
  "role": {
    "code": "COST_ACCOUNTANT",
    "name": "成本会计",
    "admin": false
  },
  "menus": [
    {
      "key": "cost",
      "title": "成本",
      "kind": "group",
      "children": [
        {
          "key": "COST_PINGGU",
          "title": "成本核算",
          "kind": "page",
          "pageCode": "COST_PINGGU"
        }
      ]
    }
  ],
  "configVersion": 13,
  "csrfToken": "c"
};

/** C09 第 2 节 账号列表 */
export const accountListSample: AccountList = {
  "rows": [
    {
      "userId": "112",
      "username": "yangna",
      "displayName": "杨娜",
      "departmentId": "10",
      "enabled": true,
      "roleCodes": [
        "COST_ACCOUNTANT"
      ]
    }
  ],
  "total": 120
};

/** C09 第 2 节 新建账号的响应（请求为样例中的张三） */
export const accountSample: Account = {
  "userId": "113",
  "username": "zhangsan",
  "displayName": "张三",
  "departmentId": "10",
  "enabled": true,
  "roleCodes": [
    "COST_ACCOUNTANT"
  ]
};

/** C09 第 2 节 部门 */
export const departmentListSample: DepartmentList = {
  "items": [
    {
      "departmentId": "10",
      "name": "成本部",
      "parentId": null
    }
  ]
};

/** C09 第 3 节 配置项列表 */
export const configItemListSample: ConfigItemList = {
  "items": [
    {
      "type": "page",
      "key": "COST_PINGGU",
      "name": "成本核算",
      "version": 13,
      "updatedBy": "1",
      "updatedAt": "2026-10-24T10:00:00"
    }
  ]
};

/** C06 第 1 节 配置项 */
export const configItemSample: ConfigItem = {
  "type": "page",
  "key": "COST_PINGGU",
  "name": "成本核算",
  "version": 13,
  "updatedBy": "1",
  "updatedAt": "2026-10-24T10:00:00",
  "content": {}
};

/** C09 第 3 节 保存配置 */
export const configSaveResponseSample: ConfigSaveResponse = {
  "type": "page",
  "key": "COST_PINGGU",
  "version": 14
};

/** C09 第 3 节 配置校验 */
export const configValidateResponseSample: ConfigValidateResponse = {
  "ok": false,
  "errors": [
    {
      "message": "入口至少要有一个审批人",
      "entity": null,
      "rowKey": null,
      "clientRowId": null,
      "field": null,
      "approvalId": null,
      "configType": "approvalFlow",
      "configKey": "GOODS_TO_COST",
      "path": "levels[0].nodes[0].approvers"
    }
  ]
};

/** C09 第 3 节 向导读列 */
export const wizardColumnsResponseSample: WizardColumnsResponse = {
  "primaryKey": "GOODSID",
  "sequence": {
    "name": "T_COST_GOODS_SEQ",
    "exists": true
  },
  "columns": [
    {
      "name": "ZX_PRICE",
      "type": "number",
      "label": "执行价",
      "inTable": true
    }
  ]
};

/** C09 第 3 节 读表结构 */
export const schemaColumnsResponseSample: SchemaColumnsResponse = {
  "objectType": "view",
  "primaryKey": null,
  "columns": [
    {
      "name": "DTLID",
      "type": "number"
    }
  ]
};

/** C09 第 3 节 搜表和视图（v16） */
export const schemaObjectsResponseSample: SchemaObjectsResponse = {
  "objects": [
    {
      "name": "T_COST_GOODS",
      "type": "table"
    },
    {
      "name": "T_COST_GOODS_PRICE_V",
      "type": "view"
    }
  ]
};

/** C09 第 4 节 列表 */
export const listResponseSample: ListResponse = {
  "rows": [
    {
      "rowKey": "1001",
      "values": {
        "QTY": "12"
      },
      "frozen": null
    }
  ],
  "total": 1234,
  "aggregates": {
    "TOTAL_COST": "98765.43"
  }
};

/** C09 第 4 节 按主键读行 */
export const rowsByKeysResponseSample: RowsResponse = {
  "rows": [
    {
      "rowKey": "1001",
      "values": {
        "QTY": "12"
      },
      "frozen": null
    },
    {
      "rowKey": "1002",
      "values": {
        "QTY": "12"
      },
      "frozen": {
        "approvalId": "203"
      },
      "compare": {
        "PRICE": {
          "value": "3.50",
          "diff": "0.30",
          "percent": "8.57"
        }
      }
    }
  ]
};

/** C09 第 4 节 单据加载 */
export const recordResponseSample: RecordResponse = {
  "master": {
    "rowKey": "1001",
    "values": {
      "QTY": "12"
    },
    "frozen": null
  },
  "details": {
    "COST_MATERIAL": [
      {
        "rowKey": "1001",
        "values": {
          "QTY": "12"
        },
        "frozen": null
      }
    ]
  }
};

/** C09 第 4 节 Lookup 查询 */
export const lookupSearchResponseSample: LookupSearchResponse = {
  "rows": [
    {
      "values": {
        "GOODSID": "115",
        "NAME": "胶囊壳"
      }
    }
  ],
  "total": 3,
  "keywordSearch": true
};

/** C09 第 4 节 字典 */
export const dictResponseSample: DictResponse = {
  "items": [
    {
      "value": "1",
      "label": "启用"
    }
  ]
};

/** C09 第 4 节 导出配置 */
export const exportListSample: ExportList = {
  "items": [
    {
      "exportCode": "cost-pinggu-export",
      "name": "物料成本核算表导出"
    }
  ]
};

/** C09 第 6 节 待办列表 */
export const approvalListSample: ApprovalList = {
  "rows": [
    {
      "approvalId": "203",
      "page": "GOODS_PRICE_MANAGE",
      "pageTitle": "物料清单及成本",
      "operation": "COST_GOODS_PRICE.save",
      "operationLabel": "保存",
      "source": {
        "entity": "COST_GOODS_PRICE",
        "recordKey": "25",
        "label": "聚维酮K30"
      },
      "applicant": {
        "userId": "112",
        "displayName": "杨娜"
      },
      "submittedAt": "2026-10-24T09:30:00",
      "status": "pending",
      "level": 1
    }
  ],
  "total": 7
};

/** C09 第 6 节 预览 */
export const previewResponseSample: PreviewResponse = {
  "view": {
    "master": {
      "key": "goods",
      "title": "物料清单",
      "columns": [
        "物料ID",
        "物料名称",
        "参考价格",
        "单价"
      ],
      "rows": [
        {
          "op": "modify",
          "flows": [
            "GOODS_TO_COST",
            "GOODS_PRICE_AUDIT"
          ],
          "cells": [
            {
              "before": "25",
              "after": "25"
            },
            {
              "before": "聚维酮K30",
              "after": "聚维酮K30"
            },
            {
              "before": "75.00",
              "after": "75.00"
            },
            {
              "before": "75.00",
              "after": "80.00"
            }
          ]
        }
      ],
      "widths": [
        null,
        null,
        null,
        null
      ]
    },
    "details": [],
    "affected": [
      {
        "flow": "GOODS_TO_COST",
        "key": "costMaterial",
        "title": "成本核算（原辅料）",
        "selection": "checked",
        "editable": true,
        "columns": [
          "单据号",
          "产品",
          "物料",
          "单价",
          "金额",
          "每盒成本",
          "千片加工费"
        ],
        "rows": [
          {
            "op": "modify",
            "ref": {
              "key": "206323"
            },
            "checked": true,
            "cells": [
              {
                "before": "2550",
                "after": "2550"
              },
              {
                "before": "250mg乙酰唑胺片",
                "after": "250mg乙酰唑胺片"
              },
              {
                "before": "聚维酮K30",
                "after": "聚维酮K30"
              },
              {
                "before": "75.00",
                "after": "80.00"
              },
              {
                "before": "750.00",
                "after": "800.00"
              },
              {
                "before": "13.0065",
                "after": "13.0507"
              },
              {
                "before": "94.73",
                "after": "94.29"
              }
            ]
          },
          {
            "op": "none",
            "ref": {
              "key": "103681"
            },
            "checked": false,
            "cells": [
              {
                "before": "2556",
                "after": "2556"
              },
              {
                "before": "10mg氯丙嗪片",
                "after": "10mg氯丙嗪片"
              },
              {
                "before": "聚维酮K30",
                "after": "聚维酮K30"
              },
              {
                "before": "75.00",
                "after": "75.00"
              },
              {
                "before": "23.25",
                "after": "23.25"
              },
              {
                "before": "1.1566",
                "after": "1.1566"
              },
              {
                "before": "689.03",
                "after": "689.03"
              }
            ]
          },
          {
            "op": "none",
            "missing": true,
            "cells": [
              {
                "before": "2601",
                "after": "2601"
              },
              {
                "before": null,
                "after": null
              },
              {
                "before": "聚维酮K30",
                "after": "聚维酮K30"
              },
              {
                "before": "75.00",
                "after": "75.00"
              },
              {
                "before": "150.00",
                "after": "150.00"
              },
              {
                "before": null,
                "after": null
              },
              {
                "before": null,
                "after": null
              }
            ]
          }
        ]
      }
    ]
  },
  "fingerprint": "sha256:5b1e0c6d9a3f47e28b1c6d0e9f3a2b4c5d6e7f8091a2b3c4d5e6f708192a3b4c"
};

/** C09 第 7 节 站内通知 */
export const inboxListSample: InboxList = {
  "rows": [
    {
      "deliveryId": "3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c",
      "title": "您有来自于物料清单及成本页面，业务单据为115的审批",
      "body": "",
      "link": "/approval/203",
      "createdAt": "2026-10-24T09:30:01",
      "read": false
    }
  ],
  "total": 3,
  "unread": 2
};

/** C09 第 7 节 投递记录 */
export const deliveryListSample: DeliveryList = {
  "rows": [
    {
      "deliveryId": "3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c",
      "recipient": "111",
      "status": "abandoned",
      "attempts": 5,
      "nextRetryAt": null,
      "lastError": "连接被拒绝"
    }
  ],
  "total": 1
};

/** C09 第 7a 节 命令审查 */
export const commandReviewListSample: CommandReviewList = {
  "enabled": true,
  "rows": [
    {
      "requestKey": "3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c",
      "user": "admin",
      "page": "COST_PINGGU",
      "operation": "COST_PINGGU.save",
      "result": "rejected",
      "errorCode": "RULE_REJECTED",
      "message": "价格超出范围",
      "startedAt": "2026-10-24T09:30:00",
      "durationMs": 35,
      "sqlCount": 2,
      "sqlMs": 4.5,
      "sql": [
        {
          "text": "SELECT 1 FROM DUAL",
          "binds": {},
          "ms": 1.2,
          "rows": 1,
          "error": null
        }
      ]
    }
  ],
  "total": 12
};

/** C09 第 8 节 健康检查 */
export const healthSample: HealthResponse = {
  "status": "ok",
  "coreVersion": "0.1.0",
  "configVersion": 13
};

/** 审批处理的命令结果。C09 没有给出这个样例，按 C02 第 2 节的写法、用 C09 审批 203 的数据构造 */
export const approvalProcessedSample: CommandResult = {
  "requestKey": "9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a",
  "outcome": "approvalProcessed",
  "rows": [],
  "idMap": {},
  "prompts": [],
  "skipped": [],
  "approvals": [
    {
      "approvalId": "203",
      "document": {
        "entity": "COST_GOODS_PRICE",
        "recordKey": "25"
      },
      "status": "pending",
      "level": 2,
      "flows": [
        "GOODS_PRICE_AUDIT"
      ]
    }
  ]
};

