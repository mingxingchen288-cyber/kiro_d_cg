/**
 * T-FP-1 编辑缓冲（FP-04）：修改、新增、删除、改动标记、撤销重做、生成命令（C02 第 1 节）。
 *
 * 例子取自验收场景：成本单 2550 的原辅料明细 206323（硬脂酸镁）、206324，成本单 2551 的明细 103681；E01 的 200680。
 * 基于属性的测试（fast-check）：任意编辑序列全部撤销后回到初始状态，撤销后重做回到撤销前；改回原值时修改和标记消失；
 * 删除未保存的新增行不进入命令；生成的命令符合 C02，只含修改的字段。
 */
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { DocumentPatch } from '../../src/contracts/command';
import { array } from '../../src/contracts/schema';
import { type BufferSchema, EditBuffer } from '../../src/modules/page/edit-buffer';

const MASTER = 'COST_PINGGU';
const DETAIL = 'COST_MATERIAL';

const FIELDS = {
  [MASTER]: { DOCID: 'number', MEMO: 'text', QTY: 'number', TOTAL_COST: 'number' },
  [DETAIL]: {
    DTLID: 'number',
    DOCID: 'number',
    GOODSID: 'number',
    MEMO: 'text',
    PRICE: 'number',
    CUSTOMER_SPECIFIED: 'boolean'
  }
} as const;

/** 主键、主从关联字段和计算字段 TOTAL_COST 不能写进命令 */
const SCHEMA: BufferSchema = {
  master: MASTER,
  entities: {
    [MASTER]: { primaryKey: 'DOCID', parentKey: null, fieldTypes: FIELDS[MASTER] },
    [DETAIL]: { primaryKey: 'DTLID', parentKey: 'DOCID', fieldTypes: FIELDS[DETAIL] }
  },
  writable: (entity, field) =>
    !['DOCID', 'DTLID', 'TOTAL_COST'].includes(field) && field in FIELDS[entity as keyof typeof FIELDS]
};

const MASTERS = [
  { rowKey: '2550', values: { DOCID: '2550', MEMO: null, QTY: '10', TOTAL_COST: '45.00' } },
  { rowKey: '2551', values: { DOCID: '2551', MEMO: '原备注', QTY: '5', TOTAL_COST: '20.00' } }
];
const DETAILS = [
  {
    rowKey: '206323',
    recordKey: '2550',
    values: { DTLID: '206323', DOCID: '2550', GOODSID: '115', MEMO: null, PRICE: '75', CUSTOMER_SPECIFIED: false }
  },
  {
    rowKey: '206324',
    recordKey: '2550',
    values: { DTLID: '206324', DOCID: '2550', GOODSID: '116', MEMO: null, PRICE: '70', CUSTOMER_SPECIFIED: true }
  },
  {
    rowKey: '103681',
    recordKey: '2551',
    values: { DTLID: '103681', DOCID: '2551', GOODSID: '25', MEMO: null, PRICE: '75', CUSTOMER_SPECIFIED: false }
  }
];

function newBuffer() {
  let next = 0;
  const buffer = new EditBuffer(SCHEMA, () => `tmp-00000000-0000-4000-8000-${String(++next).padStart(12, '0')}`);
  buffer.load(
    MASTER,
    MASTERS.map(r => ({ ...r, recordKey: r.rowKey }))
  );
  buffer.load(DETAIL, DETAILS);
  return buffer;
}

