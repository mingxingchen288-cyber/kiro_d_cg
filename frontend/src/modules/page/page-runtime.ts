/**
 * 页面运行时（page-runtime）：按页面编码打开的通用页面（单表页、主从页）的全部行为，不引用 AG Grid 和 Vue 组件，
 * 经 GridPort 驱动表格（grid-adapter 实现）。界面状态放在 `state`（Vue 的 reactive，组件直接绑定）。
 *
 * - 加载：页面视图（C05）、个人列配置、订阅 `config.changed`（FP-09）。
 * - 主表用服务端行模型，明细用客户端行模型（FP-02）；选中主表行后加载这张单据的明细。
 * - 编辑、新增、删除、撤销重做经编辑缓冲（FP-04）；编辑后在 Worker 中预览（FP-05）。
 * - 保存（FP-06、FP-07）、按钮（FP-14）、冻结时弹出审批进度（FP-16）、复制（FP-13）、Lookup 和默认值（FP-15）、
 *   个人列配置（FP-11）、高级查询。
 */
import { reactive, shallowRef } from 'vue';
import type { Ref } from 'vue';
import type { PlatformApi } from '../../contracts/api';
import type { Command, CommandResult, FieldValue, FieldValues, ResultRow } from '../../contracts/command';
import { PlatformError } from '../../contracts/errors';
import type {
  AdvancedQuery,
  ApprovalDetail,
  CurrentUser,
  DataRow,
  ListRequest,
  PersonalColumn,
  PersonalConfig,
  RecordResponse,
  RoleRef
} from '../../contracts/http';
import type { PageView, ViewButton, ViewRegion } from '../../contracts/page-view';
import type { RealtimeClient } from '../../contracts/realtime';
import type { CalcWorkerClient, RuleEffect } from '../../contracts/rules';
import type { ShellApi } from '../../contracts/shell';
import { type CopySelection, copyDetailRows, copyMaster, defaultMasterSelection } from './copy';
import type { RowId } from './edit-buffer';
import { MASTER_GRID, fieldOf, newRowValues, regionKey } from './fields';
import { failureText } from './failure';
import { canOpenLookup, fillsBack, lookupFill, lookupRequest } from './lookup';
import { columnOrder, columnsToApply, mergePersonal, personalChanges } from './personal';
import { PreviewEngine, buildDisplayRequest, buildPreviewRequest } from './preview';
import { SUMMARY_ROW_ID, detailSummary, masterSummary, sumFields } from './summary';
import { PageModel } from './view-model';

/** 表格中的一行：`__id` 为表格行标识（rowKey；新增行为 clientRowId，保存后不变） */
export type GridRow = Record<string, FieldValue> & { __id: string };

/** grid-adapter 实现的表格接口；参数中的行都用表格行标识 */
export interface GridPort {
  /** 这些行的值或标记变了：按视图模型重新给出行数据（主表 applyServerSideTransaction，明细 applyTransaction） */
  updateRows(ids: string[]): void;
  /** 插入新行：插在 `after` 那一行之后，null 为最前面 */
  insertRows(rows: Array<{ id: string; after: string | null }>): void;
  removeRows(ids: string[]): void;
  hasRow(id: string): boolean;
  /** 明细：换成这些行（客户端行模型，按行标识保留行节点） */
  setRows(ids: string[]): void;
  /** 主表：重新查询；`purge` 为 true 时从第一页开始（查询条件变了） */
  reload(purge?: boolean): void;
  selectedIds(): string[];
  select(id: string): void;
  /** 重新计算可编辑和样式（配置原地替换、只读切换） */
  refreshAll(): void;
  /** 当前的列状态，只含可见字段，按显示顺序 */
  columnState(): PersonalColumn[];
  applyColumnState(columns: PersonalColumn[]): void;
  /** 只排列列的先后（按 `ids`，不在其中的列排在后面），不改列宽、固定和显隐 */
  orderColumns(ids: string[]): void;
  stopEditing(): void;
  /** 表格显示顺序中的上一行、下一行（原地表单的上一条、下一条） */
  neighbor(id: string, offset: -1 | 1): string | null;
}

export interface PageRuntimeDeps {
  api: PlatformApi;
  calc: CalcWorkerClient;
  realtime: RealtimeClient;
  session: { user: Readonly<Ref<CurrentUser | null>>; role: Readonly<Ref<RoleRef | null>> };
  message: ShellApi['message'];
  tabs?: ShellApi['tabs'];
  /** 本页面的路由路径，用于标记页签有未保存修改 */
  path?: string;
  now?: () => Date;
  /** 编辑后多久开始预览（毫秒）；测试用 0 */
  previewDelay?: number;
}

export interface LookupState {
  entity: string;
  id: string;
  field: string;
  title: string;
  fillBack: boolean;
  multiple: boolean;
  keyword: string;
  keywordSearch: boolean;
  rows: FieldValues[];
  total: number;
  loading: boolean;
  error: string;
}

export interface CopyState {
  entity: string;
  /** 主表区复制时的源单据；明细区复制时为所在单据 */
  recordId: string;
  /** 明细区复制时默认勾选的行（表格中选中的行） */
  rows: string[];
  selection: CopySelection;
}

export interface FrozenState {
  loading: boolean;
  items: ApprovalDetail[];
  /** 错误明细中没有 approvalId 时的提示 */
  message: string;
}

export const BUILTIN_ACTIONS = ['addRow', 'deleteRow', 'copyRow', 'saveGridConfig'] as const;

/**
 * 主表一块数据、一张单据的明细交给表格前，最多等显示求值这么久（毫秒）：通常几十毫秒内就有结果，行一出来就带样式；
 * 规则包或 Worker 还没就绪时不让表格一直空着，先显示，结果到了再刷新这些行。
 */
const DISPLAY_WAIT = 1000;

/** `task` 完成或过了 `ms` 毫秒，先到者为准；`task` 出错也算完成 */
function within(task: Promise<unknown>, ms: number): Promise<void> {
  return new Promise(resolve => {
    const timer = setTimeout(resolve, ms);
    const done = () => {
      clearTimeout(timer);
      resolve();
    };
    task.then(done, done);
  });
}

export class PageRuntime {
  readonly view = shallowRef<PageView | null>(null);
  readonly state = reactive({
    status: 'loading' as 'loading' | 'ready' | 'error',
    error: '',
    saving: false,
    /** 有未保存修改的行数 */
    dirtyCount: 0,
    canUndo: false,
    canRedo: false,
    /** 明细区显示的单据（主表行标识） */
    activeRecord: null as string | null,
    /** 原地表单打开的主表行 */
    formRecord: null as string | null,
    detailMode: 'tabs' as 'tabs' | 'stack',
    activeDetail: '',
    /** 各区域选中的行数，键为 master 或明细实体 */
    selected: {} as Record<string, number>,
    previewError: '',
    total: 0,
    /** 页面视图换了（配置原地替换）时加一，列定义随之重算 */
    viewVersion: 0,
    /** 字典加载后加一，下拉和显示随之重算 */
    dictVersion: 0,
    /** 数据（编辑缓冲、正式数据、预览）变了就加一：原地表单等不经表格显示的地方据此重算 */
    revision: 0
  });

