/**
 * T-FC-3 审批流编辑（FC-05）：在成本核算、物料清单及成本两个页面的"审批流"中，按定稿的界面操作配出 C06 7.8、7.9、7.10
 * 三个审批流并保存，保存内容与样例相同；校验错误定位到具体的行和格子。
 */
import { describe, expect, it } from 'vitest';
import { PlatformError } from '../../src/contracts/errors';
import { ApprovalFlowEditor, detailDialog } from '../../src/modules/config/approval/flow-editor';
import { displayColumns } from '../../src/modules/config/approval/section-columns';
import { type DisplayRow, type FreezeRow, type NodeRow, operationsSummary } from '../../src/modules/config/approval/flow-model';
import { fieldChoices, insertToken, paramToken } from '../../src/modules/config/approval/params';
import { COST_TO_GOODS, GOODS_TO_COST, TECH_CUSTOMER_MATERIAL } from './flow-samples';
import { createBackend, detail, notifier } from './support';

async function openSection(pageCode: string) {
  const backend = createBackend();
  const editor = new ApprovalFlowEditor(backend.store, backend.api, pageCode, notifier());
  await editor.load();
  return { backend, editor };
}

/** 展示数据 Tab 中新增一行，再像在表格里那样改各列 */
function addBlock(editor: ApprovalFlowEditor, values: Partial<DisplayRow>) {
  const row = editor.addRow() as DisplayRow;
  if (values.region && values.region !== row.region) {
    row.region = values.region;
    editor.regionChanged(row);
  }
  Object.assign(row, values);
  return row;
}

const cost = (columns: DisplayRow['columns']) => ({ key: 'cost', title: '成本单及成本变化', region: 'master' as const, source: 'COST_PINGGU', columns });
const costColumns = [
  { field: 'DOCID', label: '单据号' },
  { field: 'GOODSNAME', label: '产品' },
  { field: 'COST_PERBOX', label: '每盒成本', precision: 4 },
  { field: 'JGF_PERQP', label: '千片加工费', precision: 2 }
];
const lineColumns = [
  { field: 'GOODSID', label: '物料' },
  { field: 'GOODSNAME', label: '物料名称' },
  { field: 'PRICE', label: '单价', precision: 2 },
  { field: 'COST_BATCH', label: '金额', precision: 2 }
];

