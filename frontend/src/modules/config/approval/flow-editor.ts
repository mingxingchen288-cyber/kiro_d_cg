/**
 * 页面配置中"审批流"一节的状态和动作（FC-05），对照旧系统 SectionApproval.vue 的 loadAll / addFlow / addDetail /
 * removeDetails / moveAction / saveCurrent / validateCurrent / deleteCurrent。
 *
 * - 读取：全部 approvalFlow 配置项中 `page` 为本页面的；页面的表格和字段（PageCatalog）；角色、部门、人员。
 * - 保存：整条流程按 C06 第 7 节写成一个配置项，先校验再保存（ConfigStore.save），保存后回读。
 * - 校验错误按 path 定位到流程列表、某个 Tab 的某一行某一列（resolveProblems）。
 * - 删除：删除配置项；仍被引用时后端返回 422，明细同样显示。
 */
import { reactive } from 'vue';
import type { PlatformApi } from '../../../contracts/api';
import type { SchemaColumnsResponse } from '../../../contracts/http';
import { type Directory, type PageCatalog, loadDirectory, loadPageCatalog } from '../core/catalog';
import { type ConfigProblem, errorText } from '../core/errors';
import { type ConfigStore, plain } from '../core/store';
import type { Approver, BlockAction, DisplayColumn, FlowParam, NotifyRule, RowOp } from '../core/types';
import {
  type DisplayRow,
  type FlowDraft,
  type FreezeRow,
  type NodeRow,
  fromContent,
  newDisplay,
  newFreeze,
  newNode,
  rowId,
  toContent
} from './flow-model';

export type FlowTab = 'nodes' | 'freeze' | 'display';

export interface CellProblem {
  /** `flow` 为流程列表，`params`、`notify` 为参数、通知弹窗 */
  area: 'flow' | FlowTab | 'params' | 'notify';
  rowId: string | null;
  column: string | null;
  message: string;
  path: string | null;
}

export interface Notifier {
  success(text: string): void;
  error(text: string): void;
}

export const TAB_HELP: Record<FlowTab, string> = {
  nodes:
    '每级可配多个节点；本级全部节点通过才进入下一级。第 1 级的入口条件就是送审条件：审核操作勾选的每一行逐行判断，有一行成立就进入这个节点；第 1 级没有节点满足时正常保存；后续某级都不满足时，以前一级的批准结束审批。双击入口条件、审批人可编辑。',
  freeze:
    '触发审批的单据总是整张冻结，不用配；关联条件查到的行冻结（冻结表在平台注册过时，所属单据整张冻结），审批结束解冻。冻结表可以直接写表名，只能是表。',
  display:
    '修改内容按"主表一块、明细每张表一个 Tab"展示；受影响单据写关联条件，查到的行按修改表的主键勾选，全部级别通过后对勾选的行执行"审批通过后的操作"。双击关联条件、显示列、审批通过后的操作可编辑。'
};

export type DetailDialog = 'condition' | 'approvers' | 'columns' | 'actions';

/**
 * 明细表（审批节点、冻结节点、展示数据）双击某一格时打开哪个弹窗：入口条件 / 关联条件、审批人、显示列、
 * 受影响单据的通过后操作。其余格子（节点名称、冻结表、块编码、展示标题等）返回 null，双击就地编辑，
 * 不能先结束编辑（同旧系统 SectionApproval.vue 的 detailEdit，只在打开弹窗时 stopEditing）。
 */
export function detailDialog(column: string | undefined, row: { region?: string }): DetailDialog | null {
  if (column === 'condition') return 'condition';
  if (column === 'approvers') return 'approvers';
  if (column === 'columns') return 'columns';
  if (column === 'actions' && row.region === 'affected') return 'actions';
  return null;
}

export class ApprovalFlowEditor {
  readonly state = reactive({
    loading: false,
    busy: false,
    loadError: '',
    flows: [] as FlowDraft[],
    selectedKey: '',
    tab: 'nodes' as FlowTab,
    problems: [] as CellProblem[],
    status: '选择流程后编辑明细，保存时整条流程一并发布。',
    catalog: null as PageCatalog | null,
    directory: { roles: [], departments: [], users: [] } as Directory
  });

  private readonly schemaCache = new Map<string, Promise<SchemaColumnsResponse>>();

  constructor(
    private readonly store: ConfigStore,
    private readonly api: PlatformApi,
    readonly pageCode: string,
    private readonly notify: Notifier
  ) {}

  get current(): FlowDraft | undefined {
    return this.state.flows.find(f => f._key === this.state.selectedKey);
  }

