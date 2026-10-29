/**
 * 新建页面向导（FC-07、config CF-14、C09 `wizard/columns`、`wizard/generate`），对照旧系统 WizardPanel.vue、
 * WizardStep1～3.vue、useWizardState.ts：
 * 1. 页面菜单：归属菜单（菜单分组）、页面名称、页面编码（只允许大写字母、数字、下划线，最长 64，同旧系统）；
 * 2. 导入表与配置字段：页面模式单表 / 主从；主表的视图和写入表，"导入列"后调整标题、显示、编辑、ERP 列；
 *    主从时添加明细表并选关联字段；审计默认开启，明细显示方式默认多 Tab（单表页不显示，按预填值提交）；
 *    写入表的序列 `<表名>_SEQ` 不存在时提示先建序列，不能继续；
 * 3. 确认生成：列出将生成的配置项，生成请求随审计、明细显示方式一起提交。
 *
 * 请求中 `master`、`details[]` 的写法按后端 wizard.py：`{entity, name, table, readView, freezable, erpColumns, labels}`，
 * 明细另有 `title`、`parentKey`。显示、编辑的调整写在 `fieldDefaults`（后端向导目前不处理，生成后由 `followUp`
 * 补存到实体，见 contract-gaps）。
 */
import { reactive } from 'vue';
import type { PlatformApi } from '../../../contracts/api';
import type { WizardGenerateRequest } from '../../../contracts/http';
import type { JsonValue } from '../../../contracts/schema';
import { errorText, problemsOf } from '../core/errors';
import type { ConfigProblem } from '../core/errors';
import type { ConfigStore } from '../core/store';
import type { FieldFlags, MenuNode } from '../core/types';

export interface WizardColumnRow {
  name: string;
  type: string;
  label: string;
  inTable: boolean;
  visible: boolean;
  editable: boolean;
  erp: boolean;
}

export interface WizardTable {
  entity: string;
  name: string;
  readView: string;
  table: string;
  primaryKey: string;
  sequence: { name: string; exists: boolean } | null;
  columns: WizardColumnRow[];
  /** 明细：区域标题、关联主表的字段 */
  title: string;
  parentKey: string;
  importError: string;
}

export interface MenuGroupOption {
  label: string;
  value: string;
}

export function emptyTable(): WizardTable {
  return {
    entity: '',
    name: '',
    readView: '',
    table: '',
    primaryKey: '',
    sequence: null,
    columns: [],
    title: '',
    parentKey: '',
    importError: ''
  };
}

/** 页面编码输入：同旧系统 handleCodeInput，只保留大写字母、数字、下划线，最长 64 */
export function normalizeCode(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9_]/g, '').slice(0, 64);
}

/** 实体编码按写入表推出：去掉 `T_` 前缀，例如 T_COST_GOODS → COST_GOODS；管理员可以改 */
export function entityCodeOf(table: string) {
  return normalizeCode(table.replace(/^T_/i, ''));
}

/** 菜单配置中的分组，供"归属菜单"选择 */
export function menuGroups(menus: Array<{ name: string; content: { items: MenuNode[] } }>): MenuGroupOption[] {
  const out: MenuGroupOption[] = [];
  const walk = (items: MenuNode[], path: string[]) => {
    for (const item of items) {
      if (item.kind !== 'group') continue;
      const next = [...path, item.title];
      out.push({ label: next.join(' / '), value: item.key });
      walk(item.children ?? [], next);
    }
  };
  for (const menu of menus) walk(menu.content.items, []);
  return out;
}

export class WizardState {
  readonly state = reactive({
    step: 1,
    parentMenu: '',
    title: '',
    pageCode: '',
    layout: 'single' as 'single' | 'masterDetail',
    /** 预填：审计开启、明细多 Tab（FC-07） */
    audit: true,
    detailMode: 'tabs' as 'tabs' | 'stack',
    master: emptyTable(),
    details: [] as WizardTable[],
    errors: [] as string[],
    problems: [] as ConfigProblem[],
    busy: false,
    generated: null as unknown
  });

  constructor(
    private readonly api: PlatformApi,
    private readonly store: ConfigStore
  ) {}

  setPageCode(value: string) {
    this.state.pageCode = normalizeCode(value);
  }

  setLayout(layout: 'single' | 'masterDetail') {
    this.state.layout = layout;
    if (layout === 'single') this.state.details = [];
  }

  addDetail() {
    this.state.details.push(emptyTable());
  }

  removeDetail(index: number) {
    this.state.details.splice(index, 1);
  }

  /** 导入列：读视图（没有视图时读表）的结构和序列是否存在（只读） */
  async importColumns(table: WizardTable) {
    table.importError = '';
    try {
      const result = await this.api.wizardColumns({ readView: table.readView.trim() || null, table: table.table.trim() });
      table.primaryKey = result.primaryKey;
      table.sequence = result.sequence;
      table.columns = result.columns.map(c => ({
        name: c.name,
        type: c.type,
        label: c.label,
        inTable: c.inTable,
        visible: true,
        editable: c.inTable && c.name !== result.primaryKey,
        erp: false
      }));
      if (!table.entity) table.entity = entityCodeOf(table.table);
      if (!table.name) table.name = this.state.title;
      if (!table.sequence.exists) table.importError = sequenceMessage(table.sequence.name);
    } catch (error) {
      table.columns = [];
      table.sequence = null;
      table.importError = errorText(error);
    }
  }

