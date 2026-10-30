<script setup lang="ts">
/**
 * grid-adapter：一个区域（主表区或某个明细）的 AG Grid，实现页面运行时的 GridPort。
 * 主表用服务端行模型，明细用客户端行模型（FP-02）；关闭 AG Grid 自带的撤销（FP-04，撤销由编辑缓冲负责）。
 * 只给各行模型传它支持的参数：`cacheBlockSize` 只给主表（服务端行模型），`groupDefaultExpanded` 只给明细（客户端行模型），
 * 否则 AG Grid 在控制台警告"… is not supported with the '…' row model"。
 * 列虚拟化只在测试模式下关掉（`suppressColumnVirtualisation`，见 columns.ts；用户 2026-10-30 同意），正式模式不变。
 */
import { computed, onBeforeUnmount, shallowRef } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type {
  CellDoubleClickedEvent,
  ColDef,
  DefaultMenuItem,
  GetContextMenuItemsParams,
  GetRowIdParams,
  GridApi,
  GridReadyEvent,
  IRowNode,
  IServerSideDatasource,
  MenuItemDef,
  RowClassParams,
  RowSelectionOptions,
  SideBarDef
} from 'ag-grid-community';
import type { JsonValue } from '../../../contracts/schema';
import type { PersonalColumn } from '../../../contracts/http';
import { EXPORT_MENU } from '../export';
import { fieldOf } from '../fields';
import type { GridPort, GridRow, PageRuntime } from '../page-runtime';
import { messageOf } from '../page-runtime';
import { SUMMARY_ROW_ID } from '../summary';
import { FORM_COLUMN, buildColumns, suppressColumnVirtualisation } from './columns';

defineOptions({ name: 'PageGrid' });

const props = defineProps<{
  runtime: PageRuntime;
  entity: string;
  /** 主表：服务端行模型，并带原地表单的展开列 */
  master: boolean;
}>();

const api = shallowRef<GridApi<GridRow> | null>(null);
const runtime = props.runtime;

const region = computed(() => {
  // 配置原地替换（viewVersion）后重新取区域
  void runtime.state.viewVersion;
  return runtime.view.value ? runtime.model.region(props.entity) : undefined;
});

const columnDefs = computed<ColDef<GridRow>[]>(() => {
  void runtime.state.dictVersion;
  const current = region.value;
  if (!current) return [];
  const columns = buildColumns(runtime, current, props.master);
  if (!props.master) {
    const groupBy = new Set(current.grid.groupBy);
    for (const column of columns) if (column.colId && groupBy.has(column.colId)) column.rowGroup = true;
  }
  return columns;
});

const sideBar = computed<SideBarDef | false>(() =>
  region.value?.grid.sideBar ? { toolPanels: ['columns'], hiddenByDefault: false, defaultToolPanel: '' } : false
);

const cellSelection = computed(() => Boolean(region.value?.grid.cellSelection));

/** 汇总行（C06 第 3 节 `aggregate`）：固定在表格底部；编辑、预览、加载明细、换单据和重新查询后重算 */
const pinnedBottom = computed(() => {
  void runtime.state.revision;
  void runtime.state.viewVersion;
  void runtime.state.activeRecord;
  void runtime.ui.aggregates.value;
  const row = runtime.summaryRow(props.entity);
  return row ? [row] : [];
});

const rowSelection: RowSelectionOptions = {
  mode: 'multiRow',
  checkboxes: false,
  headerCheckbox: false,
  enableClickSelection: true
};

const defaultColDef: ColDef<GridRow> = { minWidth: 70 };

function getRowId(params: GetRowIdParams<GridRow>) {
  return params.data.__id;
}

const rowClassRules = {
  'row-deleted': (params: RowClassParams<GridRow>) =>
    Boolean(params.data && runtime.model.buffer.isDeleted(props.entity, runtime.model.rowIdOf(params.data.__id))),
  'row-new': (params: RowClassParams<GridRow>) =>
    Boolean(params.data && runtime.model.buffer.isNew(props.entity, runtime.model.rowIdOf(params.data.__id))),
  'row-frozen': (params: RowClassParams<GridRow>) =>
    Boolean(params.data && runtime.frozenBy(props.entity, params.data.__id))
};

function getRowStyle(params: RowClassParams<GridRow>) {
  if (!params.data) return undefined;
  // 界面规则的行样式：有修改时取预览，否则取页面加载时的显示求值（旧系统 GRID_STYLE 加载即显示）
  const style = runtime.model.ruleView(props.entity, runtime.model.rowIdOf(params.data.__id))?.style.row;
  return style && typeof style === 'object' && !Array.isArray(style) ? (style as Record<string, string>) : undefined;
}

