/**
 * T-FC-4 新建页面向导（FC-07）与扩展配置（FC-08）：
 * - 按向导生成物料清单页的请求与 C09 样例一致；审计默认开启、明细显示方式默认多 Tab；改为关闭审计后请求中 `audit` 为 false；
 *   单表页不显示明细显示方式，请求仍带 `detailMode`；序列不存在时提示先建序列，不能继续生成；
 * - 实体的必须审批字段规则、默认值、对比；审批流的 SQL 审批人和审批人填写的参数。
 */
import { describe, expect, it } from 'vitest';
import { ApprovalFlowEditor } from '../../src/modules/config/approval/flow-editor';
import { type NodeRow, toContent } from '../../src/modules/config/approval/flow-model';
import { ItemEditor } from '../../src/modules/config/core/item-editor';
import { cleanApprovalRequired, defaultValue } from '../../src/modules/config/entity/entity-model';
import { WizardState, menuGroups } from '../../src/modules/config/wizard/wizard-state';
import { createBackend, notifier } from './support';

function goodsColumns(exists = true) {
  return {
    primaryKey: 'GOODSID',
    sequence: { name: 'T_COST_GOODS_SEQ', exists },
    columns: [
      { name: 'GOODSID', type: 'number', label: 'GOODSID', inTable: true },
      { name: 'GOODSNAME', type: 'text', label: 'GOODSNAME', inTable: true },
      { name: 'ZX_PRICE', type: 'number', label: '执行价', inTable: true },
      { name: 'LAST_PRICE', type: 'number', label: 'LAST_PRICE', inTable: false }
    ]
  };
}

async function fillGoodsPage(wizard: WizardState) {
  wizard.state.parentMenu = 'cost';
  wizard.state.title = '物料清单及成本';
  wizard.setPageCode('goods_price_manage');
  expect(wizard.next()).toBe(true);
  const master = wizard.state.master;
  master.readView = 'T_COST_GOODS_PRICE_V';
  master.table = 'T_COST_GOODS';
  master.name = '物料清单';
  await wizard.importColumns(master);
  master.entity = 'COST_GOODS_PRICE';
}

