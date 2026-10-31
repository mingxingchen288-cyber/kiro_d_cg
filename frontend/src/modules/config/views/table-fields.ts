/**
 * "表与列"的列表格（同旧系统 SectionTables.vue 的列元数据表格）在新配置中的对应：
 * - 实体（C06 第 2 节，所有页面共用）：标题、类型、写入列、来源（ERP / 自有）、角色、小数位、千分位（只有数值字段能勾）、
 *   默认值、选项值、对比；
 * - 页面字段设置（C06 第 3 节，只对本页面）：显示、编辑、必填、求和（汇总行，只能用于数值字段）、查询（高级查询的预置条件）、
 *   宽度、固定、字典、字典可填写（选了字典才能勾）、Lookup；
 *   "显示、编辑、必填"也可以切换为编辑实体的 `fieldDefaults`（所有页面的基线）。
 * 旧系统每个页面有自己的一份列元数据；新配置把它拆成实体和页面两层，下层只能收紧可见、可编辑，必填只能增加。
 *
 * 表中的"显示、编辑、必填"显示实际结果（FC-09）：字段本身不能编辑的（计算字段、系统字段、只在视图中、没有 `erpRow`
 * 的实体的 ERP 列、`erpRow.column`，同后端 `views.field_state`）编辑格不勾、不能改；"本页面"范围下，实体默认已收紧的
 * 格子（不显示、不可编辑、必填）也不能改。这些格子写明原因（`flagLock`）。行中存的仍是本层自己的设置，不能改的格子
 * 不改它，所以保存的内容只写需要写的项，与原来相同。角色的列权限（C06 第 8 节）还会再收紧，不在这张表里算。
 * 保存列时按 config 的 CF-14 重算页面保存操作的 `writableFields`（`saveColumns`）。
 */
import type { ConfigStore } from '../core/store';
import { errorText } from '../core/errors';
import type { ItemEditor, ItemNotifier } from '../core/item-editor';
import type {
  DefaultValue,
  EntityContent,
  EntityField,
  FieldCompare,
  FieldFlags,
  FieldSetting,
  LookupSetting,
  PageArea,
  PageContent
} from '../core/types';
import { BUILTIN_DEFAULTS } from '../entity/entity-model';

export interface FieldRow {
  _id: string;
  name: string;
  label: string;
  type: EntityField['type'];
  column: string;
  source: 'erp' | 'own';
  role: EntityField['role'];
  scale: number | null;
  /** 实体字段的 `grouping`（C06 第 2 节）：勾选时数值显示千分位，同旧系统列表格的"千分位" */
  grouping: boolean;
  visible: boolean;
  editable: boolean;
  required: boolean;
  width: number | null;
  pinned: 'left' | 'right' | null;
  dictType: string | null;
  /** 页面字段设置的 `dictFreeText`（C06 第 3 节）：字典下拉中可以填写字典以外的值，同旧系统编辑器"下拉（可填写）" */
  dictFreeText: boolean;
  lookup: LookupSetting | null;
  /** 页面字段设置的 `aggregate`（C06 第 3 节）：勾选时这一列在汇总行中求和，同旧系统列表格的"求和" */
  aggregate: boolean;
  /** 页面字段设置的 `searchable`（C06 v23 第 3 节）：勾选时高级查询对话框一打开就列出这个字段，同旧系统列表格的"查询" */
  searchable: boolean;
  defaultText: string;
  optionsText: string;
  compare: FieldCompare | null;
  isNew: boolean;
  /** 上层的设置：本页面范围为实体的 `fieldDefaults`，实体默认范围没有上层，为空 */
  inherited: FieldFlags;
}

export type FlagScope = 'page' | 'entity';
export type Flag = 'visible' | 'editable' | 'required';
type ErpRow = EntityContent['erpRow'];

const TO_ENTITY_SCOPE = '切到“实体默认”修改';

