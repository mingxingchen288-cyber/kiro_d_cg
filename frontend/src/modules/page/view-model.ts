/**
 * 视图模型（T-FP-1）：合并正式数据、编辑缓冲中的修改和预览结果，给出每行要显示的值、行的顺序、冻结状态、
 * 单元格能否编辑和改动标记。不引用 AG Grid 和 Vue；表格经 grid-adapter 从这里取数据。
 */
import type { FieldValues, FrozenMark, ResultRow } from '../../contracts/command';
import { isDecimalText, numbersConsistent } from '../../contracts/decimal-text';
import type { CompareResult, DataRow, RecordResponse } from '../../contracts/http';
import type { PageView, ViewRegion } from '../../contracts/page-view';
import type { EvalRowResult, RuleEffect } from '../../contracts/rules';
import { EditBuffer, type RowId } from './edit-buffer';
import { fieldEditable, fieldOf, fieldWritable, regionOf } from './fields';

interface RowExtras {
  frozen: FrozenMark | null;
  compare?: Record<string, CompareResult> | null;
}

/** 界面规则的效果（C07 第 3 节 `fields`、`style`） */
interface RuleView {
  fields: EvalRowResult['fields'];
  style: EvalRowResult['style'];
}

interface Preview extends RuleView {
  computed: FieldValues;
}

export interface CellError {
  field: string | null;
  message: string;
}

const keyOf = (entity: string, id: string) => `${entity}\u0000${id}`;

export function createBuffer(view: PageView) {
  const entities = Object.fromEntries(
    [view.master, ...view.details].map(region => [
      region.entity,
      {
        primaryKey: region.primaryKey,
        parentKey: 'parentKey' in region ? (region.parentKey as string) : null,
        fieldTypes: Object.fromEntries(region.fields.map(f => [f.name, f.type]))
      }
    ])
  );
  return new EditBuffer({
    master: view.master.entity,
    entities,
    writable(entity, field, current, isNew) {
      const region = regionOf(view, entity);
      const meta = region && fieldOf(view, entity, field);
      return Boolean(region && meta && fieldWritable(region, meta, current, isNew));
    }
  });
}

export class PageModel {
  readonly buffer: EditBuffer;
  private readonly extras = new Map<string, RowExtras>();
  private readonly previews = new Map<string, Preview>();
  /** 显示求值（C07 `purpose: display`）的结果：只有界面规则的效果，没有计算值，不改显示的值 */
  private readonly displays = new Map<string, RuleView>();
  /** 已加载明细的单据：每个明细实体按后端返回顺序的行主键 */
  private readonly details = new Map<string, Record<string, string[]>>();
  private readonly effects = new Map<string, RuleEffect[]>();
  private readonly errors = new Map<string, CellError[]>();
  /** 新增行保存后取得的正式主键 → 表格中仍用的 clientRowId（FP-02：行节点不变） */
  private readonly aliases = new Map<string, string>();
  private readonly reverse = new Map<string, string>();

  constructor(
    public view: PageView,
    buffer?: EditBuffer
  ) {
    this.buffer = buffer ?? createBuffer(view);
  }

  get master() {
    return this.view.master.entity;
  }

  /** 配置变更后换成新的页面视图（FP-09）；编辑缓冲和已加载的数据保留 */
  replaceView(view: PageView) {
    this.view = view;
  }

  // ---- 正式数据

  registerMasterRows(rows: DataRow[]) {
    this.buffer.load(
      this.master,
      rows.map(r => ({ rowKey: r.rowKey, recordKey: r.rowKey, values: r.values }))
    );
    for (const row of rows)
      this.extras.set(keyOf(this.master, row.rowKey), { frozen: row.frozen, compare: row.compare });
  }

  registerRecord(recordKey: string, record: RecordResponse) {
    this.registerMasterRows([record.master]);
    const loaded: Record<string, string[]> = {};
    for (const detail of this.view.details) {
      const rows = record.details[detail.entity] ?? [];
      this.buffer.load(
        detail.entity,
        rows.map(r => ({ rowKey: r.rowKey, recordKey, values: r.values }))
      );
      for (const row of rows)
        this.extras.set(keyOf(detail.entity, row.rowKey), { frozen: row.frozen, compare: row.compare });
      loaded[detail.entity] = rows.map(r => r.rowKey);
    }
    this.details.set(recordKey, loaded);
  }