  /** 结构较深的界面状态用 shallowRef，整体替换 */
  readonly ui = {
    /** 预览给出的规则提示和拒绝 */
    effects: shallowRef<RuleEffect[]>([]),
    advanced: shallowRef<AdvancedQuery | null>(null),
    aggregates: shallowRef<FieldValues>({}),
    lookup: shallowRef<LookupState | null>(null),
    copy: shallowRef<CopyState | null>(null),
    /** 审批进度弹窗（FP-16） */
    frozen: shallowRef<FrozenState | null>(null)
  };

  model!: PageModel;
  personal: PersonalConfig = {};
  readonly dicts = new Map<string, Map<string, string>>();
  private readonly ports = new Map<string, GridPort>();
  private readonly preview: PreviewEngine;
  private readonly previewTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly pendingPreviews = new Set<Promise<void>>();
  /** 每张单据最近一次显示求值的序号：先发的结果晚到时不用（以后一次为准） */
  private readonly displaySeq = new Map<string, number>();
  /** 配置变更后，等表格换上新的列再按页面视图重排列的区域（columnsLoaded） */
  private readonly reorderPending = new Set<string>();
  private readonly unsubscribers: Array<() => void> = [];
  private loadToken = 0;
  /** 保存、业务按钮的结果写进模型的次数：单据加载期间这个数变了，读到的可能是写入前的数据（见 ensureRecord） */
  private resultGeneration = 0;

  constructor(
    readonly pageCode: string,
    private readonly deps: PageRuntimeDeps
  ) {
    this.preview = new PreviewEngine(deps.calc, (packId, version) =>
      deps.api.rulesPack(packId, version, this.backgroundPack)
    );
  }

  /** 配置变更后重新读取的规则包是后台请求（C09 第 1 节） */
  private backgroundPack = false;

  /** 最近一次主表列表请求（排序、筛选、高级查询），保存后重新取汇总时用 */
  private lastQuery: ListRequest | null = null;

  private get api() {
    return this.deps.api;
  }

  private now() {
    return this.deps.now?.() ?? new Date();
  }

  // ================================================================ 加载

  async load() {
    try {
      const view = await this.api.pageView(this.pageCode);
      this.model = new PageModel(view);
      this.view.value = view;
      this.state.activeDetail = view.details[0]?.entity ?? '';
      try {
        this.personal = await this.api.personal(this.pageCode);
      } catch {
        this.personal = {};
      }
      this.state.detailMode = this.personal.detailMode ?? view.detailMode;
      this.state.status = 'ready';
      this.loadDicts(view);
      this.deps.realtime.subscribe([this.pageCode]);
      this.unsubscribers.push(
        this.deps.realtime.onEvent('config.changed', payload => {
          if (payload.pages.includes(this.pageCode)) void this.reloadView();
        })
      );
      this.deps.tabs?.open(this.deps.path ?? `/page/${this.pageCode}`, view.title);
    } catch (error) {
      this.state.status = 'error';
      this.state.error = messageOf(error);
    }
  }

  dispose() {
    this.deps.realtime.unsubscribe([this.pageCode]);
    for (const off of this.unsubscribers) off();
    for (const timer of this.previewTimers.values()) clearTimeout(timer);
  }

  private loadDicts(view: PageView) {
    const types = new Set(
      [view.master, ...view.details].flatMap(r => r.fields.map(f => f.dictType)).filter(Boolean) as string[]
    );
    for (const type of types) {
      if (this.dicts.has(type)) continue;
      this.dicts.set(type, new Map());
      this.api
        .dict(type)
        .then(response => {
          this.dicts.set(type, new Map(response.items.map(item => [item.value, item.label])));
          this.state.dictVersion += 1;
          for (const port of this.ports.values()) port.refreshAll();
        })
        .catch(error => this.deps.message.error(`字典 ${type} 读取失败：${messageOf(error)}`));
    }
  }

  /** FP-09：收到 config.changed 后重新读取页面视图和规则包，原地替换；正在编辑的值保留 */
  async reloadView() {
    try {
      const view = await this.api.pageView(this.pageCode, true);
      this.backgroundPack = true;
      this.model.replaceView(view);
      this.view.value = view;
      if (!view.details.some(d => d.entity === this.state.activeDetail))
        this.state.activeDetail = view.details[0]?.entity ?? '';
      // 列的先后在表格换上新的列之后按页面视图重排（columnsLoaded）
      for (const entity of this.ports.keys()) this.reorderPending.add(entity);
      this.state.viewVersion += 1;
      this.loadDicts(view);
      for (const port of this.ports.values()) port.refreshAll();
      // 规则包可能换了版本：重新预览有修改的单据，已显示的单据重新做显示求值
      for (const recordId of this.model.buffer.dirtyRecords()) this.schedulePreview(recordId);
      void this.display(this.model.displayedRecords());
    } catch (error) {
      this.deps.message.error(`页面配置已变更，重新读取失败：${messageOf(error)}`);
    }
  }

  // ================================================================ 表格

  attach(entity: string, port: GridPort) {
    this.ports.set(entity, port);
    const view = this.view.value;
    const region = view && this.model.region(entity);
    if (!view || !region) return;
    const grid = this.personal.grids?.[regionKey(view, entity)];
    const columns = columnsToApply(region, grid ?? undefined);
    if (columns.length) port.applyColumnState(columns);
    if (entity !== view.master.entity && this.state.activeRecord)
      port.setRows(this.detailGridIds(entity, this.state.activeRecord));
  }

  detach(entity: string, port: GridPort) {
    if (this.ports.get(entity) === port) this.ports.delete(entity);
  }

  /**
   * 表格换上了新的列（grid-adapter 在 AG Grid 的 newColumnsLoaded 时调用）。配置变更（FP-09）后列的先后按页面视图，
   * 与刷新页面后相同：个人列配置中的列按个人配置，其余按页面视图的顺序排在后面（personal.ts 的 columnOrder）。
   * AG Grid 的 maintainColumnOrder 会把重新显示的列放到最右边，所以这里重排一次；列宽、固定、显隐不变。
   */
  columnsLoaded(entity: string) {
    if (!this.reorderPending.delete(entity)) return;
    const view = this.view.value;
    const region = view && this.model.region(entity);
    if (!view || !region) return;
    this.port(entity)?.orderColumns(columnOrder(region, this.personal.grids?.[regionKey(view, entity)] ?? undefined));
  }

  private port(entity: string) {
    return this.ports.get(entity);
  }

  gridRow(entity: string, gridId: string): GridRow {
    const id = this.model.rowIdOf(gridId);
    return { ...this.model.values(entity, id), __id: gridId };
  }

