/**
 * 一个区域（页面中的主表或某个明细）某一类规则的编辑状态，对应旧系统 SectionBehavior 中的"计算规则 / 校验规则 /
 * 可编辑规则 / 样式规则 → 可视化编辑"弹窗：弹窗里一张卡片一条规则，"+ 添加规则"新增，"删除"去掉，"保存"把
 * 改动过的规则逐条保存为 `rule` 配置项（先校验再保存），删掉的已保存规则删除配置项。
 *
 * 规则属于哪个区域：`entity` 层规则按 `target` 为区域的实体；`page` 层规则（target 为页面编码）按作用字段属于哪个区域，
 * 作用于整行（field 为 null）的放在主表（C06 第 5 节没有写页面层整行规则属于哪个区域，见 contract-gaps）。
 *
 * 校验规则弹窗另有"字段必填"卡片（`RequiredCard`）：数值字段的"必填"不生成校验规则，改为字段设置的必填，
 * 与"表与列"的"必填"列是同一个设置（见 `RequiredCard` 的说明）。
 */
import { reactive } from 'vue';
import type { PageTable } from '../core/catalog';
import { type ConfigProblem, errorText } from '../core/errors';
import { ItemEditor } from '../core/item-editor';
import { type ConfigStore, plain } from '../core/store';
import type { EntityContent, FieldFlags, PageArea, RuleContent } from '../core/types';
import { type RuleKind, cleanVisual, isVisual, kindOf, suggestKey } from './rule-model';

let sequence = 0;

/** 字段必填的范围，同"表与列"：实体默认（所有页面，实体的 `fieldDefaults`）、本页面（页面字段设置） */
export type RequiredScope = 'entity' | 'page';

/**
 * 校验规则弹窗中的"字段必填"：必填保存为字段设置的 `required`（C06 第 2、3 节），页面视图的这个字段为必填，
 * 保存单据时写入管道按真实的值检查（WP-07：为空或空文字时 422，提示"字段 不能为空"；0 可以保存），
 * 同旧系统 validator.ts 的 validateRow。数值字段的"必填"只能这样配：rules-core 中数值为空按 0 计算
 * （模块说明第 8 节），`X == null or X == ''` 这样的条件对数值字段永远不成立。
 */
export interface RequiredCard {
  _id: string;
  field: string;
  scope: RequiredScope;
  /** 已保存在配置中（打开时从实体和页面读出，或本次已保存） */
  saved: boolean;
}

/** 字段设置中 `set` 的字段设为必填，`unset` 的去掉必填；其他设置不变，去掉后没有设置的字段不写 */
export function applyRequired<T extends FieldFlags>(settings: Record<string, T>, set: string[], unset: string[]) {
  const next: Record<string, T> = {};
  for (const [name, setting] of Object.entries(settings)) {
    const { required: _required, ...rest } = setting;
    const kept = unset.includes(name) ? (rest as T) : setting;
    if (!unset.includes(name) || Object.keys(kept).length) next[name] = kept;
  }
  for (const name of set) next[name] = { ...next[name], required: true };
  return next;
}

/** 已保存的字段必填：按实体字段的顺序，实体默认在前、本页面在后 */
export function requiredCards(entity: EntityContent, settings: Record<string, FieldFlags>): RequiredCard[] {
  const cards: RequiredCard[] = [];
  for (const f of entity.fields) {
    if (entity.fieldDefaults?.[f.name]?.required === true) cards.push(newRequired(f.name, 'entity', true));
    if (settings[f.name]?.required === true) cards.push(newRequired(f.name, 'page', true));
  }
  return cards;
}

function newRequired(field: string, scope: RequiredScope, saved: boolean): RequiredCard {
  sequence += 1;
  return { _id: `required-${sequence}`, field, scope, saved };
}

export interface RuleCard {
  _id: string;
  key: string;
  name: string;
  version: number | null;
  dirty: boolean;
  /** 计算规则：false 单公式（expression），true 多公式（branches） */
  multi: boolean;
  content: RuleContent;
  problems: ConfigProblem[];
}

export interface RuleArea {
  pageCode: string;
  table: PageTable;
}

export function belongsTo(rule: RuleContent, area: RuleArea, masterFields: string[]) {
  if (rule.layer === 'entity') return rule.target === area.table.entity;
  if (rule.layer !== 'page' || rule.target !== area.pageCode) return false;
  if (!rule.field) return area.table.isMaster;
  if (area.table.isMaster) return masterFields.includes(rule.field);
  return !masterFields.includes(rule.field) && area.table.fields.some(f => f.name === rule.field);
}

/**
 * 规则卡片 → 配置内容：只写有值的可选字段。规则没有"数据项"（C06 v27 去掉，FC-15；旧系统的规则对话框也没有），不写 `dataItems`。
 */