  /** 新增的主表行（还没保存）也有明细区 */
  ensureNewRecord(recordId: string) {
    if (!this.details.has(recordId)) {
      this.details.set(recordId, Object.fromEntries(this.view.details.map(d => [d.entity, []])));
    }
  }

  isRecordLoaded(recordId: string) {
    return this.details.has(recordId);
  }

  /** 按主键取行补查、按钮结果中的行等：更新正式数据 */
  registerRows(entity: string, rows: DataRow[]) {
    if (entity === this.master) {
      this.registerMasterRows(rows);
      return;
    }
    for (const row of rows) {
      const recordKey = this.buffer.recordOf(entity, row.rowKey);
      if (!recordKey) continue;
      this.buffer.load(entity, [{ rowKey: row.rowKey, recordKey, values: row.values }]);
      this.extras.set(keyOf(entity, row.rowKey), { frozen: row.frozen, compare: row.compare });
    }
  }

  /**
   * 命令结果中写入的行（C02 第 2 节）。新增行带 clientRowId：按 rowKey 登记正式数据，表格中仍用 clientRowId。
   * 返回每行在表格中的标识。
   */
  applyResultRow(row: ResultRow, recordKey: string) {
    if (row.clientRowId) this.alias(row.rowKey, row.clientRowId);
    this.buffer.load(row.entity, [{ rowKey: row.rowKey, recordKey, values: row.values }]);
    const previous = this.extras.get(keyOf(row.entity, row.rowKey));
    this.extras.set(keyOf(row.entity, row.rowKey), { frozen: row.frozen, compare: previous?.compare });
    if (row.entity !== this.master) {
      const list = this.details.get(recordKey)?.[row.entity];
      if (list && !list.includes(row.rowKey)) list.push(row.rowKey);
    }
    this.previews.delete(keyOf(row.entity, row.rowKey));
    if (row.clientRowId) this.previews.delete(keyOf(row.entity, row.clientRowId));
    return this.gridId(row.rowKey);
  }

  /** 保存前记下各单据明细的显示顺序（含新增行），保存后按它排列正式数据，新增行留在原来的位置 */
  captureOrders(recordIds: string[]) {
    return recordIds.map(recordId => ({
      recordId,
      entities: Object.fromEntries(this.view.details.map(d => [d.entity, this.detailIds(d.entity, recordId)]))
    }));
  }

  restoreOrders(captured: ReturnType<PageModel['captureOrders']>, idMap: Record<string, string>) {
    for (const { recordId, entities } of captured) {
      const loaded = this.details.get(idMap[recordId] ?? recordId);
      if (!loaded) continue;
      for (const [entity, ids] of Object.entries(entities)) {
        const current = new Set(loaded[entity] ?? []);
        const ordered = ids.map(id => idMap[id] ?? id).filter(id => current.has(id));
        const rest = [...current].filter(id => !ordered.includes(id));
        loaded[entity] = [...ordered, ...rest];
      }
    }
  }

  /** 新增的单据保存后取得正式主键：已加载的明细改记在正式主键下，表格中仍用 clientRowId */
  renameRecord(clientRowId: string, rowKey: string) {
    this.alias(rowKey, clientRowId);
    const loaded = this.details.get(clientRowId);
    if (loaded) {
      this.details.set(rowKey, loaded);
      this.details.delete(clientRowId);
    }
  }

  /** 删除的行 */
  removeRow(entity: string, rowKey: string) {
    for (const loaded of this.details.values()) {
      const list = loaded[entity];
      if (list) {
        const index = list.indexOf(rowKey);
        if (index >= 0) list.splice(index, 1);
      }
    }
    this.extras.delete(keyOf(entity, rowKey));
    if (entity === this.master) this.details.delete(rowKey);
  }

  private alias(rowKey: string, clientRowId: string) {
    const gridId = this.aliases.get(clientRowId) ?? clientRowId;
    this.aliases.set(rowKey, gridId);
    this.reverse.set(gridId, rowKey);
  }

