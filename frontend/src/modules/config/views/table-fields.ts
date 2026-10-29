/**
 * "表与列"的列表格（同旧系统 SectionTables.vue 的列元数据表格）在新配置中的对应：
 * - 实体（C06 第 2 节，所有页面共用）：标题、类型、写入列、来源（ERP / 自有）、角色、小数位、默认值、选项值、对比；
 * - 页面字段设置（C06 第 3 节，只对本页面）：显示、编辑、必填、宽度、固定、字典、Lookup；
 *   "显示、编辑、必填"也可以切换为编辑实体的 `fieldDefaults`（所有页面的基线）。
 * 旧系统每个页面有自己的一份列元数据；新配置把它拆成实体和页面两层，下层只能收紧可见、可编辑，必填只能增加。
 */
import type { DefaultValue, EntityContent, EntityField, FieldCompare, FieldFlags, FieldSetting, LookupSetting } from '../core/types';
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
  visible: boolean;
  editable: boolean;
  required: boolean;
  width: number | null;
  pinned: 'left' | 'right' | null;
  dictType: string | null;
  lookup: LookupSetting | null;
  defaultText: string;
  optionsText: string;
  compare: FieldCompare | null;
  isNew: boolean;
}

export type FlagScope = 'page' | 'entity';

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
      visible: flags.visible !== false,
      editable: flags.editable !== false,
      required: flags.required === true,
      width: s.width ?? null,
      pinned: s.pinned ?? null,
      dictType: s.dictType ?? null,
      lookup: s.lookup ?? null,
      defaultText: defaultToText(f.default),
      optionsText: f.default?.type === 'options' ? f.default.value.join(',') : '',
      compare: f.compare ?? null,
      isNew: false
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
    if (r.lookup) s.lookup = r.lookup;
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
      visible: true,
      editable: c.inTable,
      required: false,
      width: null,
      pinned: null,
      dictType: null,
      lookup: null,
      defaultText: '',
      optionsText: '',
      compare: null,
      isNew: true
    }));
}