const datasource: IServerSideDatasource<GridRow> = {
  getRows(params) {
    const request = params.request;
    runtime
      .fetchMasterRows({
        startRow: request.startRow ?? 0,
        endRow: request.endRow ?? 100,
        sortModel: request.sortModel.map(s => ({ colId: s.colId, sort: s.sort })),
        filterModel: (request.filterModel ?? {}) as Record<string, Record<string, JsonValue>>
      })
      .then(result => params.success({ rowData: result.rows, rowCount: result.total }))
      .catch(error => {
        runtime.state.error = messageOf(error);
        params.fail();
      });
  }
};

function node(id: string): IRowNode<GridRow> | undefined {
  return api.value?.getRowNode(id) ?? undefined;
}

function rows(ids: string[]) {
  return ids.map(id => runtime.gridRow(props.entity, id));
}

function indexAfter(after: string | null) {
  if (after === null) return 0;
  const found = node(after)?.rowIndex;
  return found === null || found === undefined ? undefined : found + 1;
}

/**
 * 逐行更新（FP-06、FP-08）：主表 applyServerSideTransaction，明细 applyTransaction，只换这些行的数据，不重建表格。
 * 编辑时 runtime 在 valueSetter 中触发更新，这里推迟到 AG Grid 结束本次编辑之后再执行，同一轮中的多行合成一次。
 */
const pendingUpdates = new Set<string>();
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function flushUpdates() {
  flushTimer = null;
  const grid = api.value;
  const ids = [...pendingUpdates].filter(id => node(id));
  pendingUpdates.clear();
  if (!grid || !ids.length) return;
  const update = rows(ids);
  if (props.master) grid.applyServerSideTransaction({ route: [], update });
  else grid.applyTransaction({ update });
  const nodes = ids.map(node).filter((n): n is IRowNode<GridRow> => Boolean(n));
  grid.refreshCells({ rowNodes: nodes, force: true });
}

const port: GridPort = {
  updateRows(ids) {
    for (const id of ids) pendingUpdates.add(id);
    flushTimer ??= setTimeout(flushUpdates, 0);
  },
  insertRows(added) {
    const grid = api.value;
    if (!grid) return;
    for (const row of added) {
      const addIndex = indexAfter(row.after);
      const data = runtime.gridRow(props.entity, row.id);
      if (props.master) grid.applyServerSideTransaction({ route: [], add: [data], addIndex });
      else grid.applyTransaction({ add: [data], addIndex });
    }
  },
  removeRows(ids) {
    const grid = api.value;
    if (!grid || !ids.length) return;
    const remove = ids.map(id => ({ __id: id }) as GridRow);
    if (props.master) grid.applyServerSideTransaction({ route: [], remove });
    else grid.applyTransaction({ remove });
  },
  hasRow(id) {
    return Boolean(node(id));
  },
  setRows(ids) {
    api.value?.setGridOption('rowData', rows(ids));
  },
  reload(purge = false) {
    api.value?.refreshServerSide({ purge });
  },
  selectedIds() {
    return (api.value?.getSelectedRows() ?? []).map(row => row.__id);
  },
  select(id) {
    const target = node(id);
    if (!target) return;
    target.setSelected(true, true);
    api.value?.ensureNodeVisible(target);
  },
  refreshAll() {
    api.value?.refreshCells({ force: true });
    api.value?.redrawRows();
  },
  columnState() {
    const grid = api.value;
    const current = region.value;
    if (!grid || !current) return [];
    const visible = new Set(current.fields.filter(f => f.visible).map(f => f.name));
    return grid
      .getColumnState()
      .filter(state => state.colId !== FORM_COLUMN && visible.has(state.colId))
      .map(
        (state): PersonalColumn => ({
          field: state.colId,
          width: state.width ?? null,
          pinned: state.pinned === 'left' || state.pinned === 'right' ? state.pinned : null,
          hide: Boolean(state.hide)
        })
      );
  },
  applyColumnState(columns) {
    api.value?.applyColumnState({
      state: columns.map(c => ({ colId: c.field, width: c.width ?? undefined, pinned: c.pinned, hide: c.hide })),
      applyOrder: true
    });
  },
  orderColumns(ids) {
    // 只给 colId：列宽、固定、显隐不变；不在 ids 中的列（表单展开列等）按原来的先后排在后面，锁定在左边的仍在左边
    api.value?.applyColumnState({ state: ids.map(colId => ({ colId })), applyOrder: true });
  },
  stopEditing() {
    api.value?.stopEditing();
  },
  neighbor(id, offset) {
    const grid = api.value;
    const index = node(id)?.rowIndex;
    if (!grid || index === null || index === undefined) return null;
    return grid.getDisplayedRowAtIndex(index + offset)?.data?.__id ?? null;
  }
};

function onGridReady(event: GridReadyEvent<GridRow>) {
  api.value = event.api;
  runtime.attach(props.entity, port);
}

onBeforeUnmount(() => {
  if (flushTimer) clearTimeout(flushTimer);
  runtime.detach(props.entity, port);
});

function onSelectionChanged() {
  runtime.onSelection(props.entity, port.selectedIds());
}

