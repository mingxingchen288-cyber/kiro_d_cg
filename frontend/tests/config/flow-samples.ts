/** C06 v17 第 7.8～7.10 节的三个审批流样例（`content`），原样照抄，用来核对编辑界面保存的内容 */
import type { ApprovalFlowContent } from '../../src/modules/config/core/types';

const notify: ApprovalFlowContent['notify'] = [
  { event: 'submitted', to: 'levelApprovers' },
  { event: 'passed', to: 'applicant' },
  { event: 'rejected', to: 'applicant' }
];

export const COST_TO_GOODS: ApprovalFlowContent = {
  page: 'COST_PINGGU',
  order: 1,
  enabled: true,
  operations: { COST_MATERIAL: ['add', 'modify'], COST_PACKAGE: ['add', 'modify'] },
  levels: [
    {
      level: 1,
      nodes: [
        {
          name: '管理员审批',
          conditionType: 'sql',
          condition:
            '(DECODE(:new_GOODSID, :old_GOODSID, 0, 1) = 1 OR DECODE(:new_PRICE, :old_PRICE, 0, 1) = 1) AND DECODE(:new_PRICE, (SELECT NVL(ZX_PRICE, PRICE) FROM T_COST_GOODS WHERE GOODSID = :new_GOODSID), 0, 1) = 1',
          department: null,
          approvers: [{ type: 'role', role: 'ADMIN' }],
          mode: 'or',
          enabled: true
        }
      ]
    },
    {
      level: 2,
      nodes: [
        {
          name: '采购、生产会签',
          conditionType: 'sql',
          condition: ':new_PRICE > (SELECT NVL(ZX_PRICE, PRICE) * 1.1 FROM T_COST_GOODS WHERE GOODSID = :new_GOODSID)',
          department: null,
          approvers: [
            { type: 'role', role: '008' },
            { type: 'role', role: '007' }
          ],
          mode: 'and',
          enabled: true
        }
      ]
    }
  ],
  freeze: [{ table: 'T_COST_GOODS', condition: 'GOODSID = :new_GOODSID', enabled: true }],
  display: [
    {
      key: 'cost',
      title: '成本单及成本变化',
      region: 'master',
      source: 'COST_PINGGU',
      columns: [
        { field: 'DOCID', label: '单据号' },
        { field: 'GOODSNAME', label: '产品' },
        { field: 'COST_PERBOX', label: '每盒成本', precision: 4 },
        { field: 'JGF_PERQP', label: '千片加工费', precision: 2 }
      ]
    },
    {
      key: 'material',
      title: '原辅料',
      region: 'detail',
      source: 'COST_MATERIAL',
      columns: [
        { field: 'GOODSID', label: '物料' },
        { field: 'GOODSNAME', label: '物料名称' },
        { field: 'PRICE', label: '单价', precision: 2 },
        { field: 'COST_BATCH', label: '金额', precision: 2 }
      ]
    },
    {
      key: 'package',
      title: '包材',
      region: 'detail',
      source: 'COST_PACKAGE',
      columns: [
        { field: 'GOODSID', label: '物料' },
        { field: 'GOODSNAME', label: '物料名称' },
        { field: 'PRICE', label: '单价', precision: 2 },
        { field: 'COST_BATCH', label: '金额', precision: 2 }
      ]
    },
    {
      key: 'goods',
      title: '物料清单',
      region: 'affected',
      source: 'T_COST_GOODS_PRICE_V',
      condition: 'GOODSID = :new_GOODSID',
      targetTable: 'T_COST_GOODS',
      keyColumn: 'GOODSID',
      columns: [
        { field: 'GOODSID', label: '物料ID' },
        { field: 'GOODSNAME', label: '物料名称' },
        { field: 'ZX_PRICE', label: '单价', precision: 2 }
      ],
      selection: 'all',
      actions: [{ action: 'updateFields', fields: [{ column: 'ZX_PRICE', value: ':new_PRICE' }] }]
    }
  ],
  propagation: 'end',
  notify
};

