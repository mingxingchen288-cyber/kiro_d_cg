/**
 * 第 7 批页面显示的配置界面（模拟验证）：
 * - "表与列"的"千分位"（实体字段 `grouping`，同旧系统 SectionTables.vue 第 99 行）和"字典可填写"（页面字段 `dictFreeText`，
 *   同旧系统编辑器"下拉（可填写）"）读出 seed 的设置，改了以后写回实体和页面；
 * - "Lookup管理"的"配置显示列"（同旧系统 LookupPanel.vue 的显示标题、宽度）读出 seed 的标题和宽度，保存时写回 `columns`。
 * 配置取 `backend/seed/config/`。
 */
import { describe, expect, it } from 'vitest';
import type { EntityContent, LookupContent, PageContent } from '../../src/modules/config/core/types';
import { columnItems, columnNames, sourceColumnsOf } from '../../src/modules/config/views/lookup-columns';
import { applyRows, fieldRows } from '../../src/modules/config/views/table-fields';
import { seedItems } from './support';

const seed = <T>(type: string, key: string) => seedItems().find(i => i.type === type && i.key === key)!.content as T;

describe('表与列：千分位、字典可填写', () => {
  it('成本核算主表：批量、每批物料成本勾着千分位，备注、产品名称（文本）没有；分类选了字典 pingguClass 并勾着可填写', () => {
    const entity = seed<EntityContent>('entity', 'COST_PINGGU');
    const page = seed<PageContent>('page', 'COST_PINGGU');
    const rows = fieldRows(entity, page.master.fields ?? {}, 'page');
    const row = (name: string) => rows.find(r => r.name === name)!;
    expect([
      row('APEX_PL').grouping,
      row('TOTAL_COST').grouping,
      row('MEMO').grouping,
      row('GOODSNAME').grouping
    ]).toEqual([true, true, false, false]);
    expect(rows.filter(r => r.grouping)).toHaveLength(20);
    expect([row('PINGGU_CLASS').dictType, row('PINGGU_CLASS').dictFreeText]).toEqual(['pingguClass', true]);
  });

  it('给包装规格勾上千分位、取消批量的千分位：实体中前者写 grouping，后者去掉；分类取消可填写后页面只留 dictType', () => {
    const entity = seed<EntityContent>('entity', 'COST_PINGGU');
    const page = seed<PageContent>('page', 'COST_PINGGU');
    const rows = fieldRows(entity, page.master.fields ?? {}, 'page');
    rows.find(r => r.name === 'P_PERPACK')!.grouping = true;
    rows.find(r => r.name === 'APEX_PL')!.grouping = false;
    rows.find(r => r.name === 'PINGGU_CLASS')!.dictFreeText = false;
    const applied = applyRows(entity, page.master.fields ?? {}, rows, 'page');
    const field = (name: string) => applied.entity.fields.find(f => f.name === name)!;
    expect(field('P_PERPACK').grouping).toBe(true);
    expect('grouping' in field('APEX_PL')).toBe(false);
    expect(field('TOTAL_COST').grouping).toBe(true);
    expect(applied.settings.PINGGU_CLASS).toEqual({ dictType: 'pingguClass' });
  });
});

describe('Lookup管理：显示列的标题和宽度', () => {
  it('产品选择 costGoods：对话框按数据源的列列出，已配置的列带旧系统的标题和宽度，没配置的标题为字段名', () => {
    const lookup = seed<LookupContent>('lookup', 'costGoods');
    const rows = sourceColumnsOf(['GOODSID', 'GOODSNAME', 'MA_NO', 'NOT_SHOWN'], lookup.columns, lookup.keywordColumns);
    expect(rows).toEqual([
      { name: 'GOODSID', show: true, keyword: true, label: '产品ID', width: 80 },
      { name: 'GOODSNAME', show: true, keyword: true, label: '产品名称', width: 200 },
      { name: 'MA_NO', show: true, keyword: true, label: '注册证号', width: null },
      { name: 'NOT_SHOWN', show: false, keyword: false, label: 'NOT_SHOWN', width: null }
    ]);
  });

  it('保存显示列：改了标题或填了宽度的列写成对象，标题同字段名又没宽度的只写列名', () => {
    const lookup = seed<LookupContent>('lookup', 'costUser');
    const rows = sourceColumnsOf(['USERNAME', 'REAL_NAME', 'DEPT'], lookup.columns, lookup.keywordColumns);
    rows[1].width = 120;
    rows[2].show = true;
    expect(columnItems(rows)).toEqual([
      { column: 'USERNAME', label: '工号', width: 200 },
      { column: 'REAL_NAME', label: '姓名', width: 120 },
      'DEPT'
    ]);
    expect(columnNames(columnItems(rows))).toEqual(['USERNAME', 'REAL_NAME', 'DEPT']);
  });
});