  get tables() {
    return this.state.catalog?.tables ?? [];
  }

  /** 读取本页面的审批流和目录（同旧系统 loadAll：两项分别读取，失败的一项显示原因） */
  async load() {
    this.state.loading = true;
    this.state.loadError = '';
    this.state.problems = [];
    const errors: string[] = [];
    const [flows, catalog, directory] = await Promise.allSettled([
      this.store.loadAll('approvalFlow'),
      loadPageCatalog(this.store, this.pageCode),
      loadDirectory(this.api, this.store)
    ]);
    if (catalog.status === 'fulfilled') this.state.catalog = catalog.value;
    else errors.push(`页面表格读取失败：${errorText(catalog.reason)}`);
    if (directory.status === 'fulfilled') {
      const { errors: dirErrors, ...dir } = directory.value;
      this.state.directory = dir;
      errors.push(...dirErrors);
    } else errors.push(`角色、部门、人员读取失败：${errorText(directory.reason)}`);
    if (flows.status === 'fulfilled') {
      const previous = this.state.selectedKey;
      const previousKey = this.current?.key;
      this.state.flows = flows.value
        .filter(item => item.content.page === this.pageCode)
        .sort((a, b) => a.content.order - b.content.order)
        .map(item => fromContent(item.key, item.name, item.version, item.content));
      const keep = this.state.flows.find(f => f.key === previousKey);
      this.state.selectedKey = keep?._key ?? (this.state.flows.some(f => f._key === previous) ? previous : this.state.flows[0]?._key ?? '');
      this.state.status = `已读取 ${this.state.flows.length} 条审批流配置。修改后保存整条流程。`;
    } else {
      errors.push(`审批流读取失败：${errorText(flows.reason)}`);
      this.state.flows = [];
      this.state.selectedKey = '';
    }
    this.state.loadError = errors.join('；');
    this.state.loading = false;
  }

  hasDirty() {
    return this.state.flows.some(f => f.dirty);
  }

  select(key: string) {
    if (this.state.busy || key === this.state.selectedKey) return;
    this.state.selectedKey = key;
    this.state.problems = [];
  }

  markDirty() {
    const flow = this.current;
    if (flow) flow.dirty = true;
  }

  /** 新增流程：编码按"页面编码_FLOW_序号"预填，保存前可以改；顺序取已有最大值加一 */
  addFlow() {
    const used = new Set(this.state.flows.map(f => f.key));
    let n = this.state.flows.length + 1;
    while (used.has(`${this.pageCode}_FLOW_${n}`)) n += 1;
    const draft: FlowDraft = {
      _key: rowId('flow'),
      key: `${this.pageCode}_FLOW_${n}`,
      name: '新审批流程',
      version: null,
      dirty: true,
      page: this.pageCode,
      order: Math.max(0, ...this.state.flows.map(f => Number(f.order) || 0)) + 1,
      enabled: true,
      operations: {},
      nodes: [],
      freeze: [],
      display: [],
      params: [],
      notify: []
    };
    this.state.flows.push(draft);
    this.state.selectedKey = draft._key;
    this.state.problems = [];
    return draft;
  }

  rows(tab: FlowTab = this.state.tab): Array<NodeRow | FreezeRow | DisplayRow> {
    const flow = this.current;
    if (!flow) return [];
    return tab === 'nodes' ? flow.nodes : tab === 'freeze' ? flow.freeze : flow.display;
  }

  /** 新增明细（同旧系统 addDetail）：节点取选中行的级别；展示数据默认是第一张明细（没有明细时为主表） */
  addRow(selectedIds: string[] = []) {
    const flow = this.current;
    if (!flow) return null;
    let row: NodeRow | FreezeRow | DisplayRow;
    if (this.state.tab === 'nodes') {
      const selected = flow.nodes.find(n => selectedIds.includes(n._id));
      row = newNode(selected ? Number(selected.level) : Math.max(1, ...flow.nodes.map(n => Number(n.level))));
      flow.nodes.push(row as NodeRow);
    } else if (this.state.tab === 'freeze') {
      row = newFreeze();
      flow.freeze.push(row as FreezeRow);
    } else {
      const detail = this.tables.find(t => !t.isMaster);
      const master = this.tables.find(t => t.isMaster);
      const used = new Set(flow.display.map(d => d.key));
      let n = flow.display.length + 1;
      while (used.has(`block${n}`)) n += 1;
      row = newDisplay(detail ? 'detail' : 'master', detail?.entity ?? master?.entity ?? '', `block${n}`);
      (row as DisplayRow).title = detail?.title ?? master?.title ?? '修改内容';
      flow.display.push(row as DisplayRow);
    }
    this.markDirty();
    return row;
  }