export const TECH_CUSTOMER_MATERIAL: ApprovalFlowContent = {
  page: 'COST_PINGGU',
  order: 2,
  enabled: true,
  operations: { COST_MATERIAL: ['modify', 'delete'], COST_PACKAGE: ['modify', 'delete'] },
  levels: [
    {
      level: 1,
      nodes: [
        {
          name: '管理员审批',
          conditionType: 'sql',
          condition:
            ":master_old_USESTATUS = '评估中' AND NVL(:old_CUSTOMER_SPECIFIED, 0) <> 0 AND (:operation = 'deleted' OR DECODE(:new_GOODSID, :old_GOODSID, 0, 1) = 1 OR DECODE(:new_CUSTOMER_SPECIFIED, :old_CUSTOMER_SPECIFIED, 0, 1) = 1)",
          department: '1069',
          approvers: [{ type: 'role', role: 'ADMIN' }],
          mode: 'or',
          enabled: true
        }
      ]
    }
  ],
  freeze: [],
  display: [
    {
      key: 'cost',
      title: '成本单及成本变化',
      region: 'master',
      source: 'COST_PINGGU',
      columns: [
        { field: 'DOCID', label: '单据号' },
        { field: 'GOODSNAME', label: '产品' },
        { field: 'COST_PERBOX', label: '每盒成本', precision: 4 },
        { field: 'JGF_PERQP', label: '千片加工费', precision: 2 }
      ]
    },
    {
      key: 'material',
      title: '原辅料',
      region: 'detail',
      source: 'COST_MATERIAL',
      columns: [
        { field: 'GOODSID', label: '物料' },
        { field: 'GOODSNAME', label: '物料名称' },
        { field: 'PRICE', label: '单价', precision: 2 },
        { field: 'COST_BATCH', label: '金额', precision: 2 },
        { field: 'CUSTOMER_SPECIFIED', label: '客户指定' }
      ]
    },
    {
      key: 'package',
      title: '包材',
      region: 'detail',
      source: 'COST_PACKAGE',
      columns: [
        { field: 'GOODSID', label: '物料' },
        { field: 'GOODSNAME', label: '物料名称' },
        { field: 'PRICE', label: '单价', precision: 2 },
        { field: 'COST_BATCH', label: '金额', precision: 2 },
        { field: 'CUSTOMER_SPECIFIED', label: '客户指定' }
      ]
    }
  ],
  propagation: 'end',
  notify
};

const affected = (key: string, title: string, source: string, targetTable: string, withMaster: boolean) => ({
  key,
  title,
  region: 'affected' as const,
  source,
  condition: 'GOODSID = :new_GOODSID',
  targetTable,
  keyColumn: 'DTLID',
  columns: [
    { field: 'master.DOCID', label: '单据号' },
    { field: 'master.GOODSNAME', label: '产品' },
    { field: 'GOODSNAME', label: '物料' },
    { field: 'PRICE', label: '单价', precision: 2 },
    { field: 'COST_BATCH', label: '金额', precision: 2 },
    ...(withMaster
      ? [
          { field: 'master.COST_PERBOX', label: '每盒成本', precision: 4 },
          { field: 'master.JGF_PERQP', label: '千片加工费', precision: 2 }
        ]
      : [])
  ],
  selection: 'checked' as const,
  actions: [{ action: 'updateFields' as const, fields: [{ column: 'PRICE', value: 'NVL(:new_ZX_PRICE, :old_PRICE)' }] }]
});

export const GOODS_TO_COST: ApprovalFlowContent = {
  page: 'GOODS_PRICE_MANAGE',
  order: 3,
  enabled: true,
  operations: { COST_GOODS_PRICE: ['modify'] },
  levels: [
    {
      level: 1,
      nodes: [
        {
          name: '管理员审批',
          conditionType: 'sql',
          condition: 'DECODE(:new_ZX_PRICE, :old_ZX_PRICE, 0, 1) = 1',
          department: null,
          approvers: [{ type: 'role', role: 'ADMIN' }],
          mode: 'or',
          enabled: true
        }
      ]
    }
  ],
  freeze: [
    { table: 'T_COST_PINGGU_DTL', condition: 'GOODSID = :new_GOODSID', enabled: true },
    { table: 'T_COST_PINGGU_DTL_LQ', condition: 'GOODSID = :new_GOODSID', enabled: true }
  ],
  display: [
    {
      key: 'goods',
      title: '物料清单',
      region: 'master',
      source: 'COST_GOODS_PRICE',
      columns: [
        { field: 'GOODSID', label: '物料ID' },
        { field: 'GOODSNAME', label: '物料名称' },
        { field: 'PRICE', label: '参考价格', precision: 2 },
        { field: 'ZX_PRICE', label: '单价', precision: 2 }
      ]
    },
    affected('costMaterial', '成本核算（原辅料）', 'V_COST_PINGGU_MATERIAL', 'T_COST_PINGGU_DTL', true),
    affected('costPackage', '成本核算（包材）', 'V_COST_PINGGU_PACKAGE', 'T_COST_PINGGU_DTL', false),
    affected('lqMaterial', '液体成本核算（原辅料）', 'V_COST_PINGGU_MATERIAL_LQ', 'T_COST_PINGGU_DTL_LQ', false),
    affected('lqPackage', '液体成本核算（包材）', 'V_COST_PINGGU_PACKAGE_LQ', 'T_COST_PINGGU_DTL_LQ', false)
  ],
  propagation: 'end',
  notify
};
