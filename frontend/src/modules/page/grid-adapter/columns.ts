/**
 * grid-adapter：按页面视图生成 AG Grid 的列定义。本目录是 frontend-page 中唯一引用 AG Grid 的部分。
 *
 * - 只生成可见字段的列（FP-10）：不可见的字段不在列和列工具面板中，数据仍在行里。
 * - 列宽、固定用 initialWidth、initialPinned：查询和配置替换后不重置用户调整过的列（FP-08、FP-09）。
 * - 可编辑、样式、标记都用回调，每次从页面运行时取最新状态（配置替换和预览后立即生效）。
 * - 改动标记沿用旧系统（MasterDetailPageV3.vue）：改过的格绿色、计算带出变化的格黄色、新增行深蓝底白字、删除行半透明加删除线；
 *   判断和样式与原地表单共用（marks.ts、marks.css）。对比、错误提示、界面规则的单元格样式也与原地表单共用（marks.ts）。
 * - 主表区和每个明细区的每行最前面都有原地表单的展开列（FP-03）。
 */
import type {
  CellClassParams,
  ColDef,
  EditableCallbackParams,
  ValueFormatterParams,
  ValueSetterParams
} from 'ag-grid-community';
import type { FieldValue } from '../../../contracts/command';
import type { ViewField, ViewRegion } from '../../../contracts/page-view';
import { displayText, optionValues, parseInput } from '../fields';
import { CELL_MARKS, cellCompare, cellTooltip, ruleCellStyle } from '../marks';
import type { GridRow, PageRuntime } from '../page-runtime';

export const FORM_COLUMN = '__form';

/** 可填写的字典下拉编辑器（DictSelectCellEditor.vue）在表格 `components` 中的名字，由 PageGrid 注册 */
export const DICT_FREE_TEXT_EDITOR = 'dictSelectCellEditor';

/**
 * 测试模式专用：只在 `vite --mode test`（`pnpm dev`、`pnpm build:test`，端到端测试的开发方式和回归方式都用它）下
 * 关掉 AG Grid 的列虚拟化，主表和明细（以及 Lookup 结果）一次渲染全部列，端到端用例按 col-id 直接取格子，不用横向逐段滚动。
 * 来源：用户 2026-10-30 同意"只在 vite --mode test 下关掉列虚拟化"。正式模式（`pnpm build`，`--mode prod`）不变，
 * 仍只渲染视野内的列。AG Grid 只在建表时读这个选项。
 */
export const suppressColumnVirtualisation = import.meta.env.MODE === 'test';

function idOf(params: { data?: GridRow | undefined }) {
  return params.data?.__id ?? '';
}

/**
 * 对比显示：值后面跟箭头和差值（与旧系统 renderCompareValue 相同的样式）。显示什么由 marks.ts 的 cellCompare 决定，
 * 原地表单的字段用同一个（样式名都是 cell-compare）。
 */
function compareRenderer(runtime: PageRuntime, region: ViewRegion, field: ViewField, dict?: Map<string, string>) {
  return (params: { value: FieldValue; data?: GridRow }) => {
    const span = document.createElement('span');
    span.textContent = displayText(field, params.value ?? null, dict);
    const id = params.data ? runtime.model.rowIdOf(params.data.__id) : '';
    const shown = cellCompare(runtime.model, { region, id, field: field.name });
    if (!shown) return span;
    const wrapper = document.createElement('span');
    const diff = document.createElement('span');
    diff.className = 'cell-compare';
    diff.style.cssText = `color:${shown.color};font-size:11px;margin-left:4px`;
    diff.textContent = `${shown.arrow}${shown.text}`;
    wrapper.append(span, diff);
    return wrapper;
  };
}

/** 空单元格（汇总行中不求和的布尔列） */
const emptyCell = () => '';

function filterOf(field: ViewField): ColDef['filter'] {
  if (field.type === 'number') return 'agNumberColumnFilter';
  if (field.type === 'date' || field.type === 'datetime') return 'agDateColumnFilter';
  if (field.type === 'boolean') return false;
  return 'agTextColumnFilter';
}

