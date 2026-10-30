/**
 * 编辑缓冲（FP-04）：按页面实例记录未保存的修改、新增行和删除标记，提供改动标记、撤销和重做（表格和表单共用），
 * 保存时把全部修改生成一个命令的 documents（C02 第 1 节）。不引用 AG Grid 和 Vue。
 *
 * - 行用（实体、行标识）定位：已保存的行为 rowKey，新增行为 clientRowId（`tmp-` 加 UUID）。每行记下所属单据（主表行的标识）。
 * - 正式数据（从后端读到的值）经 `load` 登记，只用来判断"改回原值"，不进撤销历史。
 * - 每次调用 set、addRow、deleteRow 是一个撤销步骤；`batch` 把其中的多次调用合成一步（Lookup 回填、复制、粘贴）。
 *   历史按行记录修改前后的状态，撤销把这些行恢复为修改前，重做恢复为修改后。
 * - 行的先后（命令中的单据和行、新增行的位置）按行进入未保存修改的先后（`seq`），撤销、重做后与当时相同。
 */
// 本模块用相对路径引用 contracts：vitest 没有配置 `@` 别名（vitest.config.ts 归 assembly）
import { isDecimalText, numbersConsistent } from '../../contracts/decimal-text';
import type { DetailChange, DocumentPatch, FieldValue, FieldValues, MasterChange } from '../../contracts/command';
import type { FieldType } from '../../contracts/page-view';

export interface BufferEntity {
  primaryKey: string;
  /** 明细实体关联主表的字段；主表为 null */
  parentKey: string | null;
  fieldTypes: Record<string, FieldType>;
}

export interface BufferSchema {
  master: string;
  entities: Record<string, BufferEntity>;
  /**
   * 能否写进命令（C02 第 1 节）：计算字段、只读的 ERP 列、`erpRow.column`、主键和主从关联字段不能写。
   * `current` 为这一行的当前值，`isNew` 表示新增行。
   */
  writable(entity: string, field: string, current: FieldValues, isNew: boolean): boolean;
}

export interface RowId {
  entity: string;
  id: string;
}

interface PendingRow {
  entity: string;
  id: string;
  recordId: string;
  isNew: boolean;
  /** 新增行为全部值；已保存的行为改过的字段 */
  values: FieldValues;
  deleted: boolean;
  /** 新增行插在哪一行之后（同一实体、同一单据中），null 表示最前面 */
  after: string | null;
  /**
   * 这一行进入未保存修改的先后（从没有修改变为有修改时取下一个号，之后不变）。命令中单据和行的先后、新增行的先后都按它，
   * 随行的状态一起记进撤销历史，撤销、重做后与当时相同；不按 Map 的插入顺序，因为撤销、重做会把行重新插到最后。
   */
  seq: number;
}

type Step = Map<string, { before: PendingRow | undefined; after: PendingRow | undefined }>;
type RowChange = Omit<PendingRow, 'seq'>;

const keyOf = (entity: string, id: string) => `${entity}\u0000${id}`;
const copyRow = (row: PendingRow | undefined) => (row ? { ...row, values: { ...row.values } } : undefined);

export class EditBuffer {
  private readonly committedRows = new Map<string, { recordId: string; values: FieldValues }>();
  private readonly pending = new Map<string, PendingRow>();
  private undoStack: Step[] = [];
  private redoStack: Step[] = [];
  private current_step: Step | null = null;
  private depth = 0;
  private lastSeq = 0;

  constructor(
    private readonly schema: BufferSchema,
    private readonly newId: () => string = () => `tmp-${crypto.randomUUID()}`
  ) {}

  // ---- 正式数据

  /** 登记从后端读到的行；`recordKey` 为行所属单据的主表主键（主表行为它自己） */
  load(entity: string, rows: Array<{ rowKey: string; recordKey: string; values: FieldValues }>) {
    for (const row of rows)
      this.committedRows.set(keyOf(entity, row.rowKey), { recordId: row.recordKey, values: { ...row.values } });
  }