/** 字段本身不能编辑的原因（同后端 `views.field_state`、C06 第 2 节）；能编辑时为空串 */
export function fieldLock(field: { name: string; column: string | null; source: EntityField['source']; role: EntityField['role'] }, erpRow: ErpRow): string {
  if (field.role === 'calculated') return '计算字段（由规则计算），不能编辑';
  if (field.role === 'system') return '系统字段（由平台写入），不能编辑';
  if (!field.column?.trim()) return '只在视图中、没有写入列，不能编辑';
  if (field.source === 'erp' && !erpRow) return 'ERP 列，实体没有 ERP 行标识，不能编辑';
  if (erpRow && field.name === erpRow.column) return 'ERP 行标识列，只由平台写，不能编辑';
  return '';
}

/** 某一格不能改的原因；能改时为空串 */
export function flagLock(row: FieldRow, flag: Flag, erpRow: ErpRow): string {
  if (flag === 'editable') {
    const own = fieldLock(row, erpRow);
    if (own) return own;
    return row.inherited.editable === false ? `实体默认不可编辑（所有页面），${TO_ENTITY_SCOPE}` : '';
  }
  if (flag === 'visible') return row.inherited.visible === false ? `实体默认不显示（所有页面），本页面不能显示，${TO_ENTITY_SCOPE}` : '';
  return row.inherited.required === true ? `实体默认必填（所有页面），本页面不能取消，${TO_ENTITY_SCOPE}` : '';
}

/** 表格中显示的值：能改的格子是本层的设置，不能改的格子是实际结果（不显示、不可编辑、必填） */
export function flagValue(row: FieldRow, flag: Flag, erpRow: ErpRow): boolean {
  return flagLock(row, flag, erpRow) ? flag === 'required' : row[flag];
}

/** 一行中全部不能改的原因（"不能修改的原因"列） */
export function lockText(row: FieldRow, erpRow: ErpRow): string {
  return (['editable', 'visible', 'required'] as const)
    .map(flag => flagLock(row, flag, erpRow))
    .filter(Boolean)
    .join('；');
}

let sequence = 0;

function defaultToText(value: DefaultValue | null | undefined) {
  if (!value || value.type === 'options') return '';
  if (value.type === 'builtin') return BUILTIN_DEFAULTS.find(b => b.value === value.value)?.label ?? value.value;
  return value.value;
}

export function textToDefault(text: string, options: string): DefaultValue | null {
  const values = options
    .split(/[,，]/)
    .map(v => v.trim())
    .filter(Boolean);
  if (values.length) return { type: 'options', value: values };
  const t = text.trim();
  if (!t) return null;
  const builtin = BUILTIN_DEFAULTS.find(b => b.label === t || b.value === t);
  return builtin ? { type: 'builtin', value: builtin.value } : { type: 'static', value: t };
}

export function fieldRows(entity: EntityContent, settings: Record<string, FieldSetting>, scope: FlagScope): FieldRow[] {
  return entity.fields.map(f => {
    const flags: FieldFlags = scope === 'page' ? settings[f.name] ?? {} : entity.fieldDefaults?.[f.name] ?? {};
    const s = settings[f.name] ?? {};
    return {
      _id: `field-${++sequence}`,
      name: f.name,
      label: f.label,
      type: f.type,
      column: f.column ?? '',
      source: f.source,
      role: f.role,
      scale: f.scale ?? null,
      grouping: f.grouping === true,
      visible: flags.visible !== false,
      editable: flags.editable !== false,
      required: flags.required === true,
      width: s.width ?? null,
      pinned: s.pinned ?? null,
      dictType: s.dictType ?? null,
      dictFreeText: s.dictFreeText === true,
      lookup: s.lookup ?? null,
      aggregate: s.aggregate === 'sum',
      searchable: s.searchable === true,
      defaultText: defaultToText(f.default),
      optionsText: f.default?.type === 'options' ? f.default.value.join(',') : '',
      compare: f.compare ?? null,
      isNew: false,
      inherited: scope === 'page' ? { ...(entity.fieldDefaults?.[f.name] ?? {}) } : {}
    };
  });
}