describe('新建页面向导（FC-07）', () => {
  it('归属菜单从菜单配置的分组中选；页面编码只保留大写字母、数字、下划线', async () => {
    const backend = createBackend();
    const menus = await backend.store.loadAll('menu');
    expect(menuGroups(menus)).toEqual([{ label: '成本', value: 'cost' }]);
    const wizard = new WizardState(backend.api, backend.store);
    wizard.setPageCode('goods-price manage');
    expect(wizard.state.pageCode).toBe('GOODSPRICEMANAGE');
  });

  it('生成物料清单页：请求与 C09 样例一致，审计默认开启、明细显示方式默认多 Tab', async () => {
    const backend = createBackend();
    backend.http.on('POST', '/api/config/wizard/columns', goodsColumns());
    backend.http.on('POST', '/api/config/wizard/generate', { items: [] });
    const wizard = new WizardState(backend.api, backend.store);
    expect([wizard.state.audit, wizard.state.detailMode, wizard.state.layout]).toEqual([true, 'tabs', 'single']);
    await fillGoodsPage(wizard);
    expect(backend.http.callsTo('POST', '/api/config/wizard/columns')[0].body).toEqual({ readView: 'T_COST_GOODS_PRICE_V', table: 'T_COST_GOODS' });
    expect(wizard.next()).toBe(true);
    expect(await wizard.generate()).toBe(true);

    const body = backend.http.callsTo('POST', '/api/config/wizard/generate')[0].body as Record<string, unknown>;
    expect(body).toMatchObject({
      parentMenu: 'cost',
      pageCode: 'GOODS_PRICE_MANAGE',
      title: '物料清单及成本',
      layout: 'single',
      detailMode: 'tabs',
      audit: true,
      details: []
    });
    expect(body.master).toEqual({
      entity: 'COST_GOODS_PRICE',
      name: '物料清单',
      table: 'T_COST_GOODS',
      readView: 'T_COST_GOODS_PRICE_V',
      freezable: true,
      erpColumns: [],
      labels: { ZX_PRICE: '执行价' }
    });
  });

  it('FC-14 输入"T_COST_GOODS"列出表和视图（同旧系统 searchDbObjects，两个字符起查）；导入的标题是列注释', async () => {
    const backend = createBackend();
    backend.http.on('POST', '/api/config/schema/objects', {
      objects: [
        { name: 'T_COST_GOODS', type: 'table' },
        { name: 'T_COST_GOODS_PRICE_V', type: 'view' }
      ]
    });
    const wizard = new WizardState(backend.api, backend.store);
    await wizard.searchObjects('T');
    expect(backend.http.callsTo('POST', '/api/config/schema/objects')).toHaveLength(0);
    expect(wizard.state.objectOptions).toEqual([]);
    await wizard.searchObjects('T_COST_GOODS');
    expect(backend.http.callsTo('POST', '/api/config/schema/objects')[0].body).toEqual({ keyword: 'T_COST_GOODS' });
    expect(wizard.state.objectOptions).toEqual([
      { label: 'T_COST_GOODS', value: 'T_COST_GOODS', kind: '表' },
      { label: 'T_COST_GOODS_PRICE_V', value: 'T_COST_GOODS_PRICE_V', kind: '视图' }
    ]);
    // 液体成本核算主表：后端给出的标题是列注释（COST_PERBOX 每盒成本），没有注释的列是列名；生成时只提交和列名不同的标题
    backend.http.on('POST', '/api/config/wizard/columns', {
      primaryKey: 'DOCID',
      sequence: { name: 'T_COST_PINGGU_LQ_SEQ', exists: true },
      columns: [
        { name: 'DOCID', type: 'number', label: 'DOCID', inTable: true },
        { name: 'COST_PERBOX', type: 'number', label: '每盒成本', inTable: true }
      ]
    });
    const master = wizard.state.master;
    master.table = 'T_COST_PINGGU_LQ';
    await wizard.importColumns(master);
    expect(master.columns.map(c => c.label)).toEqual(['DOCID', '每盒成本']);
    expect(wizard.request().master.labels).toEqual({ COST_PERBOX: '每盒成本' });
  });

  it('管理员关闭审计：请求中 audit 为 false；单表页仍带 detailMode', async () => {
    const backend = createBackend();
    backend.http.on('POST', '/api/config/wizard/columns', goodsColumns());
    backend.http.on('POST', '/api/config/wizard/generate', { items: [] });
    const wizard = new WizardState(backend.api, backend.store);
    await fillGoodsPage(wizard);
    wizard.state.audit = false;
    expect(wizard.next()).toBe(true);
    await wizard.generate();
    const body = backend.http.callsTo('POST', '/api/config/wizard/generate')[0].body as Record<string, unknown>;
    expect([body.audit, body.detailMode, body.layout]).toEqual([false, 'tabs', 'single']);
  });

  it('序列 T_COST_GOODS_SEQ 不存在：提示先建序列，不能进入下一步，也不发生成请求', async () => {
    const backend = createBackend();
    backend.http.on('POST', '/api/config/wizard/columns', goodsColumns(false));
    const wizard = new WizardState(backend.api, backend.store);
    await fillGoodsPage(wizard);
    expect(wizard.state.master.importError).toBe('序列 T_COST_GOODS_SEQ 不存在，请先在数据库中建好序列再生成（平台不创建序列）');
    expect(wizard.next()).toBe(false);
    expect(wizard.state.errors).toContain('序列 T_COST_GOODS_SEQ 不存在，请先在数据库中建好序列再生成（平台不创建序列）');
    expect(await wizard.generate()).toBe(false);
    expect(backend.http.callsTo('POST', '/api/config/wizard/generate')).toHaveLength(0);
  });

  it('调整了显示、编辑：随请求提交 fieldDefaults，生成后实体里没有时补存', async () => {
    const backend = createBackend();
    backend.http.on('POST', '/api/config/wizard/columns', goodsColumns());
    backend.http.on('POST', '/api/config/wizard/generate', () => {
      // 后端向导生成实体（只写标题，不写 fieldDefaults）
      backend.items.set('entity/COST_GOODS_PRICE_NEW', {
        type: 'entity',
        key: 'COST_GOODS_PRICE_NEW',
        name: '物料清单',
        version: 1,
        content: { table: 'T_COST_GOODS', primaryKey: 'GOODSID', freezable: true, fields: [] }
      });
      return { items: [] };
    });
    const wizard = new WizardState(backend.api, backend.store);
    await fillGoodsPage(wizard);
    wizard.state.master.entity = 'COST_GOODS_PRICE_NEW';
    wizard.state.master.columns.find(c => c.name === 'GOODSNAME')!.editable = false;
    wizard.state.master.columns.find(c => c.name === 'LAST_PRICE')!.visible = false;
    expect(wizard.next()).toBe(true);
    expect(await wizard.generate()).toBe(true);
    const body = backend.http.callsTo('POST', '/api/config/wizard/generate')[0].body as { master: Record<string, unknown> };
    expect(body.master.fieldDefaults).toEqual({ GOODSNAME: { editable: false }, LAST_PRICE: { visible: false } });
    expect(backend.get('entity', 'COST_GOODS_PRICE_NEW')?.content.fieldDefaults).toEqual({ GOODSNAME: { editable: false }, LAST_PRICE: { visible: false } });
  });
});

