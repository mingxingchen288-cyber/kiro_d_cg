/**
 * T-FC-3 校验规则的"必填"用于数值字段（FC-06）：rules-core 中数值为空按 0 计算，条件 `PRICE == null or PRICE == ''`
 * 永远不成立，所以数值字段的"必填"不生成校验规则，换成字段设置的必填（实体默认或本页面），同"表与列"的"必填"列。
 *
 * 业务例子：配置中心 → 成本核算 → 页面行为 → 原料/辅料的校验规则 → 新增一条，字段选单价、规则选必填 →
 * "设为字段必填" → 保存。保存单据时单价为空被拒绝、0 能保存，由写入管道检查（后端 tests/pipeline/test_flow.py）。
 */
import { describe, expect, it } from 'vitest';
import { loadPageCatalog } from '../../src/modules/config/core/catalog';
import { ItemEditor } from '../../src/modules/config/core/item-editor';
import type { EntityContent, PageContent } from '../../src/modules/config/core/types';
import { RuleEditor } from '../../src/modules/config/rules/rule-editor';
import { validateCondition } from '../../src/modules/config/rules/rule-model';
import { fieldRows, flagLock, flagValue } from '../../src/modules/config/views/table-fields';
import { createBackend, notifier } from './support';

async function open() {
  const backend = createBackend();
  const page = new ItemEditor(backend.store, 'page', notifier());
  await page.open('COST_PINGGU');
  const catalog = await loadPageCatalog(backend.store, 'COST_PINGGU');
  const material = catalog.tables.find(t => t.entity === 'COST_MATERIAL')!;
  const masterFields = catalog.tables[0].fields.map(f => f.name);
  const editor = () => new RuleEditor(backend.store, { pageCode: 'COST_PINGGU', table: material }, 'validate', masterFields, notifier(), page);
  return { backend, page, editor };
}

const puts = (backend: ReturnType<typeof createBackend>) =>
  backend.http.callsTo('PUT', '/api/config/items/:type/:key').map(c => ({ path: c.path, body: c.body as { content: unknown } }));

describe('校验规则的"必填"用于数值字段（FC-06）', () => {
  it('单价必填（层级"实体"）：不生成校验规则，原辅料实体的 fieldDefaults 写 PRICE 必填；表与列的"必填"显示勾选', async () => {
    const { backend, editor } = await open();
    const rules = editor();
    await rules.load();
    expect(rules.state.required).toEqual([]);

    const card = rules.add('PRICE');
    expect(rules.isNumber('PRICE')).toBe(true);
    expect(rules.toRequired(card)).toBe('');
    expect(rules.state.cards).toEqual([]);
    expect(rules.state.required).toMatchObject([{ field: 'PRICE', scope: 'entity', saved: false }]);
    expect(await rules.save()).toBe(true);

    // 只保存了实体，没有规则配置项
    expect(puts(backend).map(p => p.path)).toEqual(['/api/config/items/entity/COST_MATERIAL']);
    expect([...backend.items.values()].filter(i => i.type === 'rule')).toEqual([]);
    const entity = backend.get('entity', 'COST_MATERIAL')!.content as unknown as EntityContent;
    expect(entity.fieldDefaults).toEqual({ PRICE: { required: true } });
    expect(entity.fields).toEqual((createBackend().get('entity', 'COST_MATERIAL')!.content as unknown as EntityContent).fields);
    expect(rules.state.fieldsSaved).toBe(true);

    // 表与列（本页面范围）：单价的"必填"格显示勾选、不能取消，写明原因
    const row = fieldRows(entity, {}, 'page').find(r => r.name === 'PRICE')!;
    expect(flagValue(row, 'required', null)).toBe(true);
    expect(flagLock(row, 'required', null)).toContain('实体默认必填');

    // 再次打开：列为已保存的字段必填
    const again = editor();
    await again.load();
    expect(again.state.required).toMatchObject([{ field: 'PRICE', scope: 'entity', saved: true }]);
    expect(again.state.cards).toEqual([]);
  });

  it('单价必填（层级"本页面"）：写进成本核算页原料/辅料区的字段设置，经页面配置各区共用的页面编辑状态保存', async () => {
    const { backend, page, editor } = await open();
    const rules = editor();
    await rules.load();
    const card = rules.add('PRICE');
    rules.setLayer(card, 'page');
    expect(rules.toRequired(card)).toBe('');
    expect(rules.state.required).toMatchObject([{ field: 'PRICE', scope: 'page' }]);
    expect(await rules.save()).toBe(true);

    expect(puts(backend).map(p => p.path)).toEqual(['/api/config/items/page/COST_PINGGU']);
    const saved = backend.get('page', 'COST_PINGGU')!.content as unknown as PageContent;
    expect(saved.details![0]).toMatchObject({ entity: 'COST_MATERIAL', fields: { PRICE: { required: true } } });
    // 页面的其他内容不变
    expect({ ...saved, details: undefined }).toEqual({ ...(createBackend().get('page', 'COST_PINGGU')!.content as object), details: undefined });
    expect(page.state.current!.version).toBe(2);

    // 表与列（本页面范围）：单价的"必填"勾选，可以改
    const entity = backend.get('entity', 'COST_MATERIAL')!.content as unknown as EntityContent;
    const row = fieldRows(entity, saved.details![0].fields ?? {}, 'page').find(r => r.name === 'PRICE')!;
    expect([row.required, flagLock(row, 'required', null)]).toEqual([true, '']);
  });

  it('删除已保存的字段必填：去掉必填，字段的其他设置不变', async () => {
    const { backend, page, editor } = await open();
    page.state.current!.content.details![0].fields = { PRICE: { required: true, width: 90 } };
    await page.save();
    const rules = editor();
    await rules.load();
    expect(rules.state.required).toMatchObject([{ field: 'PRICE', scope: 'page', saved: true }]);
    rules.removeRequired(rules.state.required[0]);
    expect(await rules.save()).toBe(true);
    const saved = backend.get('page', 'COST_PINGGU')!.content as unknown as PageContent;
    expect(saved.details![0].fields).toEqual({ PRICE: { width: 90 } });
  });

  it('文本字段的"必填"仍然生成条件（文本为空时规则中是 null，条件成立），不换成字段必填', async () => {
    const { editor } = await open();
    const rules = editor();
    await rules.load();
    expect(validateCondition('GOODSNAME', 'required', '')).toBe("GOODSNAME == null or GOODSNAME == ''");
    const card = rules.add('GOODSNAME');
    expect(rules.toRequired(card)).toBe('GOODSNAME 不是数值字段，用"生成条件"');
    expect(rules.state.cards).toHaveLength(1);
  });
});