  committed(entity: string, id: string): FieldValues | undefined {
    return this.committedRows.get(keyOf(entity, id))?.values;
  }

  // ---- 读取

  /** 当前值：正式数据叠加未保存的修改；新增行为它的全部值 */
  current(entity: string, id: string): FieldValues | undefined {
    const row = this.pending.get(keyOf(entity, id));
    if (row?.isNew) return { ...row.values };
    const committed = this.committed(entity, id);
    if (!committed) return undefined;
    return row ? { ...committed, ...row.values } : { ...committed };
  }

  /** 行所属的单据 */
  recordOf(entity: string, id: string): string | undefined {
    return this.pending.get(keyOf(entity, id))?.recordId ?? this.committedRows.get(keyOf(entity, id))?.recordId;
  }

  isNew(entity: string, id: string) {
    return Boolean(this.pending.get(keyOf(entity, id))?.isNew);
  }

  isDeleted(entity: string, id: string) {
    return Boolean(this.pending.get(keyOf(entity, id))?.deleted);
  }

  isChanged(entity: string, id: string, field: string) {
    const row = this.pending.get(keyOf(entity, id));
    return Boolean(row && !row.isNew && field in row.values);
  }

  /** 已保存的行中改过的字段 */
  changedFields(entity: string, id: string): string[] {
    const row = this.pending.get(keyOf(entity, id));
    return row && !row.isNew ? Object.keys(row.values) : [];
  }

  /** 某单据中某实体的新增行，按插入位置；主表的新增行 `recordId` 传 null */
  newRows(entity: string, recordId: string | null): Array<{ id: string; after: string | null }> {
    const rows: Array<{ id: string; after: string | null }> = [];
    for (const row of this.rows()) {
      if (row.entity !== entity || !row.isNew) continue;
      if (entity !== this.schema.master && row.recordId !== recordId) continue;
      rows.push({ id: row.id, after: row.after });
    }
    return rows;
  }

  /** 有未保存修改（修改、新增、删除）的行数 */
  get size() {
    return this.pending.size;
  }

  get dirty() {
    return this.pending.size > 0;
  }

  /** 有未保存修改的单据 */
  dirtyRecords(): string[] {
    return [...new Set(this.rows().map(r => r.recordId))];
  }

  /** 有未保存修改的行 */
  dirtyRows(): RowId[] {
    return this.rows().map(r => ({ entity: r.entity, id: r.id }));
  }

  get canUndo() {
    return this.undoStack.length > 0;
  }

  get canRedo() {
    return this.redoStack.length > 0;
  }

  /** 未保存修改的完整状态，供测试比较 */
  snapshot() {
    return [...this.pending.values()]
      .map(r => copyRow(r)!)
      .sort((a, b) => keyOf(a.entity, a.id).localeCompare(keyOf(b.entity, b.id)));
  }

  // ---- 修改

  /** 把多次修改合成一个撤销步骤 */
  batch<T>(fn: () => T): T {
    this.beginBatch();
    try {
      return fn();
    } finally {
      this.endBatch();
    }
  }

  /** 开始一个撤销步骤（例如表格粘贴开始时）；与 endBatch 成对调用，可以嵌套 */
  beginBatch() {
    this.depth += 1;
    if (this.depth === 1) this.current_step = new Map();
  }

  /** 结束撤销步骤；返回这一步改到的行 */
  endBatch(): RowId[] {
    if (this.depth === 0) return [];
    this.depth -= 1;
    if (this.depth > 0) return [];
    const step = this.current_step!;
    this.current_step = null;
    // 去掉前后相同的行；整步没有变化时不进历史
    for (const [key, change] of step) if (sameRow(change.before, change.after)) step.delete(key);
    if (step.size === 0) return [];
    this.undoStack.push(step);
    this.redoStack = [];
    return touched(step);
  }

  set(entity: string, id: string, field: string, value: FieldValue) {
    this.setValues(entity, id, { [field]: value });
  }