  /**
   * 区域底部的汇总行（C06 第 3 节 `aggregate`，见 summary.ts）：主表区为列表的汇总加上还没保存的修改，
   * 明细区为当前单据的明细行之和。没有求和的列或没有行时为 null。
   */
  summaryRow(entity: string): GridRow | null {
    const view = this.view.value;
    const region = view && this.model.region(entity);
    if (!view || !region) return null;
    const values =
      entity === view.master.entity
        ? masterSummary(this.model, this.ui.aggregates.value)
        : detailSummary(this.model, region, this.state.activeRecord);
    return values ? { ...values, __id: SUMMARY_ROW_ID } : null;
  }

  private detailGridIds(entity: string, recordId: string) {
    return this.model.detailIds(entity, recordId).map(id => this.model.gridId(id));
  }

  /** 主表的服务端行模型数据源（C09 第 4 节列表）；第一页最前面放还没保存的新增主表行 */
  async fetchMasterRows(request: Pick<ListRequest, 'startRow' | 'endRow' | 'sortModel' | 'filterModel'>) {
    const body: ListRequest = { ...request };
    if (this.ui.advanced.value) body.advanced = this.ui.advanced.value;
    this.lastQuery = body;
    const response = await this.api.listRows(this.pageCode, body);
    this.model.registerMasterRows(response.rows);
    this.state.total = response.total;
    this.ui.aggregates.value = response.aggregates;
    // 这一块的行一显示就带界面规则的效果（FP-18）：每块只在取到数据时求值一次，滚动时表格用缓存的块，不再求值
    await within(this.display(response.rows.map(r => r.rowKey)), DISPLAY_WAIT);
    const added = request.startRow === 0 ? this.model.newMasterRows().map(r => this.model.gridId(r.id)) : [];
    const master = this.model.master;
    const rows = [...added, ...response.rows.map(r => this.model.gridId(r.rowKey))].map(id => this.gridRow(master, id));
    return { rows, total: response.total + added.length };
  }

  /**
   * 汇总行（C06 第 3 节 `aggregate`）：保存或按钮成功后正式数据变了，按最近一次列表请求的条件重新取主表的汇总
   * （`startRow` 等于 `endRow`，只取总数和汇总，C09 第 4 节）。主表没有求和的列时不取。
   */
  private async refreshAggregates() {
    const view = this.view.value;
    if (!view || !this.lastQuery || !sumFields(view.master).length) return;
    try {
      const response = await this.api.listRows(this.pageCode, { ...this.lastQuery, startRow: 0, endRow: 0 });
      this.ui.aggregates.value = response.aggregates;
      this.state.total = response.total;
    } catch (error) {
      this.deps.message.error(`汇总读取失败：${messageOf(error)}`);
    }
  }

  /** 选中行变了（表格行标识） */
  onSelection(entity: string, gridIds: string[]) {
    const view = this.view.value;
    if (!view) return;
    this.state.selected = { ...this.state.selected, [regionKey(view, entity)]: gridIds.length };
    if (entity === view.master.entity && gridIds.length && view.details.length) {
      void this.activate(this.model.rowIdOf(gridIds[gridIds.length - 1]));
    }
  }

  selectedRows(entity: string): string[] {
    return (this.port(entity)?.selectedIds() ?? []).map(id => this.model.rowIdOf(id));
  }

  /** 明细区显示这张单据：还没加载时按单据加载接口读取（C09 第 4 节） */
  async activate(recordId: string) {
    this.state.activeRecord = recordId;
    await this.ensureRecord(recordId);
    if (this.state.activeRecord !== recordId) return;
    for (const detail of this.view.value?.details ?? [])
      this.port(detail.entity)?.setRows(this.detailGridIds(detail.entity, recordId));
  }

  private async ensureRecord(recordId: string) {
    if (this.model.isRecordLoaded(recordId)) return;
    if (this.model.buffer.isNew(this.model.master, recordId)) {
      this.model.ensureNewRecord(recordId);
      return;
    }
    this.loadToken += 1;
    try {
      // 读取期间保存或按钮的结果已写进模型时重新读取：例如改了 200680 的备注马上保存，预览补读这张单据的响应晚于保存结果到达，
      // 读到的是保存前的备注，登记进去会把刚保存的值改回旧值
      let generation: number;
      let record: RecordResponse;
      do {
        generation = this.resultGeneration;
        // eslint-disable-next-line no-await-in-loop
        record = await this.api.loadRecord(this.pageCode, recordId);
      } while (generation !== this.resultGeneration);
      this.model.registerRecord(recordId, record);
      // 正式数据变了：明细区的汇总行等据此重算
      this.state.revision += 1;
      // 明细一显示就带界面规则的效果（FP-18）：这张单据带明细重新做显示求值
      await within(this.display([recordId]), DISPLAY_WAIT);
    } catch (error) {
      this.deps.message.error(`单据 ${recordId} 的明细读取失败：${messageOf(error)}`);
    }
  }

  // ================================================================ 编辑

  /** 单元格能否编辑：保存期间整页只读；其余见 PageModel.cellEditable。每次都取最新的规则 */
  cellEditable(entity: string, gridId: string, field: string) {
    if (this.state.saving) return false;
    const meta = this.view.value && fieldOf(this.view.value, entity, field);
    if (meta?.lookup && fillsBack(meta.lookup)) return false;
    return this.model.cellEditable(entity, this.model.rowIdOf(gridId), field);
  }

  /** 行所在单据被冻结时，冻结它的审批 */
  frozenBy(entity: string, gridId: string) {
    return this.model.frozenBy(entity, this.model.rowIdOf(gridId));
  }

  /**
   * 用户试图修改：被冻结的单据不进入编辑，直接弹出锁定它的审批进度（FP-16）。返回 true 表示可以继续。
   */
  guard(entity: string, id: string): boolean {
    const approvalId = this.model.frozenBy(entity, id);
    if (!approvalId) return true;
    void this.showApprovals([approvalId]);
    return false;
  }

  /** 表格或表单改了一格（表格行标识）；返回是否接受 */
  edit(entity: string, gridId: string, field: string, value: FieldValue): boolean {
    const id = this.model.rowIdOf(gridId);
    if (!this.guard(entity, id)) return false;
    if (this.state.saving || !this.model.cellEditable(entity, id, field)) return false;
    this.model.buffer.set(entity, id, field, value);
    this.changed([{ entity, id }]);
    return true;
  }

  /** 粘贴等一次改多格时合成一个撤销步骤 */
  beginBatch() {
    this.model.buffer.beginBatch();
  }

  endBatch() {
    this.model.buffer.endBatch();
    this.syncState();
  }

  undo() {
    if (this.state.saving) return;
    const rows = this.model.buffer.undo();
    if (rows) this.restructured(rows);
  }

  redo() {
    if (this.state.saving) return;
    const rows = this.model.buffer.redo();
    if (rows) this.restructured(rows);
  }