export function cardContent(card: RuleCard): RuleContent {
  const c = plain(card.content);
  const out: RuleContent = { layer: c.layer, target: c.target, category: c.category, field: c.field || null, order: Number(c.order) };
  if (c.when !== undefined && c.when !== null && c.when !== '') {
    const when = isVisual(c.when) ? cleanVisual(c.when) : c.when.trim();
    if (!isVisual(when) || when.conditions.length) out.when = when;
  }
  if (c.category === 'calc') {
    if (card.multi) out.branches = (c.branches ?? []).map(b => (b.when ? { when: b.when, expression: b.expression } : { expression: b.expression }));
    else out.expression = c.expression ?? '';
  }
  if (c.category === 'validate') {
    out.level = c.level ?? 'reject';
    out.message = c.message ?? '';
  }
  if (c.category === 'ui' && c.effect) {
    const effect: NonNullable<RuleContent['effect']> = {};
    for (const name of ['editable', 'required'] as const) if (c.effect[name] !== null && c.effect[name] !== undefined) effect[name] = c.effect[name];
    for (const name of ['rowStyle', 'cellStyle'] as const) {
      const style = c.effect[name];
      if (style && Object.values(style).some(Boolean)) effect[name] = Object.fromEntries(Object.entries(style).filter(([, v]) => v));
    }
    out.effect = effect;
  }
  return out;
}

export class RuleEditor {
  readonly state = reactive({
    loading: false,
    busy: false,
    cards: [] as RuleCard[],
    removed: [] as RuleCard[],
    /** 校验规则弹窗：字段必填（字段设置），以及删掉的已保存项 */
    required: [] as RequiredCard[],
    removedRequired: [] as RequiredCard[],
    /** 保存字段必填时实体或页面被拒绝的明细 */
    requiredProblems: [] as ConfigProblem[],
    /** 本次打开后保存过字段必填（"表与列"要重新读取） */
    fieldsSaved: false,
    status: ''
  });

  private usedKeys = new Set<string>();

  /**
   * `page`：页面配置的编辑状态（页面配置各区共用的那一个）。字段必填的"本页面"范围写在它的区域字段设置中并经它保存，
   * 不另读一份页面，免得各区保存时互相覆盖；没有时不能按本页面设置。
   */
  constructor(
    private readonly store: ConfigStore,
    readonly area: RuleArea,
    readonly kind: RuleKind,
    private readonly masterFields: string[],
    private readonly notify: { success(text: string): void; error(text: string): void },
    private readonly page: ItemEditor<'page'> | null = null
  ) {}

  async load() {
    this.state.loading = true;
    try {
      if (this.kind === 'validate') {
        const entity = await this.store.load('entity', this.area.table.entity);
        this.state.required = requiredCards(entity.content, this.pageArea()?.fields ?? {});
        this.state.removedRequired = [];
      }
      const rules = await this.store.loadAll('rule');
      this.usedKeys = new Set(rules.map(r => r.key));
      this.state.cards = rules
        .filter(r => kindOf(r.content) === this.kind && belongsTo(r.content, this.area, this.masterFields))
        .sort((a, b) => a.content.order - b.content.order)
        .map(r => ({
          _id: `rule-${++sequence}`,
          key: r.key,
          name: r.name,
          version: r.version,
          dirty: false,
          multi: Boolean(r.content.branches?.length),
          content: plain(r.content),
          problems: []
        }));
      this.state.removed = [];
    } catch (error) {
      this.notify.error(errorText(error));
    } finally {
      this.state.loading = false;
    }
  }

  /** "+ 添加规则"：层级默认计算、校验为实体层，可编辑、样式为页面层（只管界面）；顺序取已有最大值加 10 */
  add(field: string | null = null) {
    const layer = this.kind === 'calc' || this.kind === 'validate' ? 'entity' : 'page';
    const target = layer === 'entity' ? this.area.table.entity : this.area.pageCode;
    const category = this.kind === 'calc' ? 'calc' : this.kind === 'validate' ? 'validate' : 'ui';
    const content: RuleContent = {
      layer,
      target,
      category,
      field,
      order: Math.max(0, ...this.state.cards.map(c => Number(c.content.order) || 0)) + 10
    };
    if (category === 'validate') Object.assign(content, { level: 'reject', message: '' });
    if (this.kind === 'editable') content.effect = { editable: false };
    if (this.kind === 'style') content.effect = { rowStyle: {} };
    const key = suggestKey(target, this.kind, field, this.usedKeys);
    this.usedKeys.add(key);
    const card: RuleCard = { _id: `rule-${++sequence}`, key, name: key, version: null, dirty: true, multi: false, content, problems: [] };
    this.state.cards.push(card);
    return card;
  }

  remove(card: RuleCard) {
    this.state.cards = this.state.cards.filter(c => c._id !== card._id);
    if (card.version !== null) this.state.removed.push(card);
  }

  /** 字段在本区域中是不是数值字段 */
  isNumber(field: string | null | undefined) {
    return Boolean(field) && this.area.table.fields.some(f => f.name === field && f.type === 'number');
  }