  tables() {
    return [this.state.master, ...this.state.details];
  }

  /** 序列不存在的表：有一张就不能继续生成 */
  missingSequences() {
    return this.tables()
      .filter(t => t.sequence && !t.sequence.exists)
      .map(t => t.sequence!.name);
  }

  validateStep1() {
    const errors: string[] = [];
    if (!this.state.parentMenu) errors.push('请选择归属菜单');
    if (!this.state.title.trim()) errors.push('页面名称必填');
    if (!this.state.pageCode) errors.push('页面编码必填');
    return errors;
  }

  validateStep2() {
    const errors: string[] = [];
    const check = (t: WizardTable, label: string, detail: boolean) => {
      if (!t.table.trim()) errors.push(`${label}目标表名必填`);
      if (!t.columns.length) errors.push(`${label}列配置不能为空，请先导入列`);
      if (!t.entity.trim()) errors.push(`${label}实体编码必填`);
      if (detail && !t.parentKey) errors.push(`${label}关联字段必须选择`);
    };
    check(this.state.master, '主表', false);
    this.state.details.forEach((d, i) => check(d, `明细表${i + 1}`, true));
    if (this.state.layout === 'masterDetail' && !this.state.details.length) errors.push('主从页至少要有一张明细表');
    for (const name of this.missingSequences()) errors.push(sequenceMessage(name));
    return errors;
  }

  next() {
    const errors = this.state.step === 1 ? this.validateStep1() : this.validateStep2();
    this.state.errors = errors;
    if (!errors.length) this.state.step += 1;
    return errors.length === 0;
  }

  prev() {
    this.state.errors = [];
    if (this.state.step > 1) this.state.step -= 1;
  }

  /** 生成请求（C09 第 3 节）：`audit`、`detailMode` 总是写出，单表页也写 `detailMode` */
  request(): WizardGenerateRequest {
    const spec = (t: WizardTable, detail: boolean): Record<string, JsonValue> => {
      const labels: Record<string, string> = {};
      const fieldDefaults: Record<string, FieldFlags> = {};
      for (const c of t.columns) {
        if (c.label && c.label !== c.name) labels[c.name] = c.label;
        const flags: FieldFlags = {};
        if (!c.visible) flags.visible = false;
        if (c.inTable && c.name !== t.primaryKey && !c.editable) flags.editable = false;
        if (Object.keys(flags).length) fieldDefaults[c.name] = flags;
      }
      const out: Record<string, JsonValue> = {
        entity: t.entity.trim(),
        name: t.name.trim() || t.entity.trim(),
        table: t.table.trim(),
        readView: t.readView.trim() || null,
        freezable: true,
        erpColumns: t.columns.filter(c => c.erp).map(c => c.name),
        labels
      };
      if (Object.keys(fieldDefaults).length) out.fieldDefaults = fieldDefaults as unknown as JsonValue;
      if (detail) {
        out.title = t.title.trim() || t.name.trim();
        out.parentKey = t.parentKey;
      }
      return out;
    };
    return {
      parentMenu: this.state.parentMenu,
      pageCode: this.state.pageCode,
      title: this.state.title.trim(),
      layout: this.state.layout,
      detailMode: this.state.detailMode,
      audit: this.state.audit,
      master: spec(this.state.master, false),
      details: this.state.layout === 'masterDetail' ? this.state.details.map(d => spec(d, true)) : []
    };
  }

  /** 生成：序列不存在时不发请求；422 时显示明细 */
  async generate() {
    const missing = this.missingSequences();
    if (missing.length) {
      this.state.errors = missing.map(sequenceMessage);
      return false;
    }
    this.state.busy = true;
    this.state.problems = [];
    try {
      const request = this.request();
      this.state.generated = await this.api.wizardGenerate(request);
      await this.followUp(request);
      return true;
    } catch (error) {
      const problems = problemsOf(error);
      if (problems) this.state.problems = problems;
      else this.state.errors = [errorText(error)];
      return false;
    } finally {
      this.state.busy = false;
    }
  }

  /** 后端向导还没有写 `fieldDefaults` 时，把显示、编辑的调整补存到生成的实体（普通的实体保存，先校验） */
  private async followUp(request: WizardGenerateRequest) {
    const specs = [request.master, ...request.details];
    for (const spec of specs) {
      const wanted = spec.fieldDefaults as unknown as Record<string, FieldFlags> | undefined;
      if (!wanted) continue;
      const entity = await this.store.load('entity', String(spec.entity));
      const current = entity.content.fieldDefaults ?? {};
      const missing = Object.entries(wanted).filter(([field, flags]) =>
        Object.entries(flags).some(([k, v]) => current[field]?.[k as keyof FieldFlags] !== v)
      );
      if (!missing.length) continue;
      const fieldDefaults = { ...current };
      for (const [field, flags] of missing) fieldDefaults[field] = { ...current[field], ...flags };
      const result = await this.store.save('entity', entity.key, entity.name, { ...entity.content, fieldDefaults });
      if (!result.ok) this.state.problems.push(...result.problems);
    }
  }
}

export function sequenceMessage(name: string) {
  return `序列 ${name} 不存在，请先在数据库中建好序列再生成（平台不创建序列）`;
}
