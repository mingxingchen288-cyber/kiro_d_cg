/**
 * T-FC-3 规则表单（FC-06）：编辑并保存 C06 第 5 节的两条规则；
 * T-FC-1 行权限（FC-04）：可视化条件生成与旧系统相同的 SQL，自定义 SQL 原样保存；
 * T-FC-2 表单布局（FC-03）：拖动和缩放按整列整行，不超出 24 列，保存的布局符合 C05，退出不保存时恢复原布局。
 */
import { describe, expect, it } from 'vitest';
import { loadPageCatalog } from '../../src/modules/config/core/catalog';
import { ItemEditor } from '../../src/modules/config/core/item-editor';
import { FormLayoutModel, toGrid } from '../../src/modules/config/layout/form-layout';
import { columnPolicy, columnRows, generateRowSql, rowPolicyForm, rowPolicyValue } from '../../src/modules/config/role/role-model';
import { RuleEditor } from '../../src/modules/config/rules/rule-editor';
import { matchCondition, validateCondition } from '../../src/modules/config/rules/rule-model';
import { createBackend, notifier } from './support';

describe('规则表单（FC-06）', () => {
  it('包材明细的批量：多公式两条分支，分支条件由"分支字段 + 正则 + 值"生成，保存内容与 C06 样例相同', async () => {
    const backend = createBackend();
    const catalog = await loadPageCatalog(backend.store, 'COST_PINGGU');
    const pack = catalog.tables.find(t => t.entity === 'COST_PACKAGE')!;
    const editor = new RuleEditor(backend.store, { pageCode: 'COST_PINGGU', table: pack }, 'calc', catalog.tables[0].fields.map(f => f.name), notifier());
    await editor.load();
    expect(editor.state.cards).toEqual([]);

    const card = editor.add('BATCH_QTY');
    expect(card.content).toMatchObject({ layer: 'entity', target: 'COST_PACKAGE', category: 'calc', order: 10 });
    card.multi = true;
    card.content.branches = [
      {
        when: matchCondition('GOODSNAME', 'regex', '桶|说明书|小盒|标签|瓶|盖|干燥剂|序列化'),
        expression: 'master.APEX_PL / master.P_PERPACK * (1 + EXADD_MATER / 100)'
      },
      { when: matchCondition('GOODSNAME', 'regex', '硬片|铝箔|复合膜'), expression: 'PER_HL * master.APEX_PL * (1 + EXADD_MATER / 100) / 1000000' }
    ];
    expect(await editor.save()).toBe(true);
    expect(backend.get('rule', card.key)?.content).toEqual({
      layer: 'entity',
      target: 'COST_PACKAGE',
      category: 'calc',
      field: 'BATCH_QTY',
      order: 10,
      dataItems: [],
      branches: [
        { when: "matches(GOODSNAME, '桶|说明书|小盒|标签|瓶|盖|干燥剂|序列化')", expression: 'master.APEX_PL / master.P_PERPACK * (1 + EXADD_MATER / 100)' },
        { when: "matches(GOODSNAME, '硬片|铝箔|复合膜')", expression: 'PER_HL * master.APEX_PL * (1 + EXADD_MATER / 100) / 1000000' }
      ]
    });
  });

  it('条件里的值含单引号：用双引号括起，不转义（ZEN 的字符串没有转义，同后端 expressions._string）', () => {
    expect(matchCondition('GOODSNAME', 'equals', "乙酰'唑胺")).toBe(`GOODSNAME == "乙酰'唑胺"`);
    expect(matchCondition('GOODSNAME', 'contains', "乙酰'唑胺")).toBe(`contains(GOODSNAME, "乙酰'唑胺")`);
    expect(matchCondition('GOODSNAME', 'notContains', "乙酰'唑胺")).toBe(`not contains(GOODSNAME, "乙酰'唑胺")`);
    expect(validateCondition('GOODSNAME', 'pattern', "乙酰'唑胺|硬片")).toBe(`not matches(GOODSNAME, "乙酰'唑胺|硬片")`);
    // 不含单引号时仍用单引号
    expect(matchCondition('GOODSNAME', 'equals', '乙酰唑胺')).toBe("GOODSNAME == '乙酰唑胺'");
  });

  it('ERP 来的物料整行不能编辑：可编辑规则，可视化条件，保存内容与 C06 样例相同', async () => {
    const backend = createBackend();
    const catalog = await loadPageCatalog(backend.store, 'GOODS_PRICE_MANAGE');
    const editor = new RuleEditor(backend.store, { pageCode: 'GOODS_MANAGE', table: catalog.tables[0] }, 'editable', [], notifier());
    await editor.load();
    const card = editor.add(null);
    card.content.when = { logic: 'AND', conditions: [{ source: 'row', field: 'ISERP', op: 'eq', value: '1' }] };
    expect(await editor.save()).toBe(true);
    expect(backend.get('rule', card.key)?.content).toEqual({
      layer: 'page',
      target: 'GOODS_MANAGE',
      category: 'ui',
      field: null,
      order: 10,
      when: { logic: 'AND', conditions: [{ source: 'row', field: 'ISERP', op: 'eq', value: '1' }] },
      effect: { editable: false }
    });
    // 再次打开：规则出现在主表的可编辑规则中
    await editor.load();
    expect(editor.state.cards.map(c => c.key)).toEqual([card.key]);
  });
});