  /** 行在表格中的标识：新增行保存后仍为它的 clientRowId */
  gridId(id: string) {
    return this.aliases.get(id) ?? id;
  }

  /** 表格中的标识 → 行标识（保存后的新增行为正式主键） */
  rowIdOf(gridId: string) {
    return this.reverse.get(gridId) ?? gridId;
  }

  // ---- 读取

  values(entity: string, id: string): FieldValues {
    const current = this.buffer.current(entity, id) ?? {};
    const preview = this.previews.get(keyOf(entity, id));
    return preview ? { ...current, ...preview.computed } : current;
  }

  compare(entity: string, id: string) {
    return this.extras.get(keyOf(entity, id))?.compare ?? undefined;
  }

  /** 单据的明细行（含新增行，按插入位置；标为删除的行保留） */
  detailIds(entity: string, recordId: string): string[] {
    const ids = [...(this.details.get(recordId)?.[entity] ?? [])];
    return insertNewRows(ids, this.buffer.newRows(entity, recordId));
  }

  /** 新增的主表行（还没保存的） */
  newMasterRows() {
    return this.buffer.newRows(this.master, null).filter(r => !this.buffer.isDeleted(this.master, r.id));
  }

  /** 行所在单据被冻结时，冻结它的审批（FP-07、FP-16）：主从页按主表行判断整张单据 */
  frozenBy(entity: string, id: string): string | null {
    const own = this.extras.get(keyOf(entity, id))?.frozen?.approvalId ?? null;
    if (own || entity === this.master) return own;
    const recordId = this.buffer.recordOf(entity, id);
    return recordId ? this.recordFrozenBy(recordId) : null;
  }

  recordFrozenBy(recordId: string): string | null {
    return this.extras.get(keyOf(this.master, recordId))?.frozen?.approvalId ?? null;
  }

  /** 命令结果中提交审批的单据整张冻结（C02 `approvals`、FP-07） */
  freezeRecord(recordId: string, approvalId: string) {
    const key = keyOf(this.master, recordId);
    const extras = this.extras.get(key) ?? { frozen: null };
    this.extras.set(key, { ...extras, frozen: { approvalId } });
  }

  // ---- 预览

  setPreview(rows: EvalRowResult[]): RowId[] {
    const changed: RowId[] = [];
    for (const row of rows) {
      const id = row.rowKey ?? row.clientRowId!;
      const key = keyOf(row.entity, id);
      const before = JSON.stringify(this.previews.get(key) ?? null);
      const next = { computed: row.computed, fields: row.fields, style: row.style };
      if (before !== JSON.stringify(next)) changed.push({ entity: row.entity, id });
      this.previews.set(key, next);
    }
    return changed;
  }

  clearPreview(rows: RowId[]) {
    for (const row of rows) this.previews.delete(keyOf(row.entity, row.id));
  }

  previewOf(entity: string, id: string) {
    return this.previews.get(keyOf(entity, id));
  }

  /**
   * 显示求值的结果（旧系统 GRID_STYLE 的 getRowStyle 按行数据算样式，加载即显示）：只记界面规则给出的字段状态和样式，
   * 结果中的 computed 不用（显示求值不计算，显示的仍是加载来的值）。返回效果有变化的行。
   */
  setDisplay(rows: EvalRowResult[]): RowId[] {
    const changed: RowId[] = [];
    for (const row of rows) {
      const id = row.rowKey ?? row.clientRowId!;
      const key = keyOf(row.entity, id);
      const next = { fields: row.fields, style: row.style };
      if (JSON.stringify(this.displays.get(key) ?? null) !== JSON.stringify(next))
        changed.push({ entity: row.entity, id });
      this.displays.set(key, next);
    }
    return changed;
  }

  /** 做过显示求值的主表行（配置变更后按新的规则包重新求值） */
  displayedRecords(): string[] {
    const prefix = keyOf(this.master, '');
    return [...this.displays.keys()].filter(key => key.startsWith(prefix)).map(key => key.slice(prefix.length));
  }