  /** 撤销、重做可能让新增行出现或消失：按编辑缓冲的状态调整表格 */
  private restructured(rows: RowId[]) {
    const master = this.model.master;
    const masterPort = this.port(master);
    for (const row of rows.filter(r => r.entity === master)) {
      const gridId = this.model.gridId(row.id);
      const exists = this.model.buffer.isNew(master, row.id) || Boolean(this.model.buffer.committed(master, row.id));
      if (!masterPort) continue;
      if (exists && !masterPort.hasRow(gridId)) masterPort.insertRows([{ id: gridId, after: null }]);
      else if (!exists && masterPort.hasRow(gridId)) {
        masterPort.removeRows([gridId]);
        if (this.state.activeRecord === row.id) this.state.activeRecord = null;
        if (this.state.formRecord === row.id) this.state.formRecord = null;
      }
    }
    const record = this.state.activeRecord;
    if (record) {
      for (const detail of this.view.value?.details ?? [])
        this.port(detail.entity)?.setRows(this.detailGridIds(detail.entity, record));
    }
    this.changed(rows);
  }

  /** 修改之后：刷新这些行，更新未保存计数，安排预览 */
  private changed(rows: RowId[]) {
    const byEntity = new Map<string, string[]>();
    for (const row of rows) {
      const list = byEntity.get(row.entity) ?? [];
      list.push(this.model.gridId(row.id));
      byEntity.set(row.entity, list);
    }
    for (const [entity, ids] of byEntity) {
      const port = this.port(entity);
      if (port) port.updateRows(ids.filter(id => port.hasRow(id)));
    }
    this.syncState();
    const records = new Set(rows.map(r => this.model.buffer.recordOf(r.entity, r.id)).filter(Boolean) as string[]);
    for (const recordId of records) this.schedulePreview(recordId);
  }

  private syncState() {
    const buffer = this.model.buffer;
    this.state.revision += 1;
    this.state.dirtyCount = buffer.size;
    this.state.canUndo = buffer.canUndo;
    this.state.canRedo = buffer.canRedo;
    this.deps.tabs?.setDirty(this.deps.path ?? `/page/${this.pageCode}`, buffer.dirty);
  }

  get dirty() {
    return this.model?.buffer.dirty ?? false;
  }

  // ================================================================ 按钮（FP-14）

  /**
   * 区域中显示的按钮：新增、删除只在页面配置放了这两个按钮的区域显示，且要 `systemButtons` 含对应项；
   * 其他按钮按区域的 `buttons` 显示，顺序为页面配置的顺序。
   */
  regionButtons(region: ViewRegion): ViewButton[] {
    const view = this.view.value;
    if (!view) return [];
    return region.buttons.filter(button => {
      if (button.action === 'addRow' || button.action === 'deleteRow')
        return view.systemButtons.includes(button.action);
      return true;
    });
  }

  /** 按钮是否可用：没有选中行时 requiresSelection 的按钮不可用；没有保存按钮时整页只读，新增、删除、复制不可用 */
  buttonEnabled(region: ViewRegion, button: ViewButton): boolean {
    const view = this.view.value;
    if (!view || this.state.saving) return false;
    const editing = button.action === 'addRow' || button.action === 'deleteRow' || button.action === 'copyRow';
    if (editing && !view.systemButtons.includes('save')) return false;
    if (region.entity !== view.master.entity && !this.state.activeRecord) return button.action === 'saveGridConfig';
    const selected = this.state.selected[regionKey(view, region.entity)] ?? 0;
    if (button.requiresSelection && selected === 0) return false;
    return true;
  }

  async clickButton(region: ViewRegion, button: ViewButton) {
    if (!this.buttonEnabled(region, button)) return;
    switch (button.action) {
      case 'addRow':
        await this.addRow(region.entity);
        return;
      case 'deleteRow':
        this.deleteSelected(region.entity);
        return;
      case 'copyRow':
        await this.openCopy(region.entity);
        return;
      case 'saveGridConfig':
        await this.saveGridConfig();
        return;
      default:
        if (button.operation) await this.runOperation(region, button);
    }
  }

  // ================================================================ 新增、删除

  async addRow(entity: string) {
    const view = this.view.value;
    if (!view) return;
    const region = this.model.region(entity)!;
    const values = newRowValues(region, {
      user: this.deps.session.user.value,
      role: this.deps.session.role.value,
      now: this.now()
    });
    const buffer = this.model.buffer;
    if (entity === view.master.entity) {
      // 与旧系统相同：插在选中行的下方，没有选中行时插在最前面
      const anchor = this.port(entity)?.selectedIds()[0] ?? null;
      const id = buffer.addRow(entity, null, values, anchor ? this.model.rowIdOf(anchor) : null);
      this.model.ensureNewRecord(id);
      this.port(entity)?.insertRows([{ id, after: anchor }]);
      this.port(entity)?.select(id);
      this.changed([{ entity, id }]);
      if (view.details.length) await this.activate(id);
      return;
    }
    const recordId = this.state.activeRecord;
    if (!recordId || !this.guard(view.master.entity, recordId)) return;
    await this.ensureRecord(recordId);
    // 与旧系统相同：明细新增行放在最后
    const order = this.model.detailIds(entity, recordId);
    const after = order.length ? order[order.length - 1] : null;
    const id = buffer.addRow(entity, recordId, values, after);
    this.port(entity)?.insertRows([{ id, after: after && this.model.gridId(after) }]);
    this.changed([{ entity, id }]);
  }

  /** 删除选中的行：已保存的行标为删除，新增行直接去掉（与旧系统相同） */
  deleteSelected(entity: string) {
    const ids = this.selectedRows(entity);
    if (!ids.length) return;
    for (const id of ids) if (!this.guard(entity, id)) return;
    const buffer = this.model.buffer;
    const removed: string[] = [];
    buffer.batch(() => {
      for (const id of ids) {
        if (buffer.isNew(entity, id)) removed.push(this.model.gridId(id));
        buffer.deleteRow(entity, id);
      }
    });
    this.port(entity)?.removeRows(removed);
    if (
      entity === this.model.master &&
      this.state.activeRecord &&
      removed.includes(this.model.gridId(this.state.activeRecord))
    ) {
      this.state.activeRecord = null;
      for (const detail of this.view.value?.details ?? []) this.port(detail.entity)?.setRows([]);
    }
    this.changed(ids.filter(id => !removed.includes(this.model.gridId(id))).map(id => ({ entity, id })));
  }

  // ================================================================ 预览（FP-05）

  private schedulePreview(recordId: string) {
    const delay = this.deps.previewDelay ?? 150;
    clearTimeout(this.previewTimers.get(recordId));
    this.previewTimers.set(
      recordId,
      setTimeout(() => {
        this.previewTimers.delete(recordId);
        const task = this.runPreview(recordId).finally(() => this.pendingPreviews.delete(task));
        this.pendingPreviews.add(task);
      }, delay)
    );
  }