/** 表格的行 → 实体字段和页面字段设置；只写有值的可选项 */
export function applyRows(entity: EntityContent, settings: Record<string, FieldSetting>, rows: FieldRow[], scope: FlagScope) {
  const fields: EntityField[] = rows.map(r => {
    const old = entity.fields.find(f => f.name === r.name);
    const field: EntityField = { ...(old ?? {}), name: r.name, column: r.column.trim() || null, label: r.label, type: r.type, source: r.source, role: r.role };
    if (r.scale !== null && String(r.scale) !== '') field.scale = Number(r.scale);
    else delete field.scale;
    if (r.grouping && r.type === 'number') field.grouping = true;
    else delete field.grouping;
    const def = textToDefault(r.defaultText, r.optionsText);
    if (def) field.default = def;
    else delete field.default;
    if (r.compare) field.compare = r.compare;
    else delete field.compare;
    return field;
  });
  const fieldDefaults: Record<string, FieldFlags> = scope === 'entity' ? {} : { ...(entity.fieldDefaults ?? {}) };
  const nextSettings: Record<string, FieldSetting> = {};
  for (const r of rows) {
    const s: FieldSetting = {};
    const flags: FieldFlags = {};
    if (!r.visible) flags.visible = false;
    if (!r.editable) flags.editable = false;
    if (r.required) flags.required = true;
    if (scope === 'page') Object.assign(s, flags);
    else if (Object.keys(flags).length) fieldDefaults[r.name] = flags;
    if (scope === 'entity') {
      const old = settings[r.name] ?? {};
      for (const k of ['visible', 'editable', 'required'] as const) if (old[k] !== undefined && old[k] !== null) s[k] = old[k];
    }
    if (r.width) s.width = Number(r.width);
    if (r.pinned) s.pinned = r.pinned;
    if (r.dictType) s.dictType = r.dictType;
    if (r.dictType && r.dictFreeText) s.dictFreeText = true;
    if (r.lookup) s.lookup = r.lookup;
    if (r.aggregate) s.aggregate = 'sum';
    if (r.searchable) s.searchable = true;
    if (Object.keys(s).length) nextSettings[r.name] = s;
  }
  const nextEntity: EntityContent = { ...entity, fields };
  if (Object.keys(fieldDefaults).length) nextEntity.fieldDefaults = fieldDefaults;
  else delete nextEntity.fieldDefaults;
  return { entity: nextEntity, settings: nextSettings };
}

/** 从视图重新导入：视图中新的列加到最后，已有列的设置不变（同后端 merge_columns 和旧系统 reimportColumns） */
export function newRowsFrom(columns: Array<{ name: string; type: string; label: string; inTable: boolean }>, existing: FieldRow[]): FieldRow[] {
  const names = new Set(existing.map(r => r.name.toUpperCase()));
  return columns
    .filter(c => !names.has(c.name.toUpperCase()))
    .map(c => ({
      _id: `field-${++sequence}`,
      name: c.name,
      label: c.label,
      type: c.type as EntityField['type'],
      column: c.inTable ? c.name : '',
      source: 'own',
      role: 'input',
      scale: null,
      grouping: false,
      visible: true,
      editable: c.inTable,
      required: false,
      width: null,
      pinned: null,
      dictType: null,
      dictFreeText: false,
      lookup: null,
      aggregate: false,
      searchable: false,
      defaultText: '',
      optionsText: '',
      compare: null,
      isNew: true,
      inherited: {}
    }));
}

/**
 * 保存操作中一个实体的可写字段（config 的 CF-14，同后端向导的 `writable_fields`）：`role` 为 input、`column` 不为 null、
 * 实体的 `fieldDefaults` 和页面都没有设为不可编辑的字段，不含主键、主从关联字段和 `erpRow.column`，没有 `erpRow` 的实体
 * 不含 ERP 列；再加上这些字段的 Lookup 回填目标中有写入列的（`fillBack` 不为 false，回填目标列入保存操作的
 * `writableFields`，见 authz 的 `writable_fields`、MG-10）。按实体字段的顺序列出。
 */
