/**
 * 一个区域（页面中的主表或某个明细）某一类规则的编辑状态，对应旧系统 SectionBehavior 中的"计算规则 / 校验规则 /
 * 可编辑规则 / 样式规则 → 可视化编辑"弹窗：弹窗里一张卡片一条规则，"+ 添加规则"新增，"删除"去掉，"保存"把
 * 改动过的规则逐条保存为 `rule` 配置项（先校验再保存），删掉的已保存规则删除配置项。
 *
 * 规则属于哪个区域：`entity` 层规则按 `target` 为区域的实体；`page` 层规则（target 为页面编码）按作用字段属于哪个区域，
 * 作用于整行（field 为 null）的放在主表（C06 第 5 节没有写页面层整行规则属于哪个区域，见 contract-gaps）。
 */
import { reactive } from 'vue';
import type { PageTable } from '../core/catalog';
import { type ConfigProblem, errorText } from '../core/errors';
import { type ConfigStore, plain } from '../core/store';
import type { RuleContent } from '../core/types';
import { type RuleKind, cleanVisual, isVisual, kindOf, suggestKey } from './rule-model';

let sequence = 0;

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

/** 规则卡片 → 配置内容：只写有值的可选字段；页面层规则在前端执行，不写数据项 */
export function cardContent(card: RuleCard): RuleContent {
  const c = plain(card.content);
  const out: RuleContent = { layer: c.layer, target: c.target, category: c.category, field: c.field || null, order: Number(c.order) };
  if (c.layer !== 'page') out.dataItems = c.dataItems ?? [];
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
    status: ''
  });

  private usedKeys = new Set<string>();

  constructor(
    private readonly store: ConfigStore,
    readonly area: RuleArea,
    readonly kind: RuleKind,
    private readonly masterFields: string[],
    private readonly notify: { success(text: string): void; error(text: string): void }
  ) {}

  async load() {
    this.state.loading = true;
    try {
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

  /** 层级改了：目标跟着改为区域的实体或页面编码 */
  setLayer(card: RuleCard, layer: 'entity' | 'page') {
    card.content.layer = layer;
    card.content.target = layer === 'entity' ? this.area.table.entity : this.area.pageCode;
    if (layer === 'page') delete card.content.dataItems;
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
      this.state.status = failed ? `${failed} 条规则没有保存，见各卡片中的错误` : '规则已保存';
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