  /**
   * 数值字段的"规则 = 必填"：这张规则卡片换成字段必填。层级为实体时写实体默认（所有页面），本页面时写页面字段设置；
   * 卡片原来是已保存的规则时，这条规则在保存时删除（同"生成条件"替换原条件）。返回不能换的原因，能换时为空串。
   */
  toRequired(card: RuleCard): string {
    const field = card.content.field;
    if (!field) return '先选字段';
    if (!this.isNumber(field)) return `${field} 不是数值字段，用"生成条件"`;
    if (card.content.layer === 'operation') return '按操作的规则没有对应的字段必填，层级请选"实体"或"本页面"';
    const scope: RequiredScope = card.content.layer === 'page' ? 'page' : 'entity';
    if (scope === 'page' && !this.pageArea()) return '没有读到本页面的配置，不能按本页面设置必填';
    this.remove(card);
    if (this.state.required.some(r => r.field === field && r.scope === scope)) return '';
    const removed = this.state.removedRequired.find(r => r.field === field && r.scope === scope);
    if (removed) {
      this.state.removedRequired = this.state.removedRequired.filter(r => r !== removed);
      this.state.required.push(removed);
    } else this.state.required.push(newRequired(field, scope, false));
    return '';
  }

  removeRequired(card: RequiredCard) {
    this.state.required = this.state.required.filter(r => r._id !== card._id);
    if (card.saved) this.state.removedRequired.push(card);
  }

  /** 本区域在页面配置中的区域（主表区或明细区） */
  private pageArea(): PageArea | null {
    const content = this.page?.state.current?.content;
    if (!content) return null;
    const entity = this.area.table.entity;
    if (content.master.entity === entity) return content.master;
    return content.details?.find(d => d.entity === entity) ?? null;
  }

  /**
   * 保存字段必填：新加的设为必填，删掉的已保存项去掉必填；实体默认保存实体配置项，本页面保存页面配置项，都先校验。
   * 哪一项被拒绝，明细放在 `requiredProblems`，这一范围的卡片保持未保存。没有改动时不保存。
   */
  private async saveRequired(): Promise<boolean> {
    let ok = true;
    this.state.requiredProblems = [];
    for (const scope of ['entity', 'page'] as const) {
      const added = this.state.required.filter(r => r.scope === scope && !r.saved);
      const dropped = this.state.removedRequired.filter(r => r.scope === scope);
      if (added.length || dropped.length) {
        const set = added.map(r => r.field);
        const unset = dropped.map(r => r.field);
        if (await this.saveScope(scope, set, unset)) {
          for (const r of added) r.saved = true;
          this.state.removedRequired = this.state.removedRequired.filter(r => !dropped.includes(r));
          this.state.fieldsSaved = true;
        } else ok = false;
      }
    }
    return ok;
  }

  private async saveScope(scope: RequiredScope, set: string[], unset: string[]): Promise<boolean> {
    if (scope === 'page') {
      const area = this.pageArea();
      if (!this.page || !area) {
        this.notify.error('没有读到本页面的配置，不能按本页面设置必填');
        return false;
      }
      area.fields = applyRequired(area.fields ?? {}, set, unset);
      this.page.markDirty();
      if ((await this.page.save()) !== null) return true;
      this.state.requiredProblems.push(...this.page.state.problems);
      return false;
    }
    const entity = new ItemEditor(this.store, 'entity', this.notify);
    await entity.open(this.area.table.entity);
    const current = entity.state.current;
    if (!current) return false;
    const defaults = applyRequired(current.content.fieldDefaults ?? {}, set, unset);
    if (Object.keys(defaults).length) current.content.fieldDefaults = defaults;
    else delete current.content.fieldDefaults;
    entity.markDirty();
    if ((await entity.save()) !== null) return true;
    this.state.requiredProblems.push(...entity.state.problems);
    return false;
  }

  /** 层级改了：目标跟着改为区域的实体或页面编码 */
  setLayer(card: RuleCard, layer: 'entity' | 'page') {
    card.content.layer = layer;
    card.content.target = layer === 'entity' ? this.area.table.entity : this.area.pageCode;
    card.dirty = true;
  }

  /** 保存全部改动：逐条先校验再保存；有任何一条被拒绝时，其余已保存的保留，被拒绝的显示明细 */
  async save() {
    this.state.busy = true;
    let failed = 0;
    try {
      for (const card of this.state.cards.filter(c => c.dirty)) {
        const result = await this.store.save('rule', card.key, card.name, cardContent(card));
        if (result.ok) {
          card.version = result.version;
          card.dirty = false;
          card.problems = [];
        } else {
          card.problems = result.problems;
          failed += 1;
        }
      }
      for (const card of [...this.state.removed]) {
        const result = await this.store.remove('rule', card.key);
        if (result.ok) this.state.removed = this.state.removed.filter(c => c !== card);
        else {
          failed += 1;
          card.problems = result.problems;
          this.state.cards.push(card);
          this.state.removed = this.state.removed.filter(c => c !== card);
        }
      }
      if (!(await this.saveRequired())) failed += 1;
      this.state.status = failed ? `${failed} 处没有保存，见各卡片中的错误` : '规则已保存';
      if (!failed) this.notify.success('规则已保存');
      return failed === 0;
    } catch (error) {
      this.notify.error(errorText(error));
      return false;
    } finally {
      this.state.busy = false;
    }
  }
}