  /** 等待已安排的预览完成（测试用） */
  async settled() {
    while (this.previewTimers.size || this.pendingPreviews.size) {
      await new Promise(resolve => setTimeout(resolve, 0));
      await Promise.all([...this.pendingPreviews]);
    }
  }

  private async runPreview(recordId: string) {
    const view = this.view.value;
    if (!view) return;
    const master = view.master.entity;
    if (!this.model.buffer.current(master, recordId)) return;
    if (view.details.length) await this.ensureRecord(recordId);
    try {
      const request = buildPreviewRequest(this.model, recordId, {
        user: this.deps.session.user.value,
        role: this.deps.session.role.value,
        now: this.now()
      });
      const result = await this.preview.evaluate(view, request);
      if (!result.ok) {
        this.state.previewError = `本地预览失败：${result.error.message}`;
        return;
      }
      this.state.previewError = '';
      const changed = this.model.setPreview(result.rows);
      this.model.setEffects(recordId, result.effects);
      this.ui.effects.value = this.model.allEffects();
      this.refreshRows(changed);
    } catch (error) {
      this.state.previewError = `本地预览不可用：${messageOf(error)}`;
    }
  }

  // ================================================================ 显示求值（FP-18）

  /**
   * 这些单据一显示就执行界面规则（C07 v6 第 3.1 节 `purpose: display`，对应旧系统 GRID_STYLE 渲染行时按行数据算样式）：
   * 明细已加载的单据带上明细，没加载的只求主表行。结果只记界面规则的行样式、单元格样式、可编辑和必填，不改显示的值，
   * 不给校验提示；效果有变化的行重新显示。Worker 或规则包不可用时提示，页面照常显示和编辑。
   * 加入 pendingPreviews，`settled()` 一起等待。
   */
  private display(recordIds: string[]): Promise<void> {
    const task: Promise<void> = this.runDisplay([...new Set(recordIds)]).finally(() =>
      this.pendingPreviews.delete(task)
    );
    this.pendingPreviews.add(task);
    return task;
  }

  private async runDisplay(recordIds: string[]) {
    const view = this.view.value;
    if (!view || !recordIds.length) return;
    const master = view.master.entity;
    const ctx = { user: this.deps.session.user.value, role: this.deps.session.role.value, now: this.now() };
    const jobs = recordIds
      .filter(id => this.model.buffer.current(master, id))
      .map(id => {
        const seq = (this.displaySeq.get(id) ?? 0) + 1;
        this.displaySeq.set(id, seq);
        return { id, seq, result: this.preview.evaluate(view, buildDisplayRequest(this.model, id, ctx)) };
      });
    const outcomes = await Promise.allSettled(jobs.map(job => job.result));
    const changed: RowId[] = [];
    outcomes.forEach((outcome, index) => {
      const { id, seq } = jobs[index];
      if (this.displaySeq.get(id) !== seq) return;
      if (outcome.status === 'rejected') {
        this.state.previewError = `本地预览不可用：${messageOf(outcome.reason)}`;
      } else if (!outcome.value.ok) {
        this.state.previewError = `界面规则求值失败：${outcome.value.error.message}`;
      } else {
        changed.push(...this.model.setDisplay(outcome.value.rows));
      }
    });
    if (changed.length) this.refreshRows(changed);
  }

  private refreshRows(rows: RowId[]) {
    this.state.revision += 1;
    const byEntity = new Map<string, string[]>();
    for (const row of rows) byEntity.set(row.entity, [...(byEntity.get(row.entity) ?? []), this.model.gridId(row.id)]);
    for (const [entity, ids] of byEntity) {
      const port = this.port(entity);
      const shown = port ? ids.filter(id => port.hasRow(id)) : [];
      if (port && shown.length) port.updateRows(shown);
    }
  }

  // ================================================================ 保存（FP-06、FP-07、FP-16）

  async save(): Promise<CommandResult | null> {
    const view = this.view.value;
    if (!view || this.state.saving || !view.systemButtons.includes('save')) return null;
    for (const port of this.ports.values()) port.stopEditing();
    const buffer = this.model.buffer;
    const documents = buffer.documents();
    if (!documents.length) {
      this.deps.message.success('没有需要保存的修改');
      return null;
    }
    const command: Command = {
      requestKey: crypto.randomUUID(),
      page: view.pageCode,
      operation: view.saveOperation,
      documents,
      params: {}
    };
    this.refreshRows(this.model.clearErrors());
    this.state.saving = true;
    for (const port of this.ports.values()) port.refreshAll();
    let result: CommandResult;
    try {
      result = await this.api.runCommand(command);
    } catch (error) {
      this.state.saving = false;
      for (const port of this.ports.values()) port.refreshAll();
      await this.failed(error);
      return null;
    }
    this.state.saving = false;
    await this.applySaveResult(result);
    for (const port of this.ports.values()) port.refreshAll();
    return result;
  }

  /** 保存或按钮失败：编辑缓冲不变；冻结时弹出审批进度，其他错误定位到行和字段 */
  private async failed(error: unknown) {
    if (error instanceof PlatformError && error.code === 'FROZEN_BY_APPROVAL') {
      if (error.frozenBy.length) {
        await this.showApprovals(error.frozenBy);
        return;
      }
    }
    if (error instanceof PlatformError && error.details.length) {
      const located = error.details
        .filter(d => d.entity && (d.rowKey || d.clientRowId))
        .map(d => ({
          entity: d.entity!,
          id: (d.rowKey ?? d.clientRowId)!,
          field: d.field,
          message: d.message ?? error.message
        }));
      this.refreshRows(this.model.setErrors(located));
      // 同样的话只说一次，并指出是哪些行（failure.ts）
      const view = this.view.value;
      this.deps.message.error(
        view ? failureText(view, error, (entity, id) => this.model.values(entity, id)) : error.message
      );
      return;
    }
    this.deps.message.error(messageOf(error));
  }

