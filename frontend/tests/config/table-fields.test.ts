/**
 * FC-09 表与列：显示、编辑、必填显示实际结果，不能改的格子写明原因；保存列时按 config 的 CF-14 同步页面保存操作的
 * 可写字段。配置取 `backend/seed/config/` 的成本核算（实体 COST_PINGGU、COST_MATERIAL、COST_PACKAGE，页面 COST_PINGGU，
 * 操作 COST_PINGGU.save），后端为模拟实现（support.ts）。
 */
import { describe, expect, it } from 'vitest';
import { ItemEditor } from '../../src/modules/config/core/item-editor';
import type { OperationContent, PageContent } from '../../src/modules/config/core/types';
import { type FlagScope, fieldRows, flagLock, flagValue, saveColumns } from '../../src/modules/config/views/table-fields';
import { createBackend, notifier, seedItems, useSeed } from './support';

const SAVE_OPERATION = 'COST_PINGGU.save';

async function openPage() {
  const backend = createBackend();
  useSeed(backend);
  const n = notifier();
  const page = new ItemEditor(backend.store, 'page', n);
  await page.open('COST_PINGGU');
  return { backend, n, page };
}

type Opened = Awaited<ReturnType<typeof openPage>>;

/** 打开页面中一张表的列表格（同 TableFieldsCard 的 load），`save` 即"保存列" */
async function openTable({ backend, n, page }: Opened, entityCode: string, scope: FlagScope) {
  const entity = new ItemEditor(backend.store, 'entity', n);
  await entity.open(entityCode);
  const content = page.state.current!.content;
  const area = content.master.entity === entityCode ? content.master : content.details!.find(d => d.entity === entityCode)!;
  const rows = fieldRows(entity.state.current!.content, area.fields ?? {}, scope);
  const erpRow = entity.state.current!.content.erpRow ?? null;
  return {
    row: (name: string) => rows.find(r => r.name === name)!,
    lock: (name: string, flag: 'visible' | 'editable' | 'required' = 'editable') => flagLock(rows.find(r => r.name === name)!, flag, erpRow),
    shown: (name: string, flag: 'visible' | 'editable' | 'required' = 'editable') => flagValue(rows.find(r => r.name === name)!, flag, erpRow),
    save: () =>
      saveColumns({ store: backend.store, notify: n, page, entity, operation: new ItemEditor(backend.store, 'operation', n), area, rows, scope })
  };
}

const operationOf = (backend: Opened['backend']) => backend.get('operation', SAVE_OPERATION)!.content as unknown as OperationContent;
const writable = (backend: Opened['backend'], entity: string) => operationOf(backend).writableFields?.[entity] ?? [];