describe('编辑缓冲：例子', () => {
  it('只改明细时主表为 none，明细为 modify', () => {
    const buffer = newBuffer();
    buffer.set(DETAIL, '206323', 'MEMO', '测试');
    expect(buffer.size).toBe(1);
    expect(buffer.isChanged(DETAIL, '206323', 'MEMO')).toBe(true);
    expect(buffer.documents()).toEqual([
      {
        entity: MASTER,
        master: { op: 'none', rowKey: '2550' },
        details: [{ entity: DETAIL, op: 'modify', rowKey: '206323', changes: { MEMO: '测试' } }]
      }
    ]);
  });

  it('同一张单据的主表和明细合成一项；不同单据各一项；同一格改两次取最后的值', () => {
    const buffer = newBuffer();
    buffer.load(MASTER, [
      { rowKey: '200680', recordKey: '200680', values: { DOCID: '200680', MEMO: null, QTY: '1', TOTAL_COST: '1' } }
    ]);
    buffer.set(DETAIL, '206323', 'MEMO', '测');
    buffer.set(DETAIL, '206323', 'MEMO', '测试');
    buffer.set(MASTER, '2550', 'MEMO', '主表');
    buffer.set(DETAIL, '206324', 'CUSTOMER_SPECIFIED', false);
    buffer.set(MASTER, '200680', 'MEMO', '测试');
    expect(buffer.documents()).toEqual([
      {
        entity: MASTER,
        master: { op: 'modify', rowKey: '2550', changes: { MEMO: '主表' } },
        details: [
          { entity: DETAIL, op: 'modify', rowKey: '206323', changes: { MEMO: '测试' } },
          { entity: DETAIL, op: 'modify', rowKey: '206324', changes: { CUSTOMER_SPECIFIED: false } }
        ]
      },
      { entity: MASTER, master: { op: 'modify', rowKey: '200680', changes: { MEMO: '测试' } }, details: [] }
    ]);
  });

  it('当前值是正式数据叠加未保存的修改；改回原值时修改和标记消失（数值按 C01 判定，75 与 75.00 相同）', () => {
    const buffer = newBuffer();
    buffer.set(DETAIL, '206323', 'PRICE', '80');
    expect(buffer.current(DETAIL, '206323')).toMatchObject({ PRICE: '80', GOODSID: '115' });
    buffer.set(DETAIL, '206323', 'PRICE', '75.00');
    expect(buffer.isChanged(DETAIL, '206323', 'PRICE')).toBe(false);
    expect(buffer.size).toBe(0);
    expect(buffer.documents()).toEqual([]);
  });

  it('新增明细：命令中为 add，只带可写且有值的字段，不带主键和关联字段', () => {
    const buffer = newBuffer();
    const id = buffer.addRow(
      DETAIL,
      '2550',
      { DTLID: null, DOCID: '2550', GOODSID: '115', PRICE: '3.50', MEMO: null },
      '206323'
    );
    expect(buffer.isNew(DETAIL, id)).toBe(true);
    expect(buffer.newRows(DETAIL, '2550')).toEqual([{ id, after: '206323' }]);
    expect(buffer.documents()).toEqual([
      {
        entity: MASTER,
        master: { op: 'none', rowKey: '2550' },
        details: [{ entity: DETAIL, op: 'add', clientRowId: id, values: { GOODSID: '115', PRICE: '3.50' } }]
      }
    ]);
  });

  it('删除已保存的行标为删除，命令中为 delete；删除主表行时不列出明细', () => {
    const buffer = newBuffer();
    buffer.deleteRow(DETAIL, '206324');
    expect(buffer.isDeleted(DETAIL, '206324')).toBe(true);
    buffer.set(DETAIL, '103681', 'MEMO', '改');
    buffer.deleteRow(MASTER, '2551');
    expect(buffer.documents()).toEqual([
      {
        entity: MASTER,
        master: { op: 'none', rowKey: '2550' },
        details: [{ entity: DETAIL, op: 'delete', rowKey: '206324' }]
      },
      { entity: MASTER, master: { op: 'delete', rowKey: '2551' }, details: [] }
    ]);
  });

  it('新增主表行连同新增明细：主表 add，明细 add；删除这一行后都不进入命令', () => {
    const buffer = newBuffer();
    const master = buffer.addRow(MASTER, null, { DOCID: null, MEMO: '新单据', QTY: '0', TOTAL_COST: '0' }, null);
    const detail = buffer.addRow(DETAIL, master, { DTLID: null, DOCID: null, GOODSID: '115', PRICE: '75' }, null);
    expect(buffer.documents()).toEqual([
      {
        entity: MASTER,
        master: { op: 'add', clientRowId: master, values: { MEMO: '新单据', QTY: '0' } },
        details: [{ entity: DETAIL, op: 'add', clientRowId: detail, values: { GOODSID: '115', PRICE: '75' } }]
      }
    ]);
    buffer.deleteRow(MASTER, master);
    expect(buffer.isNew(DETAIL, detail)).toBe(false);
    expect(buffer.documents()).toEqual([]);
  });

  it('撤销、重做：表格和表单共用一个历史；batch 中的多次修改是一步', () => {
    const buffer = newBuffer();
    buffer.set(DETAIL, '206323', 'PRICE', '80');
    buffer.batch(() => {
      buffer.set(DETAIL, '206323', 'GOODSID', '117');
      buffer.set(DETAIL, '206323', 'MEMO', '换料');
    });
    expect(buffer.undo()).toEqual([{ entity: DETAIL, id: '206323' }]);
    expect(buffer.current(DETAIL, '206323')).toMatchObject({ PRICE: '80', GOODSID: '115', MEMO: null });
    buffer.redo();
    expect(buffer.current(DETAIL, '206323')).toMatchObject({ PRICE: '80', GOODSID: '117', MEMO: '换料' });
    buffer.undo();
    buffer.undo();
    expect(buffer.canUndo).toBe(false);
    expect(buffer.documents()).toEqual([]);
  });

  it('新的修改清空重做；保存成功后清空修改和历史', () => {
    const buffer = newBuffer();
    buffer.set(MASTER, '2550', 'MEMO', 'a');
    buffer.undo();
    buffer.set(MASTER, '2550', 'MEMO', 'b');
    expect(buffer.canRedo).toBe(false);
    buffer.clear();
    expect(buffer.size).toBe(0);
    expect(buffer.canUndo).toBe(false);
  });

  it('丢弃某些行的修改（按钮操作后这些行显示后端的值）：其他行的修改和新增行保留，历史中不再有这些行', () => {
    const buffer = newBuffer();
    buffer.set(DETAIL, '206323', 'PRICE', '80');
    buffer.set(DETAIL, '103681', 'PRICE', '90');
    const added = buffer.addRow(DETAIL, '2551', { GOODSID: '116', PRICE: '12' }, null);
    buffer.discard([{ entity: DETAIL, id: '206323' }]);
    expect(buffer.isChanged(DETAIL, '206323', 'PRICE')).toBe(false);
    expect(buffer.isChanged(DETAIL, '103681', 'PRICE')).toBe(true);
    expect(buffer.isNew(DETAIL, added)).toBe(true);
    buffer.undo();
    buffer.undo();
    expect(buffer.canUndo).toBe(false);
    expect(buffer.current(DETAIL, '206323')).toMatchObject({ PRICE: '75' });
  });
});