export function writableFieldsOf(entity: EntityContent, settings: Record<string, FieldSetting>, parentKey: string | null): string[] {
  const erpRow = entity.erpRow ?? null;
  const skip = new Set([entity.primaryKey, parentKey, erpRow?.column].filter((name): name is string => Boolean(name)));
  const writable = (f: EntityField) => Boolean(f.column) && !skip.has(f.name) && !(f.source === 'erp' && !erpRow);
  const editable = entity.fields.filter(
    f => f.role === 'input' && writable(f) && entity.fieldDefaults?.[f.name]?.editable !== false && settings[f.name]?.editable !== false
  );
  const names = new Set(editable.map(f => f.name));
  for (const f of editable) {
    const lookup = settings[f.name]?.lookup;
    if (lookup && lookup.fillBack !== false) for (const target of Object.keys(lookup.fill)) names.add(target);
  }
  return entity.fields.filter(f => names.has(f.name) && f.role !== 'calculated' && writable(f)).map(f => f.name);
}

/** 按页面的主表和每个明细实体重算可写字段；`current` 中其他实体的可写字段不变 */
export function pageWritableFields(
  page: PageContent,
  entities: Record<string, EntityContent>,
  current: Record<string, string[]> = {}
): Record<string, string[]> {
  const parentKeys = new Map((entities[page.master.entity]?.details ?? []).map(d => [d.entity, d.parentKey]));
  const areas: Array<[PageArea, string | null]> = [[page.master, null]];
  for (const d of page.details ?? []) areas.push([d, parentKeys.get(d.entity) ?? null]);
  const fresh = new Map<string, string[]>();
  for (const [area, parentKey] of areas) {
    const entity = entities[area.entity];
    if (entity) fresh.set(area.entity, writableFieldsOf(entity, area.fields ?? {}, parentKey));
  }
  // 原有实体的顺序不变，新的实体加在后面；重算后没有可写字段的实体去掉（同操作编辑界面的写法）
  const next: Record<string, string[]> = {};
  for (const [code, fields] of [...Object.entries(current), ...fresh]) {
    const value = fresh.get(code) ?? fields;
    if (!(code in next) && (value.length || !fresh.has(code))) next[code] = value;
  }
  return next;
}

export interface ColumnsSave {
  store: ConfigStore;
  notify: ItemNotifier;
  page: ItemEditor<'page'>;
  entity: ItemEditor<'entity'>;
  /** 页面保存操作的编辑状态，由 `saveColumns` 打开 */
  operation: ItemEditor<'operation'>;
  /** 本表在页面中的区域（`page` 内容中的主表区或某个明细区） */
  area: PageArea;
  rows: FieldRow[];
  scope: FlagScope;
}

/**
 * 保存列：先保存实体（C06 第 2 节），再保存页面的字段设置（第 3 节），再按保存后的实体和页面重算页面保存操作
 * （`saveOperation`）的 `writableFields` 并保存，操作的其他内容不变、可写字段没有变化时不保存；每一步都先校验，
 * 哪一步不通过就停在哪一步，错误显示在该步的编辑状态中。全部完成时返回 true。
 */
export async function saveColumns(s: ColumnsSave): Promise<boolean> {
  const draft = s.entity.state.current;
  if (!draft) return false;
  const applied = applyRows(draft.content, s.area.fields ?? {}, s.rows, s.scope);
  draft.content = applied.entity;
  s.area.fields = applied.settings;
  if ((await s.entity.save()) === null) return false;
  s.page.markDirty();
  if ((await s.page.save()) === null) return false;

  const page = s.page.state.current!.content;
  const saved = s.entity.state.current!;
  const codes = [...new Set([page.master.entity, ...(page.details ?? []).map(d => d.entity)])];
  let entities: Record<string, EntityContent>;
  try {
    const loaded = await Promise.all(
      codes.map(async code => [code, code === saved.key ? saved.content : (await s.store.load('entity', code)).content] as const)
    );
    entities = Object.fromEntries(loaded);
  } catch (error) {
    s.notify.error(errorText(error));
    return false;
  }
  // 只读页面（C06 v29）没有保存操作，不用同步可写字段
  if (!page.saveOperation) return true;
  await s.operation.open(page.saveOperation);
  const operation = s.operation.state.current;
  if (!operation) return false;
  const before = operation.content.writableFields ?? {};
  const next = pageWritableFields(page, entities, before);
  if (JSON.stringify(next) === JSON.stringify(before)) return true;
  operation.content.writableFields = next;
  s.operation.markDirty();
  return (await s.operation.save()) !== null;
}