describe('行权限（FC-04）', () => {
  it('可视化：创建人等于当前用户，生成 SQL 与 C06 第 8 节样例相同', () => {
    const form = rowPolicyForm(null);
    form.conditions.push({ field: 'CREATE_BY', fieldLabel: '创建人', op: 'eq', valueType: 'dynamic', value: '${username}' });
    expect(rowPolicyValue(form)).toEqual({
      mode: 'visual',
      logic: 'AND',
      conditions: [{ field: 'CREATE_BY', fieldLabel: '创建人', op: 'eq', valueType: 'dynamic', value: '${username}' }],
      sql: 'CREATE_BY = ${username}'
    });
    expect(
      generateRowSql('OR', [
        { field: 'DEPT_ID', fieldLabel: '部门', op: 'in', valueType: 'static', value: '10, 12' },
        { field: 'GOODSNAME', fieldLabel: '产品', op: 'like', valueType: 'static', value: "乙酰'唑胺" }
      ])
    ).toBe("DEPT_ID IN (10, 12) OR GOODSNAME LIKE '%乙酰''唑胺%'");
  });

  it('自定义 SQL：原样保存为字符串；保存角色时行权限写在页面下', async () => {
    const backend = createBackend();
    const editor = new ItemEditor(backend.store, 'role', notifier());
    editor.create('COST_ACCOUNTANT', '成本会计');
    const form = rowPolicyForm(null);
    form.mode = 'sql';
    form.sql = 'CREATE_BY = ${username}';
    editor.state.current!.content.pages = { COST_PINGGU: { buttons: ['system:save', 'master:copyRow'], rows: rowPolicyValue(form) } };
    expect(await editor.save()).toBe(1);
    expect(backend.get('role', 'COST_ACCOUNTANT')?.content).toEqual({
      name: '成本会计',
      admin: false,
      pages: { COST_PINGGU: { buttons: ['system:save', 'master:copyRow'], rows: 'CREATE_BY = ${username}' } }
    });
  });

  it('列权限：把单价改为不可编辑，只写这一个字段（同 C06 样例）', () => {
    const rows = columnRows(
      [
        { name: 'PRICE', label: '单价', role: 'input', source: 'own' },
        { name: 'QTY', label: '数量', role: 'input', source: 'own' }
      ],
      {},
      undefined
    );
    rows[0].editable = false;
    expect(columnPolicy(rows)).toEqual({ PRICE: { visible: true, editable: false } });
  });
});

describe('表单布局（FC-03）', () => {
  it('从空布局开始编辑：每行 3 个字段；拖动和缩放按整列整行、不超出 24 列，压住的字段往下推', () => {
    const model = new FormLayoutModel(['GOODSNAME', 'QTY', 'MEMO', 'USESTATUS'], []);
    model.begin();
    expect(model.state.cells).toEqual([
      { field: 'GOODSNAME', x: 0, y: 0, w: 8, h: 1 },
      { field: 'QTY', x: 8, y: 0, w: 8, h: 1 },
      { field: 'MEMO', x: 16, y: 0, w: 8, h: 1 },
      { field: 'USESTATUS', x: 0, y: 1, w: 8, h: 1 }
    ]);
    // 把备注拉宽到 30 列：只到右边界
    model.resize('MEMO', 30, 1);
    expect(model.state.cells.find(c => c.field === 'MEMO')).toEqual({ field: 'MEMO', x: 16, y: 0, w: 8, h: 1 });
    // 产品名称拉宽到 12.4 列（拖动 12.4 格的像素）→ 12 列，压住数量，数量往下推
    model.resize('GOODSNAME', toGrid(12.4 * 40, 40), 1);
    expect(model.state.cells.find(c => c.field === 'GOODSNAME')).toEqual({ field: 'GOODSNAME', x: 0, y: 0, w: 12, h: 1 });
    expect(model.state.cells.find(c => c.field === 'QTY')).toEqual({ field: 'QTY', x: 8, y: 1, w: 8, h: 1 });
    // 状态拖到 x=20：宽 8，贴右边界 x=16
    model.move('USESTATUS', 20, 3);
    expect(model.state.cells.find(c => c.field === 'USESTATUS')).toEqual({ field: 'USESTATUS', x: 16, y: 3, w: 8, h: 1 });
    for (const cell of model.result()) {
      expect(cell.x).toBeGreaterThanOrEqual(0);
      expect(cell.x + cell.w).toBeLessThanOrEqual(24);
      expect(cell.w).toBeGreaterThanOrEqual(1);
      expect(cell.h).toBeGreaterThanOrEqual(1);
    }
  });

  it('保存布局：写进页面主表的 formLayout，所有人共用；退出编辑不保存时恢复原布局', async () => {
    const backend = createBackend();
    const page = new ItemEditor(backend.store, 'page', notifier());
    await page.open('COST_PINGGU');
    const model = new FormLayoutModel(['GOODSNAME', 'APEX_PL'], [{ field: 'GOODSNAME', x: 0, y: 0, w: 12, h: 1 }]);

    model.begin();
    model.move('GOODSNAME', 6, 2);
    model.cancel();
    expect(model.state.cells).toEqual([{ field: 'GOODSNAME', x: 0, y: 0, w: 12, h: 1 }]);
    expect(model.state.editing).toBe(false);

    model.begin();
    model.add('APEX_PL');
    model.resize('APEX_PL', 24, 2);
    page.state.current!.content.master.formLayout = model.result();
    expect(await page.save()).toBe(2);
    model.commit();
    expect(backend.get('page', 'COST_PINGGU')?.content.master).toMatchObject({
      formLayout: [
        { field: 'GOODSNAME', x: 0, y: 0, w: 12, h: 1 },
        { field: 'APEX_PL', x: 0, y: 1, w: 24, h: 2 }
      ]
    });
  });
});
