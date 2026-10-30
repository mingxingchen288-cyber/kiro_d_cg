/**
 * 操作的两个按 SQL 的动作（C06 v18 第 6 节）在配置页的编辑：动作列表里有 replaceDetails、updateRows；新加的动作预填
 * 必须写的字段；按操作编辑框的写法（绑定变量"名称=主表实体.字段"每行一个、明细主键列逗号分隔）填好后保存，内容就是
 * seed 中"由BOM生成明细""同步采购价"的写法（模拟验证，后端为 contracts 的替代实现）。
 */
import { describe, expect, it } from 'vitest';
import { ItemEditor } from '../../src/modules/config/core/item-editor';
import { ACTION_OPTIONS, fromLines, fromList, newAction } from '../../src/modules/config/views/operation-form';
import { createBackend, notifier } from './support';

const BOM_SQL =
  "SELECT V.GOODSID AS GOODSID, F.PRICE AS PRICE FROM CMX.T_COST_BOM_GOODS_TREE_V V WHERE V.TREEID LIKE '-' || :goodsId || '-%'";
const PRICE_SQL =
  'SELECT D.DOCID AS DOC_ID, D.DTLID AS DTL_ID, G.PRICE AS PRICE FROM V_COST_PINGGU_MATERIAL D JOIN T_COST_GOODS G ON G.GOODSID = D.GOODSID';

describe('按 SQL 的动作（C06 第 6 节 v18）', () => {
  it('动作列表里有 replaceDetails、updateRows，新加时预填必须写的字段', () => {
    expect(ACTION_OPTIONS.map(o => o.value)).toEqual([
      'recalculate',
      'updateTargets',
      'updateRecords',
      'replaceDetails',
      'updateRows',
      'escapeHatch'
    ]);
    expect(newAction('replaceDetails')).toEqual({
      action: 'replaceDetails',
      entity: '',
      sql: '',
      binds: {}
    });
    expect(newAction('updateRows')).toEqual({
      action: 'updateRows',
      entity: '',
      sql: '',
      recordKeyColumn: '',
      rowKeyColumns: []
    });
  });

  it('新建"由BOM生成明细"和"同步采购价"两个操作并保存：内容与 seed 的写法相同', async () => {
    const backend = createBackend();
    const editor = new ItemEditor(backend.store, 'operation', notifier());

    editor.create('COST_PINGGU.generateFromBom', '由BOM生成明细');
    const bom = editor.state.current!.content;
    const replace = newAction('replaceDetails');
    if (replace.action === 'replaceDetails') {
      Object.assign(replace, {
        entity: 'COST_MATERIAL',
        sql: BOM_SQL,
        binds: fromLines('docId=COST_PINGGU.DOCID\ngoodsId=COST_PINGGU.GOODSID')
      });
    }
    Object.assign(bom, {
      label: '由BOM生成明细',
      kind: 'action',
      writableFields: { COST_MATERIAL: ['GOODSID', 'PER_HL', 'PRICE'] },
      impact: ['COST_PINGGU', 'COST_MATERIAL'],
      actions: [replace],
      propagation: 'end'
    });
    expect(await editor.save()).toBe(1);
    expect(backend.get('operation', 'COST_PINGGU.generateFromBom')?.content.actions).toEqual([
      {
        action: 'replaceDetails',
        entity: 'COST_MATERIAL',
        sql: BOM_SQL,
        binds: { docId: 'COST_PINGGU.DOCID', goodsId: 'COST_PINGGU.GOODSID' }
      }
    ]);

    editor.create('COST_PINGGU.syncPrice', '同步采购价');
    const sync = editor.state.current!.content;
    const update = newAction('updateRows');
    if (update.action === 'updateRows') {
      Object.assign(update, {
        entity: 'COST_MATERIAL',
        sql: PRICE_SQL,
        recordKeyColumn: 'DOC_ID',
        rowKeyColumns: fromList('DTL_ID')
      });
    }
    Object.assign(sync, {
      label: '同步采购价',
      kind: 'action',
      writableFields: { COST_MATERIAL: ['PRICE'] },
      impact: ['COST_PINGGU', 'COST_MATERIAL'],
      actions: [update],
      propagation: 'end'
    });
    expect(await editor.save()).toBe(1);
    expect(backend.get('operation', 'COST_PINGGU.syncPrice')?.content.actions).toEqual([
      {
        action: 'updateRows',
        entity: 'COST_MATERIAL',
        sql: PRICE_SQL,
        recordKeyColumn: 'DOC_ID',
        rowKeyColumns: ['DTL_ID']
      }
    ]);
  });
});