  /**
   * 保存成功：逐行比对命令结果，只更新有差异的行，按 idMap 换主键（表格行节点不变）；结果中缺的行按主键补查，
   * 补查失败时重查当前页；提交审批的单据显示正式数据（新增行移除、删除和修改恢复）。最后清空编辑缓冲。
   */
  private async applySaveResult(result: CommandResult) {
    this.resultGeneration += 1;
    const view = this.view.value!;
    const master = view.master.entity;
    const buffer = this.model.buffer;
    const submitted = new Set(
      result.approvals.filter(a => a.document.entity === master).map(a => a.document.recordKey)
    );
    const pendingRows = buffer.dirtyRows();
    const recordIds = buffer.dirtyRecords();
    const orders = this.model.captureOrders(recordIds);
    // 提交审批的单据：idMap 中的主键是提交时取得的，审批通过后才写入
    const submittedIds = new Set(recordIds.filter(id => submitted.has(result.idMap[id] ?? id)));
    const toUpdate = new Map<string, Set<string>>();
    const mark = (entity: string, gridId: string) => {
      const set = toUpdate.get(entity) ?? new Set<string>();
      set.add(gridId);
      toUpdate.set(entity, set);
    };
    const toRemove = new Map<string, string[]>();
    const remove = (entity: string, gridId: string) => toRemove.set(entity, [...(toRemove.get(entity) ?? []), gridId]);

    // 新增的单据保存后：明细改记在正式主键下
    for (const recordId of recordIds) {
      const key = result.idMap[recordId];
      if (key && !submittedIds.has(recordId)) this.model.renameRecord(recordId, key);
    }
    const returned = new Set<string>();
    const dirtyKeys = new Set(pendingRows.map(r => `${r.entity}\u0000${r.id}`));
    for (const row of result.rows) {
      if ('deleted' in row) {
        const gridId = this.model.gridId(row.rowKey);
        this.model.removeRow(row.entity, row.rowKey);
        remove(row.entity, gridId);
        returned.add(`${row.entity}\u0000${row.rowKey}`);
        continue;
      }
      const sourceId = row.clientRowId ?? row.rowKey;
      // 逐行比对：没有未保存修改、显示的值也与结果相同的行不更新
      const before = this.model.values(row.entity, sourceId);
      const unchanged =
        !dirtyKeys.has(`${row.entity}\u0000${sourceId}`) &&
        Object.entries(row.values).every(([field, value]) => (before[field] ?? null) === value) &&
        (this.model.frozenBy(row.entity, sourceId) ?? null) === (row.frozen?.approvalId ?? null);
      const recordKey = this.recordKeyOf(row, result);
      const gridId = this.model.applyResultRow(row, recordKey);
      returned.add(`${row.entity}\u0000${row.rowKey}`);
      if (row.clientRowId) returned.add(`${row.entity}\u0000${row.clientRowId}`);
      if (!unchanged) mark(row.entity, gridId);
    }
    // 结果中缺的行：已保存的行按主键补查；提交审批的单据中的新增行移除
    const missing = new Map<string, string[]>();
    for (const row of pendingRows) {
      if (returned.has(`${row.entity}\u0000${row.id}`)) continue;
      const recordId = buffer.recordOf(row.entity, row.id)!;
      if (buffer.isNew(row.entity, row.id)) {
        const key = result.idMap[row.id];
        if (submittedIds.has(recordId) || !key) remove(row.entity, this.model.gridId(row.id));
        else missing.set(row.entity, [...(missing.get(row.entity) ?? []), key]);
        continue;
      }
      if (submittedIds.has(recordId)) {
        mark(row.entity, this.model.gridId(row.id));
        continue;
      }
      missing.set(row.entity, [...(missing.get(row.entity) ?? []), row.id]);
    }
    this.model.clearPreview(pendingRows);
    buffer.clear();
    this.model.restoreOrders(orders, result.idMap);
    for (const approval of result.approvals) {
      if (approval.document.entity !== master || approval.status !== 'pending') continue;
      this.model.freezeRecord(approval.document.recordKey, approval.approvalId);
      const gridId = this.model.gridId(approval.document.recordKey);
      if (this.port(master)?.hasRow(gridId)) mark(master, gridId);
    }
    // 结果中写入的行也按主键重读（FP-06，同旧系统保存后后端重查主表行、前端重读明细：DynamicDataService.java 第
    // 1232–1255 行、useWorkingSetStore.ts 第 1047–1076 行）：只在读取视图中的字段、数据库端的默认值（例如新单据的币种
    // "人民币"）命令结果里没有，重读后与重新打开单据看到的相同。提交审批的单据显示的就是正式数据，不重读
    for (const row of result.rows) {
      if ('deleted' in row || row.frozen) continue;
      const keys = missing.get(row.entity) ?? [];
      if (!keys.includes(row.rowKey)) missing.set(row.entity, [...keys, row.rowKey]);
    }
    let reloadNeeded = false;
    for (const [entity, rowKeys] of missing) {
      try {
        // eslint-disable-next-line no-await-in-loop
        const response = await this.api.rowsByKeys(this.pageCode, { entity, rowKeys });
        this.model.registerRows(entity, response.rows);
        for (const row of response.rows) mark(entity, this.model.gridId(row.rowKey));
      } catch {
        reloadNeeded = true;
      }
    }
    for (const [entity, ids] of toRemove) this.port(entity)?.removeRows(ids);
    for (const [entity, ids] of toUpdate) {
      const port = this.port(entity);
      if (port) port.updateRows([...ids].filter(id => port.hasRow(id)));
    }
    // 明细区显示的单据：新增的单据保存后换成正式主键；提交审批的新增单据已移除
    const active = this.state.activeRecord;
    if (active) {
      const next = !submittedIds.has(active) && result.idMap[active] ? result.idMap[active] : active;
      this.state.activeRecord = this.model.buffer.current(master, next) ? next : null;
      for (const detail of view.details) {
        this.port(detail.entity)?.setRows(
          this.state.activeRecord ? this.detailGridIds(detail.entity, this.state.activeRecord) : []
        );
      }
    }
    if (this.state.formRecord && !this.model.buffer.current(master, this.state.formRecord)) {
      const key = result.idMap[this.state.formRecord];
      this.state.formRecord = key && this.model.buffer.current(master, key) ? key : null;
    }
    if (reloadNeeded) this.port(master)?.reload();
    this.ui.effects.value = [];
    this.syncState();
    this.announce(result, '已保存');
    // 预览已清掉：保存过的单据按保存后的值重新做显示求值（FP-18）
    const saved = result.rows.filter(r => !('deleted' in r) && r.entity === master).map(r => r.rowKey);
    void this.display([...recordIds.map(id => result.idMap[id] ?? id), ...saved]);
    await this.refreshAggregates();
  }

  /** 命令结果中的行属于哪张单据 */
  private recordKeyOf(row: ResultRow, result: CommandResult) {
    const master = this.model.master;
    if (row.entity === master) return row.rowKey;
    const buffer = this.model.buffer;
    const recordId =
      buffer.recordOf(row.entity, row.clientRowId ?? row.rowKey) ?? buffer.recordOf(row.entity, row.rowKey);
    if (recordId) return result.idMap[recordId] ?? recordId;
    const parentKey = (this.model.region(row.entity) as { parentKey?: string } | undefined)?.parentKey;
    const value = parentKey ? row.values[parentKey] : null;
    return typeof value === 'string' ? value : '';
  }