  /** 行上界面规则的效果：单据有修改时取预览（按修改后的值），否则取显示求值（按加载来的值） */
  ruleView(entity: string, id: string): RuleView | undefined {
    const key = keyOf(entity, id);
    return this.previews.get(key) ?? this.displays.get(key);
  }

  /** 预览算出的计算字段与正式数据不同：沿用旧系统的"计算带出变化"标记 */
  isCalcChanged(entity: string, id: string, field: string) {
    const preview = this.previews.get(keyOf(entity, id));
    if (!preview || !(field in preview.computed)) return false;
    const committed = this.buffer.committed(entity, id);
    if (!committed) return false;
    const a = preview.computed[field];
    const b = committed[field] ?? null;
    if (a === b) return false;
    // 预览结果不舍入（C07 第 3 节），按 C01 第 3 节判定数值是否一致
    if (isDecimalText(a) && isDecimalText(b)) return !numbersConsistent(a as string, b as string);
    return true;
  }

  setEffects(recordId: string, effects: RuleEffect[]) {
    this.effects.set(recordId, effects);
  }

  allEffects(): RuleEffect[] {
    return [...this.effects.values()].flat();
  }

  // ---- 保存失败时的定位（FP-06）

  setErrors(errors: Array<{ entity: string; id: string; field: string | null; message: string }>): RowId[] {
    this.errors.clear();
    const rows: RowId[] = [];
    for (const error of errors) {
      const key = keyOf(error.entity, error.id);
      const list = this.errors.get(key) ?? [];
      list.push({ field: error.field, message: error.message });
      this.errors.set(key, list);
      rows.push({ entity: error.entity, id: error.id });
    }
    return rows;
  }

  clearErrors(): RowId[] {
    const rows = [...this.errors.keys()].map(key => {
      const [entity, id] = key.split('\u0000');
      return { entity, id };
    });
    this.errors.clear();
    return rows;
  }

  errorsOf(entity: string, id: string): CellError[] {
    return this.errors.get(keyOf(entity, id)) ?? [];
  }

  // ---- 编辑

  /**
   * 单元格能否编辑：页面有保存按钮、字段由用户填写（fieldEditable；只随 Lookup 回填写库的 fillWritable 字段不算）、
   * 行没有标为删除、单据没有被冻结，且界面规则（预览或显示求值，见 ruleView）没有把它设为不可编辑。
   * 每次调用都取最新的视图和规则（配置原地替换后立即生效）。
   */
  cellEditable(entity: string, id: string, field: string): boolean {
    if (!this.view.systemButtons.includes('save')) return false;
    const region = regionOf(this.view, entity);
    const meta = fieldOf(this.view, entity, field);
    if (!region || !meta || !this.buffer.current(entity, id)) return false;
    if (this.buffer.isDeleted(entity, id) || this.frozenBy(entity, id)) return false;
    if (this.ruleView(entity, id)?.fields[field]?.editable === false) return false;
    return fieldEditable(region, meta, this.values(entity, id), this.buffer.isNew(entity, id));
  }

  /** 字段是否必填：页面视图的 required，或界面规则（预览或显示求值）设为必填 */
  cellRequired(entity: string, id: string, field: string): boolean {
    const rule = this.ruleView(entity, id)?.fields[field]?.required;
    return rule ?? Boolean(fieldOf(this.view, entity, field)?.required);
  }

  region(entity: string): ViewRegion | undefined {
    return regionOf(this.view, entity);
  }
}

/**
 * 把新增行插到各自的位置：插在 `after` 那一行之后；同一行之后插入多行时按新增的先后排列；
 * `after` 那一行已不在列表中时排在最后。
 */
export function insertNewRows(ids: string[], added: Array<{ id: string; after: string | null }>): string[] {
  const result = [...ids];
  const anchorOf = new Map<string, string | null>();
  for (const row of added) {
    let position: number;
    if (row.after === null) position = 0;
    else {
      const index = result.indexOf(row.after);
      position = index < 0 ? result.length : index + 1;
    }
    while (position < result.length && anchorOf.has(result[position]) && anchorOf.get(result[position]) === row.after) {
      position += 1;
    }
    result.splice(position, 0, row.id);
    anchorOf.set(row.id, row.after);
  }
  return result;
}