  removeRows(ids: string[]) {
    const flow = this.current;
    if (!flow || !ids.length) return;
    if (this.state.tab === 'nodes') flow.nodes = flow.nodes.filter(r => !ids.includes(r._id));
    else if (this.state.tab === 'freeze') flow.freeze = flow.freeze.filter(r => !ids.includes(r._id));
    else flow.display = flow.display.filter(r => !ids.includes(r._id));
    this.markDirty();
  }

  /** 展示数据的上移、下移：块按顺序显示，也按顺序执行（C06 7.5） */
  moveDisplay(id: string, offset: -1 | 1) {
    const flow = this.current;
    if (!flow) return;
    const index = flow.display.findIndex(r => r._id === id);
    const next = index + offset;
    if (index < 0 || next < 0 || next >= flow.display.length) return;
    const rows = [...flow.display];
    [rows[index], rows[next]] = [rows[next], rows[index]];
    flow.display = rows;
    this.markDirty();
  }

  /** 展示区域或表格变了：主表块的表格固定为主表实体；明细块默认第一张明细；受影响单据清空表格，由管理员填写表或视图名 */
  regionChanged(row: DisplayRow) {
    const master = this.tables.find(t => t.isMaster);
    const details = this.tables.filter(t => !t.isMaster);
    if (row.region === 'master') row.source = master?.entity ?? '';
    if (row.region === 'detail' && !details.some(d => d.entity === row.source)) row.source = details[0]?.entity ?? '';
    if (row.region === 'affected') {
      if (this.tables.some(t => t.entity === row.source)) row.source = '';
      row.selection ??= 'checked';
    } else {
      row.targetTable = '';
      row.keyColumn = '';
      row.selection = null;
      row.actions = [];
    }
    this.markDirty();
  }

  // ---- 弹窗应用到当前草稿

  applyOperations(operations: Record<string, RowOp[]>) {
    const flow = this.current;
    if (!flow) return;
    flow.operations = Object.fromEntries(Object.entries(operations).filter(([, ops]) => ops.length > 0));
    this.markDirty();
  }

  applyCondition(row: { conditionType?: 'always' | 'sql'; condition: string }, value: { conditionType?: 'always' | 'sql'; condition: string }) {
    if (value.conditionType) row.conditionType = value.conditionType;
    row.condition = row.conditionType === 'always' ? '' : value.condition;
    this.markDirty();
  }

  applyApprovers(row: NodeRow, approvers: Approver[]) {
    row.approvers = approvers;
    this.markDirty();
  }

  applyColumns(row: DisplayRow, columns: DisplayColumn[]) {
    row.columns = columns;
    this.markDirty();
  }

  applyActions(row: DisplayRow, actions: BlockAction[]) {
    row.actions = actions;
    this.markDirty();
  }

  applyParams(params: FlowParam[]) {
    const flow = this.current;
    if (!flow) return;
    flow.params = params;
    this.markDirty();
  }

  applyNotify(rules: NotifyRule[]) {
    const flow = this.current;
    if (!flow) return;
    flow.notify = rules;
    this.markDirty();
  }

  /** 表或视图的结构（C09 `POST /api/config/schema/columns`），供显示列、主键列、写入字段选择 */
  schemaColumns(name: string): Promise<SchemaColumnsResponse> {
    const key = name.trim().toUpperCase();
    if (!key) return Promise.resolve({ objectType: null, primaryKey: null, columns: [] });
    let found = this.schemaCache.get(key);
    if (!found) {
      found = this.api.schemaColumns(key);
      found.catch(() => this.schemaCache.delete(key));
      this.schemaCache.set(key, found);
    }
    return found;
  }

  // ---- 校验、保存、删除

  async validateCurrent() {
    const flow = this.current;
    if (!flow) return false;
    this.state.busy = true;
    try {
      const problems = await this.store.validate([{ type: 'approvalFlow', key: flow.key, name: flow.name, content: toContent(flow) }]);
      this.state.problems = resolveProblems(flow, problems);
      if (!problems.length) this.notify.success('配置校验通过；尚未保存');
      return problems.length === 0;
    } catch (error) {
      this.notify.error(errorText(error));
      return false;
    } finally {
      this.state.busy = false;
    }
  }