  /**
   * 按命令结果提示：提交审批的单据、规则提示、跳过的修改。结果为 `unchanged` 时保存提示"没有需要保存的修改"，
   * 业务按钮按按钮名称说明没有变化（例如"由BOM生成明细：没有需要修改的数据"）。
   */
  private announce(result: CommandResult, savedText: string, unchangedText = '没有需要保存的修改') {
    const message = this.deps.message;
    if (result.outcome === 'unchanged') message.success(unchangedText);
    else if (result.outcome === 'approvalSubmitted') {
      const keys = result.approvals.map(a => a.document.recordKey).join('、');
      message.warning(`单据 ${keys} 已提交审批，审批结束前显示正式数据`);
      if (result.rows.some(r => !('deleted' in r) && !r.frozen)) message.success(savedText);
    } else message.success(savedText);
    for (const prompt of result.prompts) message.warning(prompt.message);
    if (result.skipped.length) message.warning(`${result.skipped.length} 行已被删除，修改已跳过`);
  }

  // ================================================================ 业务按钮（FP-14）

  /**
   * 业务按钮：命令只带选中行的主键（params.selectedRows），documents 为空数组；有没保存的修改也直接执行。
   * `requiresSelection` 为 false 的按钮（例如"同步采购价"）没有选中行也能点，selectedRows 为空数组。
   * 成功后结果中的行显示后端返回的值，这些行没保存的修改丢弃；其他行没保存的修改保留。按钮新增、删除的明细行
   * （例如"由BOM生成明细"）在明细区显示的单据中随之出现、去掉。失败时编辑缓冲不变。
   */
  async runOperation(region: ViewRegion, button: ViewButton): Promise<CommandResult | null> {
    const view = this.view.value;
    if (!view || !button.operation) return null;
    const selectedRows = this.selectedRows(region.entity)
      .filter(id => !this.model.buffer.isNew(region.entity, id))
      .map(rowKey => ({ entity: region.entity, rowKey }));
    const command: Command = {
      requestKey: crypto.randomUUID(),
      page: view.pageCode,
      operation: button.operation,
      documents: [],
      params: { selectedRows }
    };
    let result: CommandResult;
    try {
      result = await this.api.runCommand(command);
    } catch (error) {
      await this.failed(error);
      return null;
    }
    this.resultGeneration += 1;
    const discard: RowId[] = [];
    const updates = new Map<string, string[]>();
    const removes = new Map<string, string[]>();
    let detailsChanged = false;
    for (const row of result.rows) {
      discard.push({ entity: row.entity, id: row.rowKey });
      const gridId = this.model.gridId(row.rowKey);
      if ('deleted' in row) {
        this.model.removeRow(row.entity, row.rowKey);
        removes.set(row.entity, [...(removes.get(row.entity) ?? []), gridId]);
        detailsChanged = true;
        continue;
      }
      if (this.isNewDetail(row)) detailsChanged = true;
      // 按钮新增的明细行按关联字段归到所属单据（recordKeyOf）；它的 clientRowId 由后端生成，不用作表格标识
      this.model.applyResultRow({ ...row, clientRowId: null }, this.recordKeyOf(row, result));
      updates.set(row.entity, [...(updates.get(row.entity) ?? []), gridId]);
    }
    this.model.buffer.discard(discard);
    this.model.clearPreview(discard);
    await this.rereadResultRows(result);
    for (const approval of result.approvals) {
      if (approval.document.entity !== view.master.entity || approval.status !== 'pending') continue;
      this.model.freezeRecord(approval.document.recordKey, approval.approvalId);
      const ids = updates.get(view.master.entity) ?? [];
      updates.set(view.master.entity, [...ids, this.model.gridId(approval.document.recordKey)]);
    }
    for (const [entity, ids] of removes) this.port(entity)?.removeRows(ids);
    for (const [entity, ids] of updates) {
      const port = this.port(entity);
      if (port) port.updateRows(ids.filter(id => port.hasRow(id)));
    }
    if (detailsChanged) this.showDetails(this.state.activeRecord);
    this.syncState();
    // 按钮写入的单据按后端返回的值重新做显示求值（FP-18）
    void this.display(
      result.rows
        .filter((r): r is ResultRow => !('deleted' in r))
        .map(r => (r.entity === view.master.entity ? r.rowKey : this.recordKeyOf(r, result)))
    );
    this.announce(result, `${button.label}已完成`, `${button.label}：没有需要修改的数据`);
    await this.refreshAggregates();
    return result;
  }

  /**
   * 按钮成功后按主键重读结果中写到的行（rows/by-keys，每个实体一个请求，不在命令事务里），再显示：命令结果的行取自后端
   * 手里的数据（WP-12），只在读取视图中的字段（例如包材的参考采购价、最后采购数量，"客户指定"的 NVL）和数据库端的
   * 默认值到不了页面。同旧系统按钮执行后 reloadMasterRow + loadDetailData（useRuntimeActions.ts 第 75–110 行）。
   * 读失败时保留命令结果的值。
   */
  private async rereadResultRows(result: CommandResult) {
    const byEntity = new Map<string, string[]>();
    for (const row of result.rows) {
      if ('deleted' in row || row.frozen) continue;
      byEntity.set(row.entity, [...(byEntity.get(row.entity) ?? []), row.rowKey]);
    }
    for (const [entity, rowKeys] of byEntity) {
      try {
        // eslint-disable-next-line no-await-in-loop
        const response = await this.api.rowsByKeys(this.pageCode, { entity, rowKeys });
        this.model.registerRows(entity, response.rows);
      } catch {
        // 读失败：页面显示命令结果中的值
      }
    }
  }

  /** 按钮结果中前端还没有的明细行：按钮新增的行，例如"由BOM生成明细"按 BOM 新增的原辅料、包材 */
  private isNewDetail(row: ResultRow) {
    return row.entity !== this.model.master && !this.model.buffer.recordOf(row.entity, row.rowKey);
  }

  /** 明细区显示的单据有新增或删除的行时，按模型中的明细重新排列（新增的行排在后面） */
  private showDetails(recordId: string | null) {
    if (!recordId) return;
    for (const detail of this.view.value?.details ?? [])
      this.port(detail.entity)?.setRows(this.detailGridIds(detail.entity, recordId));
  }

  // ================================================================ 审批进度（FP-16）

  /** 弹出这些审批的进度（GET /api/approvals/{approvalId}）；有几个审批就分别列出 */
  async showApprovals(approvalIds: string[]) {
    this.ui.frozen.value = { loading: true, items: [], message: '' };
    const items: ApprovalDetail[] = [];
    for (const id of approvalIds) {
      try {
        items.push(await this.api.approvalDetail(id));
      } catch (error) {
        this.deps.message.error(`审批 ${id} 的进度读取失败：${messageOf(error)}`);
      }
    }
    if (this.ui.frozen.value) this.ui.frozen.value = { loading: false, items, message: '' };
  }

  closeApprovals() {
    this.ui.frozen.value = null;
  }

  // ================================================================ Lookup（FP-15）