  setValues(entity: string, id: string, values: FieldValues) {
    this.batch(() => {
      const key = keyOf(entity, id);
      const existing = this.pending.get(key);
      if (existing?.deleted) return;
      if (existing?.isNew) {
        this.write(key, { ...existing, values: { ...existing.values, ...values } });
        return;
      }
      const committed = this.committedRows.get(key);
      if (!committed) return;
      const changes = { ...existing?.values };
      for (const [field, value] of Object.entries(values)) {
        if (this.same(entity, field, value, committed.values[field] ?? null)) delete changes[field];
        else changes[field] = value;
      }
      const next: RowChange | undefined =
        Object.keys(changes).length > 0
          ? { entity, id, recordId: committed.recordId, isNew: false, values: changes, deleted: false, after: null }
          : undefined;
      this.write(key, next);
    });
  }

  /**
   * 新增一行，返回它的 clientRowId。主表行 `recordId` 传 null（单据就是它自己）；`after` 为插在哪一行之后。
   * `values` 由调用方按默认值或复制的内容给出。
   */
  addRow(entity: string, recordId: string | null, values: FieldValues, after: string | null): string {
    const id = this.newId();
    this.batch(() => {
      this.write(keyOf(entity, id), {
        entity,
        id,
        recordId: entity === this.schema.master ? id : recordId!,
        isNew: true,
        values: { ...values },
        deleted: false,
        after
      });
    });
    return id;
  }

  /** 删除一行：已保存的行标为删除；新增行直接去掉（主表的新增行连同它的明细） */
  deleteRow(entity: string, id: string) {
    this.batch(() => {
      const key = keyOf(entity, id);
      const existing = this.pending.get(key);
      if (existing?.isNew) {
        this.write(key, undefined);
        if (entity === this.schema.master) {
          for (const [k, row] of this.pending) if (row.recordId === id) this.write(k, undefined);
        }
        return;
      }
      const committed = this.committedRows.get(key);
      if (!committed || existing?.deleted) return;
      this.write(key, {
        entity,
        id,
        recordId: committed.recordId,
        isNew: false,
        values: { ...existing?.values },
        deleted: true,
        after: null
      });
    });
  }

  undo(): RowId[] | null {
    const step = this.undoStack.pop();
    if (!step) return null;
    for (const [key, change] of step) this.restore(key, change.before);
    this.redoStack.push(step);
    return touched(step);
  }

  redo(): RowId[] | null {
    const step = this.redoStack.pop();
    if (!step) return null;
    for (const [key, change] of step) this.restore(key, change.after);
    this.undoStack.push(step);
    return touched(step);
  }

  /** 保存成功后：清空全部修改和历史 */
  clear() {
    this.pending.clear();
    this.undoStack = [];
    this.redoStack = [];
  }

  /**
   * 丢弃这些行的修改（FP-07 提交审批的单据、FP-14 按钮结果中的行）：这些行恢复为正式数据，
   * 历史中也去掉这些行；其他行的修改和历史不变。
   */
  discard(rows: RowId[]) {
    const keys = new Set(rows.map(r => keyOf(r.entity, r.id)));
    for (const key of keys) this.pending.delete(key);
    const prune = (stack: Step[]) =>
      stack.filter(step => {
        for (const key of keys) step.delete(key);
        return step.size > 0;
      });
    this.undoStack = prune(this.undoStack);
    this.redoStack = prune(this.redoStack);
  }

  /** 某些单据的全部行（含新增的） */
  rowsOfRecords(recordIds: string[]): RowId[] {
    const set = new Set(recordIds);
    return this.rows()
      .filter(r => set.has(r.recordId))
      .map(r => ({ entity: r.entity, id: r.id }));
  }

  // ---- 命令

