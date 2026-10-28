/**
 * T-FP-1（链路 1 的最小部分）：编辑缓冲按（实体、行）记录修改，保存时按单据生成命令的 documents（C02 第 1 节）。
 * 例子取自验收场景：成本单 2550 原辅料第一行（DTLID 206323）改备注；E01 的 200680 改主表备注。
 */
import { describe, expect, it } from 'vitest';
import { EditBuffer } from '../../src/views/cost-pinggu/edit-buffer';

const MASTER = 'COST_PINGGU';

describe('编辑缓冲', () => {
  it('只改明细时主表为 none，明细为 modify', () => {
    const buffer = new EditBuffer(MASTER);
    buffer.set({ entity: 'COST_MATERIAL', rowKey: '206323', recordKey: '2550' }, 'MEMO', '测试');
    expect(buffer.size).toBe(1);
    expect(buffer.documents()).toEqual([
      {
        entity: MASTER,
        master: { op: 'none', rowKey: '2550' },
        details: [{ entity: 'COST_MATERIAL', op: 'modify', rowKey: '206323', changes: { MEMO: '测试' } }]
      }
    ]);
  });

  it('同一张单据的主表和明细合成一项；不同单据各一项', () => {
    const buffer = new EditBuffer(MASTER);
    buffer.set({ entity: 'COST_MATERIAL', rowKey: '206323', recordKey: '2550' }, 'MEMO', '测试');
    buffer.set({ entity: MASTER, rowKey: '2550', recordKey: '2550' }, 'MEMO', '主表');
    buffer.set({ entity: 'COST_PACKAGE', rowKey: '206319', recordKey: '2550' }, 'CUSTOMER_SPECIFIED', true);
    buffer.set({ entity: MASTER, rowKey: '200680', recordKey: '200680' }, 'MEMO', '测试');
    expect(buffer.size).toBe(4);
    expect(buffer.documents()).toEqual([
      {
        entity: MASTER,
        master: { op: 'modify', rowKey: '2550', changes: { MEMO: '主表' } },
        details: [
          { entity: 'COST_MATERIAL', op: 'modify', rowKey: '206323', changes: { MEMO: '测试' } },
          { entity: 'COST_PACKAGE', op: 'modify', rowKey: '206319', changes: { CUSTOMER_SPECIFIED: true } }
        ]
      },
      { entity: MASTER, master: { op: 'modify', rowKey: '200680', changes: { MEMO: '测试' } }, details: [] }
    ]);
  });

  it('同一格改两次取最后的值；未保存的值叠加到重新读到的行上；保存成功后清空', () => {
    const buffer = new EditBuffer(MASTER);
    const ref = { entity: 'COST_MATERIAL', rowKey: '206323', recordKey: '2550' };
    buffer.set(ref, 'MEMO', '测');
    buffer.set(ref, 'MEMO', '测试');
    buffer.set(ref, 'CUSTOMER_SPECIFIED', true);
    expect(buffer.isChanged('COST_MATERIAL', '206323', 'MEMO')).toBe(true);
    expect(buffer.isChanged('COST_MATERIAL', '206323', 'PRICE')).toBe(false);
    expect(buffer.overlay('COST_MATERIAL', '206323', { MEMO: null, PRICE: '75', CUSTOMER_SPECIFIED: false })).toEqual({
      MEMO: '测试',
      PRICE: '75',
      CUSTOMER_SPECIFIED: true
    });
    buffer.clear();
    expect(buffer.size).toBe(0);
    expect(buffer.documents()).toEqual([]);
  });
});