// ---- 基于属性的测试

type Op =
  | { kind: 'set'; entity: string; pick: number; field: string; value: string | boolean | null }
  | { kind: 'add'; entity: string; pick: number }
  | { kind: 'delete'; entity: string; pick: number }
  | { kind: 'batch'; ops: Op[] };

const TEXTS = [null, '', '测试', '原备注', '换料'];
const NUMBERS = [null, '0', '75', '75.00', '80', '3.50', '10', '5'];

const setOp = (entity: string, fields: string[]) =>
  fc.record({
    kind: fc.constant('set' as const),
    entity: fc.constant(entity),
    pick: fc.nat(20),
    field: fc.constantFrom(...fields),
    value: fc.oneof(fc.constantFrom(...TEXTS, ...NUMBERS), fc.boolean())
  });

const simpleOp: fc.Arbitrary<Op> = fc.oneof(
  setOp(MASTER, ['MEMO', 'QTY', 'TOTAL_COST']),
  setOp(DETAIL, ['GOODSID', 'MEMO', 'PRICE', 'CUSTOMER_SPECIFIED']),
  fc.record({ kind: fc.constant('add' as const), entity: fc.constantFrom(MASTER, DETAIL), pick: fc.nat(20) }),
  fc.record({ kind: fc.constant('delete' as const), entity: fc.constantFrom(MASTER, DETAIL), pick: fc.nat(20) })
);
const anyOp: fc.Arbitrary<Op> = fc.oneof(
  { weight: 4, arbitrary: simpleOp },
  {
    weight: 1,
    arbitrary: fc.record({ kind: fc.constant('batch' as const), ops: fc.array(simpleOp, { maxLength: 4 }) })
  }
);

/** 当前能看到的行（已保存的和新增的），按实体 */
function visibleRows(buffer: EditBuffer, entity: string) {
  const saved = (entity === MASTER ? MASTERS : DETAILS).map(r => r.rowKey);
  const records =
    entity === MASTER ? [] : [...MASTERS.map(r => r.rowKey), ...buffer.newRows(MASTER, null).map(r => r.id)];
  const added =
    entity === MASTER
      ? buffer.newRows(MASTER, null).map(r => r.id)
      : records.flatMap(rec => buffer.newRows(DETAIL, rec).map(r => r.id));
  return [...saved, ...added].filter(id => !buffer.isDeleted(entity, id));
}