  /** 打开 Lookup 对话框：先用空关键字查询 */
  async openLookup(entity: string, gridId: string, field: string) {
    const view = this.view.value;
    const meta = view && fieldOf(view, entity, field);
    const setting = meta?.lookup;
    if (!setting || !meta) return;
    const id = this.model.rowIdOf(gridId);
    if (fillsBack(setting) && !this.guard(entity, id)) return;
    const editable = !this.state.saving && this.model.cellEditable(entity, id, field);
    if (!canOpenLookup(setting, editable)) return;
    this.ui.lookup.value = {
      entity,
      id,
      field,
      title: meta.label,
      fillBack: fillsBack(setting),
      multiple: Boolean(setting.multiple),
      keyword: '',
      keywordSearch: true,
      rows: [],
      total: 0,
      loading: false,
      error: ''
    };
    await this.searchLookup('');
  }

  async searchLookup(keyword: string) {
    const lookup = this.ui.lookup.value;
    const view = this.view.value;
    if (!lookup || !view) return;
    const setting = fieldOf(view, lookup.entity, lookup.field)!.lookup!;
    const row = this.model.values(lookup.entity, lookup.id);
    const loading = { ...lookup, keyword, loading: true, error: '' };
    this.ui.lookup.value = loading;
    try {
      const response = await this.api.lookupSearch(
        setting.code,
        lookupRequest(setting, keyword.trim(), row, row[lookup.field] ?? null)
      );
      if (this.ui.lookup.value !== loading) return;
      this.ui.lookup.value = {
        ...loading,
        loading: false,
        rows: response.rows.map(r => r.values),
        total: response.total,
        keywordSearch: response.keywordSearch
      };
    } catch (error) {
      if (this.ui.lookup.value === loading)
        this.ui.lookup.value = { ...loading, loading: false, error: messageOf(error) };
    }
  }

  /** 选定 Lookup 的行：按回填映射写入本行（一个撤销步骤）；只查看的 Lookup 不回填 */
  confirmLookup(selected: FieldValues[]) {
    const lookup = this.ui.lookup.value;
    const view = this.view.value;
    this.ui.lookup.value = null;
    if (!lookup || !view || !lookup.fillBack || !selected.length) return;
    const setting = fieldOf(view, lookup.entity, lookup.field)!.lookup!;
    this.model.buffer.setValues(lookup.entity, lookup.id, lookupFill(setting, selected));
    this.changed([{ entity: lookup.entity, id: lookup.id }]);
  }

  closeLookup() {
    this.ui.lookup.value = null;
  }

  // ================================================================ 复制（FP-13）

  async openCopy(entity: string) {
    const view = this.view.value;
    if (!view) return;
    const selected = this.selectedRows(entity);
    if (entity === view.master.entity) {
      const sourceId = selected[0];
      if (!sourceId) return;
      // 源单据的明细还没加载时，先按单据加载接口读取
      if (view.details.length) await this.ensureRecord(sourceId);
      this.ui.copy.value = {
        entity,
        recordId: sourceId,
        rows: [],
        selection: defaultMasterSelection(this.model, sourceId)
      };
      return;
    }
    const recordId = this.state.activeRecord;
    if (!recordId || !selected.length || !this.guard(view.master.entity, recordId)) return;
    const region = this.model.region(entity)!;
    this.ui.copy.value = {
      entity,
      recordId,
      rows: selected,
      selection: { fields: region.fields.filter(f => f.visible).map(f => f.name) }
    };
  }

  /** 按对话框中的勾选复制；明细区复制时 `rows` 为勾选的行 */
  async confirmCopy(selection: CopySelection, rows?: string[]) {
    const copy = this.ui.copy.value;
    const view = this.view.value;
    this.ui.copy.value = null;
    if (!copy || !view) return;
    if (copy.entity === view.master.entity) {
      const newId = copyMaster(this.model, copy.recordId, selection);
      const anchor = this.model.gridId(copy.recordId);
      this.port(copy.entity)?.insertRows([{ id: newId, after: anchor }]);
      this.port(copy.entity)?.select(newId);
      const added = view.details.flatMap(d =>
        this.model.detailIds(d.entity, newId).map(id => ({ entity: d.entity, id }))
      );
      this.changed([{ entity: copy.entity, id: newId }, ...added]);
      if (view.details.length) await this.activate(newId);
      return;
    }
    const created = copyDetailRows(this.model, copy.entity, copy.recordId, rows ?? copy.rows, selection.fields);
    const order = this.model.detailIds(copy.entity, copy.recordId);
    const port = this.port(copy.entity);
    port?.insertRows(
      created.map(id => {
        const index = order.indexOf(id);
        return { id, after: index > 0 ? this.model.gridId(order[index - 1]) : null };
      })
    );
    this.changed(created.map(id => ({ entity: copy.entity, id })));
  }

  closeCopy() {
    this.ui.copy.value = null;
  }

  // ================================================================ 个人列配置（FP-11）

  /** 保存列配置：只提交改变的部分（与旧系统一样，一次保存本页全部表格） */
  async saveGridConfig() {
    const view = this.view.value;
    if (!view) return;
    const current: Record<string, PersonalColumn[]> = {};
    for (const [entity, port] of this.ports) current[regionKey(view, entity)] = port.columnState();
    const changes = personalChanges(view, this.personal, current, this.state.detailMode);
    if (!changes) {
      this.deps.message.success('列配置没有改变');
      return;
    }
    try {
      await this.api.savePersonal(this.pageCode, changes);
      this.personal = mergePersonal(this.personal, changes);
      this.deps.message.success('列配置已保存');
    } catch (error) {
      this.deps.message.error(`保存列配置失败：${messageOf(error)}`);
    }
  }

  /** 切换明细显示方式（Tab 或堆叠），存进个人配置 */
  async setDetailMode(mode: 'tabs' | 'stack') {
    if (this.state.detailMode === mode) return;
    this.state.detailMode = mode;
    try {
      await this.api.savePersonal(this.pageCode, { detailMode: mode });
      this.personal = mergePersonal(this.personal, { detailMode: mode });
    } catch (error) {
      this.deps.message.error(`保存明细显示方式失败：${messageOf(error)}`);
    }
  }

  // ================================================================ 高级查询

  applyAdvanced(query: AdvancedQuery | null) {
    this.ui.advanced.value = query;
    this.port(this.model.master)?.reload(true);
  }

  // ================================================================ 原地表单（FP-03）

  openForm(gridId: string) {
    const id = this.model.rowIdOf(gridId);
    this.state.formRecord = id;
    this.port(this.model.master)?.select(gridId);
  }

  closeForm() {
    this.state.formRecord = null;
  }

  /** 表单头部的上一条、下一条：按主表表格的显示顺序 */
  stepForm(offset: -1 | 1) {
    const current = this.state.formRecord;
    if (!current) return;
    const next = this.port(this.model.master)?.neighbor(this.model.gridId(current), offset);
    if (next) this.openForm(next);
  }

  /** 表单中改了一个字段（与表格共用编辑缓冲和撤销历史） */
  editForm(field: string, value: FieldValue) {
    const id = this.state.formRecord;
    if (!id) return false;
    return this.edit(this.model.master, this.model.gridId(id), field, value);
  }
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export { MASTER_GRID };
