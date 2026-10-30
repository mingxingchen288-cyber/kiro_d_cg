/**
 * 端到端用例准备数据的纯函数（tests/e2e/data.ts）：测试成本单的复制命令、单价与执行价比较、WP-15、复制对话框的行文字、汇总行文字。
 * 用 vitest 在 Node 中跑（不起浏览器和后端）。
 */
import { describe, expect, it } from 'vitest';
import type { PageView, ViewField } from '../../src/contracts/page-view';
import { type DocRecord, copyPlan, copyRowLabel, pricedRow, samePrice, summaryTexts, wp15 } from './data';

function field(name: string, extra: Partial<ViewField> = {}): ViewField {
  return {
    name,
    label: name,
    type: 'text',
    scale: null,
    source: 'own',
    calculated: false,
    visible: true,
    editable: true,
    required: false,
    width: null,
    pinned: null,
    dictType: null,
    lookup: null,
    ...extra
  } as ViewField;
}

const view = {
  master: {
    entity: 'COST_PINGGU',
    primaryKey: 'DOCID',
    fields: [
      field('DOCID', { editable: false, type: 'number' }),
      field('GOODSID', { type: 'number' }),
      field('GOODSNAME', { editable: false, fillWritable: true }),
      field('PROJECTNO', { editable: false }),
      field('APEX_PL', { type: 'number' }),
      field('TOTAL_FL', { type: 'number', calculated: true, editable: false, scale: 2 }),
      field('MEMO')
    ]
  },
  details: [
    {
      entity: 'COST_MATERIAL',
      primaryKey: 'DTLID',
      parentKey: 'DOCID',
      fields: [
        field('DTLID', { editable: false, type: 'number' }),
        field('DOCID', { editable: false, type: 'number' }),
        field('GOODSID', { type: 'number' }),
        field('PRICE', { type: 'number', scale: 2 }),
        field('COST_BATCH', { type: 'number', calculated: true, editable: false })
      ]
    }
  ]
} as unknown as PageView;

const source: DocRecord = {
  master: {
    entity: 'COST_PINGGU',
    rowKey: '2550',
    values: {
      DOCID: '2550',
      GOODSID: '11652',
      GOODSNAME: '250mg乙酰唑胺片',
      PROJECTNO: 'P1',
      APEX_PL: '1000000',
      TOTAL_FL: '6428.32',
      MEMO: '32131231212121212222'
    }
  },
  details: {
    COST_MATERIAL: [
      {
        entity: 'COST_MATERIAL',
        rowKey: '206323',
        values: { DTLID: '206323', DOCID: '2550', GOODSID: '25', PRICE: '75', COST_BATCH: '750' }
      },
      {
        entity: 'COST_MATERIAL',
        rowKey: '206325',
        values: { DTLID: '206325', DOCID: '2550', GOODSID: '115', PRICE: '63', COST_BATCH: '157.5' }
      }
    ]
  }
};

describe('测试成本单', () => {
  it('单价与执行价比较：按数值文本比较，任一为空时算不同（空单价保存时会被当成改价）', () => {
    expect(samePrice('75', '75.00')).toBe(true);
    expect(samePrice('0.0840', '0.084')).toBe(true);
    expect(samePrice('452.1825', '418.61205')).toBe(false);
    expect(samePrice(null, null)).toBe(false);
    expect(samePrice('', '0')).toBe(false);
  });

  it('只带单价等于执行价的明细：2550 的硬脂酸镁 63 对执行价 75 不带', () => {
    const keep = pricedRow(
      new Map([
        ['25', '75'],
        ['115', '75']
      ])
    );
    expect(source.details.COST_MATERIAL.filter(keep).map(r => r.rowKey)).toEqual(['206323']);
  });

  it('复制命令：主表新增带能写的字段（含随 Lookup 回填写库的产品名称），不带主键、计算字段和不能写的字段；备注换成标记', () => {
    let n = 0;
    const plan = copyPlan(view, source, {
      keep: pricedRow(new Map([['25', '75']])),
      master: { MEMO: 'PF_TEST e01.spec.ts:16' },
      tmp: () => `tmp-${(n += 1)}`
    });
    expect(plan.masterId).toBe('tmp-1');
    expect(plan.document).toEqual({
      entity: 'COST_PINGGU',
      master: {
        op: 'add',
        clientRowId: 'tmp-1',
        values: { GOODSID: '11652', GOODSNAME: '250mg乙酰唑胺片', APEX_PL: '1000000', MEMO: 'PF_TEST e01.spec.ts:16' }
      },
      details: [{ entity: 'COST_MATERIAL', op: 'add', clientRowId: 'tmp-2', values: { GOODSID: '25', PRICE: '75' } }]
    });
    expect([...plan.rows]).toEqual([['206323', 'tmp-2']]);
  });
});

describe('核对用的文字', () => {
  it('WP-15：最多 8 位小数，按第 9 位四舍五入', () => {
    expect(wp15('100040.37610619469026548672566')).toBe('100040.37610619');
    expect(wp15('94720.93141592920353982300884')).toBe('94720.93141593');
    expect(wp15('-0.123456785')).toBe('-0.12345679');
    expect(wp15('25.14')).toBe('25.14');
  });

  it('复制对话框中明细行的文字：除主键外前三个可见字段，按小数位显示，空值不显示', () => {
    expect(copyRowLabel(view.details[0], source.details.COST_MATERIAL[0].values)).toBe('2550 / 25 / 75.00');
    expect(copyRowLabel(view.details[0], { DOCID: '2550', GOODSID: null, PRICE: '75' })).toBe('2550 / 75.00');
  });

  it('汇总行的文字：按字段的小数位显示，没有汇总值的字段不出现', () => {
    expect(summaryTexts(view.master.fields, { TOTAL_FL: '6503857.1849', APEX_PL: null })).toEqual({
      TOTAL_FL: '6503857.18'
    });
  });
});