function apply(buffer: EditBuffer, op: Op) {
  if (op.kind === 'batch') {
    buffer.batch(() => op.ops.forEach(inner => apply(buffer, inner)));
    return;
  }
  if (op.kind === 'add') {
    if (op.entity === MASTER) buffer.addRow(MASTER, null, { MEMO: null, QTY: '0' }, null);
    else {
      const records = visibleRows(buffer, MASTER);
      if (records.length)
        buffer.addRow(DETAIL, records[op.pick % records.length], { GOODSID: '115', PRICE: '75' }, null);
    }
    return;
  }
  const rows = visibleRows(buffer, op.entity);
  if (!rows.length) return;
  const id = rows[op.pick % rows.length];
  if (op.kind === 'delete') buffer.deleteRow(op.entity, id);
  else buffer.set(op.entity, id, op.field, op.value);
}

describe('编辑缓冲：基于属性的测试', () => {
  it('任意编辑序列全部撤销后回到初始状态', () => {
    fc.assert(
      fc.property(fc.array(anyOp, { maxLength: 30 }), ops => {
        const buffer = newBuffer();
        const initial = buffer.snapshot();
        ops.forEach(op => apply(buffer, op));
        while (buffer.canUndo) buffer.undo();
        expect(buffer.snapshot()).toEqual(initial);
        expect(buffer.documents()).toEqual([]);
        expect(buffer.size).toBe(0);
      })
    );
  });

  it('撤销若干步后再重做同样的步数，回到撤销前', () => {
    fc.assert(
      fc.property(fc.array(anyOp, { maxLength: 30 }), fc.nat(30), (ops, steps) => {
        const buffer = newBuffer();
        ops.forEach(op => apply(buffer, op));
        const before = buffer.snapshot();
        const commands = buffer.documents();
        let undone = 0;
        while (undone < steps && buffer.canUndo) {
          buffer.undo();
          undone += 1;
        }
        for (let i = 0; i < undone; i += 1) buffer.redo();
        expect(buffer.snapshot()).toEqual(before);
        expect(buffer.documents()).toEqual(commands);
      })
    );
  });

  it('把改过的字段改回原值，修改和标记消失', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...DETAILS),
        fc.constantFrom('GOODSID', 'MEMO', 'PRICE'),
        fc.constantFrom(...TEXTS, ...NUMBERS),
        (row, field, value) => {
          const buffer = newBuffer();
          const original = row.values[field as keyof typeof row.values];
          buffer.set(DETAIL, row.rowKey, field, value);
          buffer.set(DETAIL, row.rowKey, field, original);
          expect(buffer.isChanged(DETAIL, row.rowKey, field)).toBe(false);
          expect(buffer.size).toBe(0);
          expect(buffer.documents()).toEqual([]);
        }
      )
    );
  });

  it('删除未保存的新增行，命令中没有这一行', () => {
    fc.assert(
      fc.property(fc.array(anyOp, { maxLength: 20 }), ops => {
        const buffer = newBuffer();
        ops.forEach(op => apply(buffer, op));
        const id = buffer.addRow(DETAIL, '2550', { GOODSID: '999', PRICE: '1' }, null);
        buffer.deleteRow(DETAIL, id);
        const rows = buffer.documents().flatMap(d => d.details);
        expect(rows.some(r => r.op === 'add' && r.clientRowId === id)).toBe(false);
      })
    );
  });

  it('生成的命令符合 C02，只含修改过的可写字段，值等于当前值', () => {
    fc.assert(
      fc.property(fc.array(anyOp, { maxLength: 30 }), ops => {
        const buffer = newBuffer();
        ops.forEach(op => apply(buffer, op));
        const documents = buffer.documents();
        expect(array(DocumentPatch).parse(structuredClone(documents))).toEqual(documents);
        const committed = new Map([...MASTERS, ...DETAILS].map(r => [r.rowKey, r.values as Record<string, unknown>]));
        for (const document of documents) {
          const rows = [{ entity: MASTER, ...document.master }, ...document.details];
          for (const row of rows) {
            if (row.op === 'modify') {
              expect(Object.keys(row.changes).length).toBeGreaterThan(0);
              for (const [field, value] of Object.entries(row.changes)) {
                expect(SCHEMA.writable(row.entity, field, {}, false)).toBe(true);
                expect(value).not.toEqual(committed.get(row.rowKey)![field]);
                expect(buffer.current(row.entity, row.rowKey)![field]).toEqual(value);
              }
            }
            if (row.op === 'add') {
              for (const field of Object.keys(row.values))
                expect(SCHEMA.writable(row.entity, field, {}, true)).toBe(true);
            }
          }
        }
      })
    );
  });
});