export function buildColumns(runtime: PageRuntime, region: ViewRegion): ColDef<GridRow>[] {
  const entity = region.entity;
  const columns: ColDef<GridRow>[] = [];
  // FP-03：主表区和每个明细区的每行最前面固定一列展开图标，点击后在这个区域原地显示这一行的表单
  columns.push({
    colId: FORM_COLUMN,
    headerName: '',
    pinned: 'left',
    lockPosition: 'left',
    lockPinned: true,
    width: 36,
    resizable: false,
    sortable: false,
    filter: false,
    suppressHeaderMenuButton: true,
    suppressColumnsToolPanel: true,
    suppressNavigable: true,
    cellClass: 'page-form-toggle',
    cellRenderer: (params: { data?: GridRow; node?: { rowPinned?: unknown } }) => {
      // 汇总行没有表单
      if (params.node?.rowPinned) return '';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'page-form-toggle__button';
      button.title = '在表单中查看';
      button.textContent = '⊞';
      button.addEventListener('click', event => {
        event.stopPropagation();
        if (params.data) runtime.openForm(entity, params.data.__id);
      });
      return button;
    }
  });
  for (const field of region.fields) {
    if (!field.visible) continue;
    const dict = field.dictType ? runtime.dicts.get(field.dictType) : undefined;
    const options = optionValues(field);
    const column: ColDef<GridRow> = {
      colId: field.name,
      field: field.name,
      headerName: field.label,
      initialWidth: field.width ?? undefined,
      initialPinned: field.pinned ?? undefined,
      sortable: true,
      resizable: true,
      filter: filterOf(field),
      editable: (params: EditableCallbackParams<GridRow>) => runtime.cellEditable(entity, idOf(params), field.name),
      valueSetter: (params: ValueSetterParams<GridRow>) => {
        const value = parseInput(field, params.newValue);
        if (value === undefined || !params.data) return false;
        if (!runtime.edit(entity, params.data.__id, field.name, value)) return false;
        params.data[field.name] = value;
        return true;
      },
      valueFormatter: (params: ValueFormatterParams<GridRow>) =>
        displayText(field, (params.value as FieldValue) ?? null, dict),
      // 错误提示、单元格样式与原地表单的字段同一组判断（marks.ts）
      tooltipValueGetter: params =>
        cellTooltip(runtime.model, {
          region,
          id: runtime.model.rowIdOf(idOf(params as { data?: GridRow })),
          field: field.name
        }),
      cellClassRules: {
        // 改动标记和错误标记与原地表单的字段同一组判断（marks.ts）
        ...Object.fromEntries(
          Object.entries(CELL_MARKS).map(([name, test]) => [
            name,
            (params: CellClassParams<GridRow>) =>
              test(runtime.model, { region, id: runtime.model.rowIdOf(idOf(params)), field: field.name })
          ])
        ),
        'cell-lookup': () => Boolean(field.lookup)
      },
      cellStyle: params =>
        ruleCellStyle(runtime.model, {
          region,
          id: runtime.model.rowIdOf(idOf(params as { data?: GridRow })),
          field: field.name
        })
    };
    if (field.type === 'number') {
      column.type = 'rightAligned';
      column.cellDataType = false;
    } else if (field.type === 'boolean') {
      // 复选框：勾选即修改（C01：JSON 中为 true/false）
      column.cellDataType = 'boolean';
      column.valueFormatter = undefined;
      // 底部汇总行（FP-17）不求和布尔列：不画复选框，留空；其他行用 AG Grid 的复选框
      column.cellRendererSelector = params => (params.node.rowPinned ? { component: emptyCell } : undefined);
    } else if (field.type === 'date') {
      column.cellDataType = 'dateString';
    } else {
      column.cellDataType = false;
    }
    if (dict && field.dictFreeText) {
      // C05 dictFreeText：字典下拉中还可以填写字典以外的值（旧系统"下拉（可填写）"，TagSelectCellEditor.vue）
      column.cellEditor = DICT_FREE_TEXT_EDITOR;
      column.cellEditorPopup = true;
      column.cellEditorPopupPosition = 'under';
      column.cellEditorParams = { options: [...dict].map(([value, label]) => ({ value, label })) };
    } else if (dict) {
      column.cellEditor = 'agSelectCellEditor';
      column.cellEditorParams = {
        values: ['', ...dict.keys()],
        formatValue: (v: string) => (v ? (dict.get(v) ?? v) : '')
      };
    } else if (options) {
      column.cellEditor = 'agSelectCellEditor';
      column.cellEditorParams = { values: options };
    }
    // 行中可能带对比值（C09 DataRow.compare），文本列和数值列都用同一个渲染器
    if (field.type !== 'boolean') column.cellRenderer = compareRenderer(runtime, region, field, dict);
    columns.push(column);
  }
  return columns;
}