/** 表格换上了新的列（初次建表、配置变更、字典加载后）：配置变更后由运行时按页面视图重排（FP-09） */
function onNewColumnsLoaded() {
  runtime.columnsLoaded(props.entity);
}

/** FP-16：被冻结的单据双击不进入编辑，弹出审批进度；Lookup 字段双击打开 Lookup 对话框（FP-15） */
function onCellDoubleClicked(event: CellDoubleClickedEvent<GridRow>) {
  const field = event.colDef.field;
  const data = event.data;
  if (!field || !data || data.__id === SUMMARY_ROW_ID || !runtime.view.value) return;
  const meta = fieldOf(runtime.view.value, props.entity, field);
  if (meta?.lookup) {
    void runtime.openLookup(props.entity, data.__id, field);
    return;
  }
  runtime.guard(props.entity, runtime.model.rowIdOf(data.__id));
}

/** 粘贴：一次粘贴是一个撤销步骤；粘贴到被冻结的单据时弹出审批进度 */
function onPasteStart() {
  const grid = api.value;
  const cell = grid?.getFocusedCell();
  const data = cell && grid?.getDisplayedRowAtIndex(cell.rowIndex)?.data;
  if (data) runtime.guard(props.entity, runtime.model.rowIdOf(data.__id));
  runtime.beginBatch();
}

function onPasteEnd() {
  runtime.endBatch();
}

/**
 * 右键菜单：与工具栏相同的区域按钮（FP-14）；右键的行先被选中。
 * 主表在这些按钮之后加分隔线和"自定义导出"子菜单（FP-19，旧系统 useGridContextMenu.ts 第 390–406 行）；
 * 没有可用的导出配置时不加，明细不加。
 */
function getContextMenuItems(params: GetContextMenuItemsParams<GridRow>): Array<MenuItemDef | DefaultMenuItem> {
  const current = region.value;
  if (!current) return [];
  if (params.node?.data && !params.node.isSelected() && params.node.data.__id !== SUMMARY_ROW_ID)
    params.node.setSelected(true, true);
  const items: Array<MenuItemDef | DefaultMenuItem> = runtime.regionButtons(current).map(button => ({
    name: button.label,
    disabled: !runtime.buttonEnabled(current, button),
    action: () => void runtime.clickButton(current, button)
  }));
  const exports = props.master ? runtime.exportMenu() : [];
  if (exports.length) {
    if (items.length) items.push('separator');
    items.push({
      name: EXPORT_MENU,
      subMenu: exports.map(item => ({
        name: item.label,
        action: () => void runtime.exportFile(item.exportCode, item.scope)
      }))
    });
  }
  return items;
}
</script>

<template>
  <AgGridVue
    class="page-grid h-full"
    :column-defs="columnDefs"
    :default-col-def="defaultColDef"
    :get-row-id="getRowId"
    :row-model-type="master ? 'serverSide' : 'clientSide'"
    :server-side-datasource="master ? datasource : undefined"
    :cache-block-size="master ? 100 : undefined"
    :row-selection="rowSelection"
    :row-class-rules="rowClassRules"
    :get-row-style="getRowStyle"
    :pinned-bottom-row-data="pinnedBottom"
    :side-bar="sideBar"
    :cell-selection="cellSelection"
    :maintain-column-order="true"
    :undo-redo-cell-editing="false"
    :stop-editing-when-cells-lose-focus="true"
    :tooltip-show-delay="300"
    :get-context-menu-items="getContextMenuItems"
    :group-default-expanded="master ? undefined : -1"
    :suppress-column-virtualisation="suppressColumnVirtualisation"
    @grid-ready="onGridReady"
    @selection-changed="onSelectionChanged"
    @new-columns-loaded="onNewColumnsLoaded"
    @cell-double-clicked="onCellDoubleClicked"
    @paste-start="onPasteStart"
    @paste-end="onPasteEnd"
  />
</template>

<style scoped>
:deep(.cell-user-changed) {
  background-color: #b7f4b3 !important;
  color: #1a1a1a !important;
}

:deep(.cell-calc-changed) {
  background-color: #fff2a8 !important;
  color: #1a1a1a !important;
}

:deep(.cell-new) {
  background-color: #0b3d91 !important;
  color: #ffffff;
}

:deep(.cell-deleted) {
  background-color: #f8d7da !important;
  text-decoration: line-through;
}

:deep(.cell-error) {
  box-shadow: inset 0 0 0 2px #d03050;
}

:deep(.row-deleted) {
  opacity: 0.5;
}

:deep(.row-new) {
  font-style: italic;
}

:deep(.row-frozen) {
  color: #8a8a8a;
}

:deep(.cell-lookup) {
  cursor: pointer;
}

:deep(.page-form-toggle) {
  padding: 0 !important;
  display: flex;
  align-items: center;
  justify-content: center;
}

:deep(.page-form-toggle__button) {
  border: none;
  background: transparent;
  color: #646cff;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}

:deep(.ag-header-cell-label) {
  white-space: normal !important;
  line-height: 1.2;
}
</style>