describe('表与列显示实际能否编辑（FC-09）', () => {
  it('字段本身不能编辑的：系统字段 DOCID、计算字段 TOTAL_COST、明细中只在视图里的 GOODSNAME 编辑格不勾、不能改，写明原因；备注 MEMO 可编辑', async () => {
    const opened = await openPage();
    const master = await openTable(opened, 'COST_PINGGU', 'page');
    expect([master.lock('DOCID'), master.shown('DOCID')]).toEqual(['系统字段（由平台写入），不能编辑', false]);
    expect([master.lock('TOTAL_COST'), master.shown('TOTAL_COST')]).toEqual(['计算字段（由规则计算），不能编辑', false]);
    expect([master.lock('MEMO'), master.shown('MEMO')]).toEqual(['', true]);

    const material = await openTable(opened, 'COST_MATERIAL', 'page');
    expect([material.lock('GOODSNAME'), material.shown('GOODSNAME')]).toEqual(['只在视图中、没有写入列，不能编辑', false]);
    // 实体默认范围同样不能改
    const materialDefaults = await openTable(opened, 'COST_MATERIAL', 'entity');
    expect(materialDefaults.lock('GOODSNAME')).toBe('只在视图中、没有写入列，不能编辑');
  });

  it('实体默认锁住批量 APEX_PL：本页面范围不能勾并写明原因；在实体默认范围放开并保存后，保存操作的可写字段多了 APEX_PL', async () => {
    const opened = await openPage();
    const { backend } = opened;
    // 先在"实体默认"范围把批量设为不可编辑并保存（用户报告问题时 seed 中就是这样），保存操作随之去掉 APEX_PL
    const lock = await openTable(opened, 'COST_PINGGU', 'entity');
    lock.row('APEX_PL').editable = false;
    expect(await lock.save()).toBe(true);
    const locked = writable(backend, 'COST_PINGGU');
    expect(locked).not.toContain('APEX_PL');
    expect(locked).toContain('MEMO');

    const page = await openTable(opened, 'COST_PINGGU', 'page');
    expect(page.lock('APEX_PL')).toBe('实体默认不可编辑（所有页面），切到“实体默认”修改');
    expect(page.shown('APEX_PL')).toBe(false);

    const defaults = await openTable(opened, 'COST_PINGGU', 'entity');
    expect([defaults.lock('APEX_PL'), defaults.shown('APEX_PL')]).toEqual(['', false]);
    defaults.row('APEX_PL').editable = true;
    const materialBefore = writable(backend, 'COST_MATERIAL');
    expect(await defaults.save()).toBe(true);

    expect(new Set(writable(backend, 'COST_PINGGU'))).toEqual(new Set([...locked, 'APEX_PL']));
    expect(writable(backend, 'COST_MATERIAL')).toEqual(materialBefore);
    expect((backend.get('entity', 'COST_PINGGU')!.content.fieldDefaults as Record<string, unknown>).APEX_PL).toBeUndefined();
    // 操作只改可写字段，其他内容与 seed 相同
    const seed = seedItems().find(i => i.type === 'operation' && i.key === SAVE_OPERATION)!.content;
    expect({ ...operationOf(backend), writableFields: null }).toEqual({ ...seed, writableFields: null });
    expect((await openTable(opened, 'COST_PINGGU', 'page')).lock('APEX_PL')).toBe('');
  });

  it('本页面范围取消备注 MEMO 的编辑并保存：页面只多写 MEMO 的 editable: false，保存操作的可写字段里没有 MEMO', async () => {
    const opened = await openPage();
    const { backend } = opened;
    const seedPage = seedItems().find(i => i.type === 'page' && i.key === 'COST_PINGGU')!.content as unknown as PageContent;
    expect(writable(backend, 'COST_PINGGU')).toContain('MEMO');

    const master = await openTable(opened, 'COST_PINGGU', 'page');
    master.row('MEMO').editable = false;
    expect(await master.save()).toBe(true);

    expect(writable(backend, 'COST_PINGGU')).not.toContain('MEMO');
    expect(writable(backend, 'COST_MATERIAL')).toContain('MEMO');
    const saved = backend.get('page', 'COST_PINGGU')!;
    const content = saved.content as unknown as PageContent;
    expect(content.master.fields).toEqual({ ...seedPage.master.fields, MEMO: { editable: false } });
    expect(content.details).toEqual(seedPage.details);
    expect([saved.version, backend.get('operation', SAVE_OPERATION)!.version]).toEqual([2, 2]);
    expect(opened.n.messages.filter(m => m.kind === 'error')).toEqual([]);
  });
});

describe('求和（C06 第 3 节 aggregate，同旧系统列表格的"求和"）', () => {
  it('成本核算主表的总成本、原辅料的金额已勾选求和；勾选主表批量 APEX_PL 并保存：页面只多写 APEX_PL 的 aggregate: sum', async () => {
    const opened = await openPage();
    const { backend } = opened;
    const seedPage = seedItems().find(i => i.type === 'page' && i.key === 'COST_PINGGU')!.content as unknown as PageContent;
    const master = await openTable(opened, 'COST_PINGGU', 'page');
    expect([master.row('TOTAL_COST').aggregate, master.row('DOCID').aggregate, master.row('APEX_PL').aggregate]).toEqual([true, false, false]);
    const material = await openTable(opened, 'COST_MATERIAL', 'page');
    expect(material.row('COST_BATCH').aggregate).toBe(true);

    master.row('APEX_PL').aggregate = true;
    expect(await master.save()).toBe(true);
    const content = backend.get('page', 'COST_PINGGU')!.content as unknown as PageContent;
    expect(content.master.fields).toEqual({ ...seedPage.master.fields, APEX_PL: { aggregate: 'sum' } });
    expect(content.master.fields?.TOTAL_COST).toEqual({ aggregate: 'sum' });
    expect(opened.n.messages.filter(m => m.kind === 'error')).toEqual([]);
  });
});