describe('扩展配置（FC-08）', () => {
  it('物料实体：ERP 物料改执行价必须审批，新增行默认值，与上次价格对比', async () => {
    const backend = createBackend();
    const editor = new ItemEditor(backend.store, 'entity', notifier());
    await editor.open('COST_GOODS_PRICE');
    const content = editor.state.current!.content;
    content.approvalRequired = cleanApprovalRequired([
      { fields: ['ZX_PRICE'], when: { logic: 'AND', conditions: [{ field: 'ISERP', op: 'eq', value: '1' }] }, sourcePages: ['GOODS_PRICE_MANAGE'] }
    ]);
    content.fields.find(f => f.name === 'ISERP')!.default = defaultValue({ type: 'options', text: '0,1', builtin: 'currentUserName' });
    content.fields.find(f => f.name === 'ZX_PRICE')!.compare = { mode: 'field', field: 'PRICE', format: 'both' };
    expect(await editor.save()).toBe(2);
    const saved = backend.get('entity', 'COST_GOODS_PRICE')!.content as Record<string, unknown>;
    expect(saved.approvalRequired).toEqual([
      { fields: ['ZX_PRICE'], when: { logic: 'AND', conditions: [{ field: 'ISERP', op: 'eq', value: '1' }] }, sourcePages: ['GOODS_PRICE_MANAGE'] }
    ]);
    const fields = saved.fields as Array<Record<string, unknown>>;
    expect(fields.find(f => f.name === 'ISERP')?.default).toEqual({ type: 'options', value: ['0', '1'] });
    expect(fields.find(f => f.name === 'ZX_PRICE')?.compare).toEqual({ mode: 'field', field: 'PRICE', format: 'both' });
  });

  it('审批流：SQL 审批人带绑定变量，最终批准时填写的生效日期参数', async () => {
    const backend = createBackend();
    const editor = new ApprovalFlowEditor(backend.store, backend.api, 'GOODS_PRICE_MANAGE', notifier());
    await editor.load();
    const flow = editor.addFlow();
    editor.applyOperations({ COST_GOODS_PRICE: ['modify'] });
    const node = editor.addRow() as NodeRow;
    editor.applyApprovers(node, [{ type: 'sql', sql: 'SELECT USER_ID FROM T_COST_USER_DEPT WHERE DEPT_ID = :deptId', binds: { deptId: 'user_departmentId' } }]);
    editor.applyParams([{ name: 'effectiveDate', label: '生效日期', type: 'date', source: 'manual', required: true }]);
    const content = toContent(flow);
    expect(content.levels[0].nodes[0].approvers).toEqual([
      { type: 'sql', sql: 'SELECT USER_ID FROM T_COST_USER_DEPT WHERE DEPT_ID = :deptId', binds: { deptId: 'user_departmentId' } }
    ]);
    expect(content.params).toEqual([{ name: 'effectiveDate', label: '生效日期', type: 'date', source: 'manual', required: true }]);
  });
});