describe('审批流配置（FC-05）', () => {
  it('打开成本核算的审批流：流程列表为空，页面表格为主表、原辅料、包材', async () => {
    const { editor } = await openSection('COST_PINGGU');
    expect(editor.state.flows).toEqual([]);
    expect(editor.state.loadError).toBe('');
    expect(editor.tables.map(t => [t.entity, t.title])).toEqual([
      ['COST_PINGGU', '成本核算'],
      ['COST_MATERIAL', '原辅料'],
      ['COST_PACKAGE', '包材']
    ]);
    expect(editor.state.directory.roles.map(r => r.value)).toEqual(['ADMIN', '007', '008']);
  });

  it('配出 7.8 成本明细改价审批并保存，保存内容与样例相同', async () => {
    const { backend, editor } = await openSection('COST_PINGGU');
    const flow = editor.addFlow();
    flow.key = 'COST_TO_GOODS';
    flow.name = '成本明细改价审批';
    expect(flow.order).toBe(1);

    // 审核操作弹窗：原辅料、包材各勾新增、修改
    editor.applyOperations({ COST_PINGGU: [], COST_MATERIAL: ['add', 'modify'], COST_PACKAGE: ['add', 'modify'] });
    expect(operationsSummary(flow.operations, editor.tables)).toBe('原辅料.新增、原辅料.修改、包材.新增、包材.修改');

    // 审批节点：第 1 级入口条件（送审条件），第 2 级会签
    editor.state.tab = 'nodes';
    const first = editor.addRow() as NodeRow;
    first.name = '管理员审批';
    editor.applyCondition(first, { conditionType: 'sql', condition: COST_TO_GOODS.levels[0].nodes[0].condition! });
    editor.applyApprovers(first, [{ type: 'role', role: 'ADMIN' }]);
    const second = editor.addRow([first._id]) as NodeRow;
    second.level = 2;
    second.name = '采购、生产会签';
    second.mode = 'and';
    // 入口条件弹窗：来源"本次待审值"、表格"原辅料"、字段"单价"插入参数，再接着写
    const priceChoice = fieldChoices('new', editor.tables, 'COST_MATERIAL', [], []).find(f => f.value === 'PRICE')!;
    let text = insertToken('', paramToken('new', priceChoice.value));
    text += ' > (SELECT NVL(ZX_PRICE, PRICE) * 1.1 FROM T_COST_GOODS WHERE GOODSID = ';
    text = insertToken(text, paramToken('new', 'GOODSID'));
    text += ')';
    editor.applyCondition(second, { conditionType: 'sql', condition: text });
    editor.applyApprovers(second, [
      { type: 'role', role: '008' },
      { type: 'role', role: '007' }
    ]);

    // 冻结节点：直接写表名和关联条件
    editor.state.tab = 'freeze';
    const freeze = editor.addRow() as FreezeRow;
    freeze.table = 'T_COST_GOODS';
    editor.applyCondition(freeze, { condition: 'GOODSID = :new_GOODSID' });

    // 展示数据：主表、原辅料、包材、受影响的物料清单
    editor.state.tab = 'display';
    addBlock(editor, cost(costColumns));
    addBlock(editor, { key: 'material', title: '原辅料', region: 'detail', source: 'COST_MATERIAL', columns: lineColumns });
    addBlock(editor, { key: 'package', title: '包材', region: 'detail', source: 'COST_PACKAGE', columns: lineColumns });
    const goods = addBlock(editor, {
      key: 'goods',
      title: '物料清单',
      region: 'affected',
      source: 'T_COST_GOODS_PRICE_V',
      condition: 'GOODSID = :new_GOODSID',
      targetTable: 'T_COST_GOODS',
      keyColumn: 'GOODSID',
      selection: 'all'
    });
    editor.applyColumns(goods, [
      { field: 'GOODSID', label: '物料ID', precision: null, width: null, targetColumn: '' },
      { field: 'GOODSNAME', label: '物料名称', precision: null, width: null, targetColumn: '' },
      { field: 'ZX_PRICE', label: '单价', precision: 2, width: null, targetColumn: '' }
    ]);
    editor.applyActions(goods, [{ action: 'updateFields', fields: [{ column: 'ZX_PRICE', value: ':new_PRICE' }] }]);
    editor.applyNotify(COST_TO_GOODS.notify!);

    const saved = await editor.saveCurrent();
    expect(saved).toEqual(COST_TO_GOODS);
    // 先校验再保存，保存请求的内容就是样例
    const validate = backend.http.callsTo('POST', '/api/config/validate');
    expect(validate).toHaveLength(1);
    const put = backend.http.callsTo('PUT', '/api/config/items/:type/:key');
    expect(put.map(c => c.params)).toEqual([{ type: 'approvalFlow', key: 'COST_TO_GOODS' }]);
    expect(put[0].body).toEqual({ name: '成本明细改价审批', content: COST_TO_GOODS });
    // 回读后显示新版本
    expect(editor.current?.version).toBe(1);
    expect(editor.current?.dirty).toBe(false);
    expect(editor.state.status).toContain('版本 1 已保存');
  });

  it('配出 7.9 技术中心客指物料变更审批：发起部门限制为技术中心，没有冻结节点和受影响单据', async () => {
    const { backend, editor } = await openSection('COST_PINGGU');
    const flow = editor.addFlow();
    flow.key = 'TECH_CUSTOMER_MATERIAL';
    flow.name = '技术中心客指物料变更审批';
    flow.order = 2;
    editor.applyOperations({ COST_MATERIAL: ['delete', 'modify'], COST_PACKAGE: ['modify', 'delete'] });
    expect(operationsSummary(flow.operations, editor.tables)).toBe('原辅料.修改、原辅料.删除、包材.修改、包材.删除');

    editor.state.tab = 'nodes';
    const node = editor.addRow() as NodeRow;
    node.name = '管理员审批';
    expect(editor.state.directory.departments).toEqual([{ label: '技术中心 (1069)', value: '1069' }]);
    node.department = '1069';
    // 主表原值的状态从"主表原值"来源插入
    const condition = TECH_CUSTOMER_MATERIAL.levels[0].nodes[0].condition!;
    expect(condition.startsWith(paramToken('master_old', 'USESTATUS'))).toBe(true);
    editor.applyCondition(node, { conditionType: 'sql', condition });
    editor.applyApprovers(node, [{ type: 'role', role: 'ADMIN' }]);

    editor.state.tab = 'display';
    addBlock(editor, cost(costColumns));
    const withCustomer = [...lineColumns, { field: 'CUSTOMER_SPECIFIED', label: '客户指定' }];
    addBlock(editor, { key: 'material', title: '原辅料', region: 'detail', source: 'COST_MATERIAL', columns: withCustomer });
    addBlock(editor, { key: 'package', title: '包材', region: 'detail', source: 'COST_PACKAGE', columns: withCustomer });
    editor.applyNotify(TECH_CUSTOMER_MATERIAL.notify!);

    expect(await editor.saveCurrent()).toEqual(TECH_CUSTOMER_MATERIAL);
    expect(backend.get('approvalFlow', 'TECH_CUSTOMER_MATERIAL')?.content).toEqual(TECH_CUSTOMER_MATERIAL);
  });

  it('配出 7.10 物料清单改价审批：两张冻结表，四块受影响单据按修改表的主键勾选、通过后改单价', async () => {
    const { backend, editor } = await openSection('GOODS_PRICE_MANAGE');
    expect(editor.tables.map(t => t.title)).toEqual(['物料清单及成本']);
    const flow = editor.addFlow();
    flow.key = 'GOODS_TO_COST';
    flow.name = '物料清单改价审批';
    flow.order = 3;
    editor.applyOperations({ COST_GOODS_PRICE: ['modify'] });
    expect(operationsSummary(flow.operations, editor.tables)).toBe('物料清单及成本.修改');

    const node = editor.addRow() as NodeRow;
    node.name = '管理员审批';
    editor.applyCondition(node, { conditionType: 'sql', condition: 'DECODE(:new_ZX_PRICE, :old_ZX_PRICE, 0, 1) = 1' });
    editor.applyApprovers(node, [{ type: 'role', role: 'ADMIN' }]);

    editor.state.tab = 'freeze';
    for (const table of ['T_COST_PINGGU_DTL', 'T_COST_PINGGU_DTL_LQ']) {
      const row = editor.addRow() as FreezeRow;
      row.table = table;
      editor.applyCondition(row, { condition: 'GOODSID = :new_GOODSID' });
    }

    editor.state.tab = 'display';
    // 单表页没有明细：新增的块默认是主表
    const master = editor.addRow() as DisplayRow;
    expect([master.region, master.source]).toEqual(['master', 'COST_GOODS_PRICE']);
    Object.assign(master, { key: 'goods', title: '物料清单' });
    editor.applyColumns(master, GOODS_TO_COST.display![0].columns);
    for (const block of GOODS_TO_COST.display!.slice(1)) {
      const row = addBlock(editor, {
        key: block.key,
        title: block.title,
        region: 'affected',
        source: block.source,
        condition: block.condition!,
        targetTable: block.targetTable!,
        keyColumn: block.keyColumn!,
        selection: 'checked'
      });
      editor.applyColumns(row, block.columns);
      editor.applyActions(row, [{ action: 'updateFields', fields: [{ column: 'PRICE', value: 'NVL(:new_ZX_PRICE, :old_PRICE)' }] }]);
    }
    editor.applyNotify(GOODS_TO_COST.notify!);

    expect(await editor.saveCurrent()).toEqual(GOODS_TO_COST);
    expect(backend.get('approvalFlow', 'GOODS_TO_COST')?.content).toEqual(GOODS_TO_COST);
  });

  it('双击明细表：入口条件、审批人、显示列、受影响单据的通过后操作打开弹窗，节点名称、冻结表、块编码等就地编辑', () => {
    // 7.8 配置时依次双击的格子
    expect(detailDialog('name', {})).toBeNull();
    expect(detailDialog('condition', {})).toBe('condition');
    expect(detailDialog('approvers', {})).toBe('approvers');
    expect(detailDialog('table', {})).toBeNull();
    for (const column of ['key', 'title', 'region', 'source', 'targetTable', 'keyColumn', 'selection']) {
      expect(detailDialog(column, { region: 'affected' })).toBeNull();
    }
    expect(detailDialog('columns', { region: 'master' })).toBe('columns');
    expect(detailDialog('actions', { region: 'affected' })).toBe('actions');
    expect(detailDialog('actions', { region: 'detail' })).toBeNull();
  });

  it('受影响单据的"勾选方式"：下拉列表的三个选项显示名称，选"全部执行，不能取消"后格子显示它；主表、明细块显示"—"', () => {
    const column = displayColumns([], () => null).find(c => c.field === 'selection')!;
    const format = column.valueFormatter as (p: { value: unknown; data?: Partial<DisplayRow> }) => string;
    // 下拉列表格式化选项时没有行数据
    expect(['checked', 'all', 'hidden'].map(value => format({ value }))).toEqual([
      '默认全选，可取消',
      '全部执行，不能取消',
      '不给审批人看，全部执行'
    ]);
    expect(format({ value: 'all', data: { region: 'affected' } })).toBe('全部执行，不能取消');
    expect(format({ value: null, data: { region: 'master' } })).toBe('—');
    expect(format({ value: null, data: { region: 'detail' } })).toBe('—');
  });

  it('再次打开已保存的审批流：三个 Tab 的行与保存的内容一致，不改动直接保存内容不变', async () => {
    const { backend, editor } = await openSection('COST_PINGGU');
    backend.items.set('approvalFlow/COST_TO_GOODS', { type: 'approvalFlow', key: 'COST_TO_GOODS', name: '成本明细改价审批', version: 3, content: structuredClone(COST_TO_GOODS) as never });
    await editor.load();
    const flow = editor.current!;
    expect([flow.key, flow.version, flow.nodes.length, flow.freeze.length, flow.display.length]).toEqual(['COST_TO_GOODS', 3, 2, 1, 4]);
    expect(flow.nodes.map(n => [n.level, n.name, n.mode])).toEqual([
      [1, '管理员审批', 'or'],
      [2, '采购、生产会签', 'and']
    ]);
    expect(await editor.saveCurrent()).toEqual(COST_TO_GOODS);
    expect(editor.current?.version).toBe(4);
  });

  it('保存时后端返回 422：错误定位到审批节点 Tab 第 2 级那一行的审批人格，流程不变', async () => {
    const { backend, editor } = await openSection('COST_PINGGU');
    const flow = editor.addFlow();
    flow.key = 'COST_TO_GOODS';
    editor.applyOperations({ COST_MATERIAL: ['add'] });
    const first = editor.addRow() as NodeRow;
    editor.applyApprovers(first, [{ type: 'role', role: 'ADMIN' }]);
    const second = editor.addRow() as NodeRow;
    second.level = 2;
    backend.http.fail(
      'PUT',
      '/api/config/items/:type/:key',
      new PlatformError(422, 'VALIDATION_FAILED', '配置校验不通过', [detail('levels[1].nodes[0].approvers', '每个节点至少要有一个审批人', 'approvalFlow', 'COST_TO_GOODS')]),
      1
    );
    expect(await editor.saveCurrent()).toBeNull();
    expect(editor.state.problems).toEqual([
      { area: 'nodes', rowId: second._id, column: 'approvers', message: '每个节点至少要有一个审批人', path: 'levels[1].nodes[0].approvers' }
    ]);
    expect(editor.problemAt('nodes', second._id, 'approvers').map(p => p.message)).toEqual(['每个节点至少要有一个审批人']);
    expect(flow.version).toBeNull();
    expect(backend.get('approvalFlow', 'COST_TO_GOODS')).toBeUndefined();
  });

  it('校验配置：错误定位到展示数据的显示列格和流程列表的审核操作格，不发保存请求', async () => {
    const { backend, editor } = await openSection('COST_PINGGU');
    editor.addFlow();
    editor.state.tab = 'display';
    const block = editor.addRow() as DisplayRow;
    backend.failNextValidate([
      detail('display[0].columns[1].field', '字段 X 不是实体 COST_MATERIAL 的字段'),
      detail('operations', '至少一个表格要选一项审核操作')
    ]);
    expect(await editor.validateCurrent()).toBe(false);
    expect(editor.state.problems.map(p => [p.area, p.rowId, p.column])).toEqual([
      ['display', block._id, 'columns'],
      ['flow', editor.current!._key, 'operations']
    ]);
    expect(backend.http.callsTo('PUT', '/api/config/items/:type/:key')).toHaveLength(0);
  });
});