  /** 按单据生成命令的 documents（C02 第 1 节），只含可写的字段 */
  documents(): DocumentPatch[] {
    const records = new Map<string, PendingRow[]>();
    for (const row of this.rows()) {
      const list = records.get(row.recordId) ?? [];
      list.push(row);
      records.set(row.recordId, list);
    }
    const master = this.schema.master;
    const result: DocumentPatch[] = [];
    for (const [recordId, rows] of records) {
      const masterRow = rows.find(r => r.entity === master);
      let masterChange: MasterChange;
      if (masterRow?.isNew) {
        masterChange = { op: 'add', clientRowId: recordId, values: this.writableValues(masterRow, true) };
      } else if (masterRow?.deleted) {
        result.push({ entity: master, master: { op: 'delete', rowKey: recordId }, details: [] });
        continue;
      } else {
        const changes = masterRow ? this.writableValues(masterRow, false) : {};
        masterChange = Object.keys(changes).length
          ? { op: 'modify', rowKey: recordId, changes }
          : { op: 'none', rowKey: recordId };
      }
      const details: DetailChange[] = [];
      for (const row of rows) {
        if (row.entity === master) continue;
        if (row.isNew) {
          details.push({ entity: row.entity, op: 'add', clientRowId: row.id, values: this.writableValues(row, true) });
        } else if (row.deleted) {
          details.push({ entity: row.entity, op: 'delete', rowKey: row.id });
        } else {
          const changes = this.writableValues(row, false);
          if (Object.keys(changes).length) details.push({ entity: row.entity, op: 'modify', rowKey: row.id, changes });
        }
      }
      if (masterChange.op === 'none' && details.length === 0) continue;
      result.push({ entity: master, master: masterChange, details });
    }
    return result;
  }

  // ---- 内部

  private writableValues(row: PendingRow, isNew: boolean): FieldValues {
    const current = this.current(row.entity, row.id) ?? {};
    const types = this.schema.entities[row.entity]?.fieldTypes ?? {};
    const result: FieldValues = {};
    for (const [field, value] of Object.entries(row.values)) {
      // 新增行中为空的字段不写，由后端按默认值补（WP-16）。数值字段例外，写 null：后端对没写的数值字段补 0，
      // 用户清空的单价（或 Lookup 带回的空单价）会存成 0，必填（WP-07）也检查不到；旧系统新增时同样写入空值
      if (isNew && value === null && types[field] !== 'number') continue;
      if (!this.schema.writable(row.entity, field, current, isNew)) continue;
      result[field] = value;
    }
    return result;
  }

  private same(entity: string, field: string, a: FieldValue, b: FieldValue) {
    if (a === b) return true;
    const type = this.schema.entities[entity]?.fieldTypes[field];
    return type === 'number' && isDecimalText(a) && isDecimalText(b) && numbersConsistent(a as string, b as string);
  }

  /** 未保存修改的行，按进入的先后（`seq`） */
  private rows(): PendingRow[] {
    return [...this.pending.values()].sort((a, b) => a.seq - b.seq);
  }

  /** 改一行并记入当前撤销步骤；行原来没有未保存的修改时取下一个先后号，原来有时沿用 */
  private write(key: string, change: RowChange | undefined) {
    const step = this.current_step!;
    const existing = this.pending.get(key);
    const next: PendingRow | undefined = change ? { ...change, seq: existing?.seq ?? (this.lastSeq += 1) } : undefined;
    if (!step.has(key)) step.set(key, { before: copyRow(existing), after: undefined });
    step.get(key)!.after = copyRow(next);
    this.restore(key, next);
  }

  private restore(key: string, row: PendingRow | undefined) {
    if (row) this.pending.set(key, copyRow(row)!);
    else this.pending.delete(key);
  }
}

function sameRow(a: PendingRow | undefined, b: PendingRow | undefined) {
  if (!a || !b) return a === b;
  return JSON.stringify(a) === JSON.stringify(b);
}

function touched(step: Step): RowId[] {
  return [...step.values()].map(change => {
    const row = (change.after ?? change.before)!;
    return { entity: row.entity, id: row.id };
  });
}