  /** 保存并发布当前流程：先校验再保存，保存后回读（同旧系统 saveCurrent） */
  async saveCurrent() {
    const flow = this.current;
    if (!flow) return null;
    this.state.busy = true;
    try {
      const content = plain(toContent(flow));
      const result = await this.store.save('approvalFlow', flow.key, flow.name, content);
      if (!result.ok) {
        this.state.problems = resolveProblems(flow, result.problems);
        this.state.status = `保存被拒绝：${result.problems.length} 处配置需要修改，见下方。`;
        return null;
      }
      const saved = await this.store.load('approvalFlow', flow.key);
      const index = this.state.flows.findIndex(f => f._key === flow._key);
      const reread = fromContent(saved.key, saved.name, saved.version, saved.content);
      reread._key = flow._key;
      this.state.flows[index] = reread;
      this.state.problems = [];
      this.state.status = `"${saved.name}"版本 ${saved.version} 已保存并回读；已经发起的审批仍按提交时的定义走完。`;
      this.notify.success('流程已整体保存，并已回读确认');
      return content;
    } catch (error) {
      this.notify.error(errorText(error));
      return null;
    } finally {
      this.state.busy = false;
    }
  }

  async removeCurrent() {
    const flow = this.current;
    if (!flow) return;
    if (flow.version === null) {
      this.state.flows = this.state.flows.filter(f => f !== flow);
      this.state.selectedKey = this.state.flows[0]?._key ?? '';
      return;
    }
    this.state.busy = true;
    try {
      const result = await this.store.remove('approvalFlow', flow.key);
      if (!result.ok) {
        this.state.problems = resolveProblems(flow, result.problems);
        return;
      }
      this.state.flows = this.state.flows.filter(f => f !== flow);
      this.state.selectedKey = this.state.flows[0]?._key ?? '';
      this.notify.success('审批流已删除；已经发起的审批不受影响');
    } catch (error) {
      this.notify.error(errorText(error));
    } finally {
      this.state.busy = false;
    }
  }

  /** 某一格的错误文字（AG Grid 的 cellClass、tooltip 用） */
  problemAt(area: CellProblem['area'], id: string | null, column: string | null) {
    return this.state.problems.filter(p => p.area === area && p.rowId === id && (column === null || p.column === column));
  }
}

const NODE_COLUMNS = new Set(['name', 'conditionType', 'condition', 'department', 'approvers', 'mode', 'enabled']);
const DISPLAY_COLUMNS = new Set(['key', 'title', 'region', 'source', 'condition', 'targetTable', 'keyColumn', 'columns', 'selection', 'actions']);

/**
 * 后端错误 path → 界面位置：`levels[i].nodes[j].x` 是审批节点表中第 i 级第 j 个节点那一行；`freeze[i].x`、
 * `display[i].x` 是对应 Tab 的第 i 行；`display[i].columns[k].field` 落在"显示列"格；`operations.*` 落在流程列表的"审核操作"格。
 */
export function resolveProblems(flow: FlowDraft, problems: ConfigProblem[]): CellProblem[] {
  const levels = [...new Set(flow.nodes.map(n => Number(n.level)))].sort((a, b) => a - b);
  return problems.map(problem => {
    const [first, second, third] = problem.segments;
    const base = { message: problem.message, path: problem.path };
    if (problem.configType && problem.configType !== 'approvalFlow') return { ...base, area: 'flow', rowId: flow._key, column: null };
    if (first?.key === 'levels' && first.index !== null) {
      const levelNodes = flow.nodes.filter(n => Number(n.level) === levels[first.index!]);
      if (second?.key === 'nodes' && second.index !== null) {
        const node = levelNodes[second.index];
        const column = third && NODE_COLUMNS.has(third.key) ? third.key : null;
        return { ...base, area: 'nodes', rowId: node?._id ?? null, column };
      }
      return { ...base, area: 'nodes', rowId: levelNodes[0]?._id ?? null, column: 'level' };
    }
    if (first?.key === 'freeze' && first.index !== null) {
      return { ...base, area: 'freeze', rowId: flow.freeze[first.index]?._id ?? null, column: second?.key ?? null };
    }
    if (first?.key === 'display' && first.index !== null) {
      const column = second && DISPLAY_COLUMNS.has(second.key) ? second.key : null;
      return { ...base, area: 'display', rowId: flow.display[first.index]?._id ?? null, column };
    }
    if (first?.key === 'params') return { ...base, area: 'params', rowId: null, column: second?.key ?? null };
    if (first?.key === 'notify') return { ...base, area: 'notify', rowId: null, column: second?.key ?? null };
    const flowColumn = first && ['operations', 'page', 'order', 'enabled'].includes(first.key) ? first.key : null;
    return { ...base, area: 'flow', rowId: flow._key, column: flowColumn };
  });
}
