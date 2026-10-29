/**
 * 审批流配置各表格的列（FC-05 定稿）：
 * - 流程列表：流程名称、所属页面（只读）、审核操作、启用、顺序；
 * - 审批节点：级别、节点名称、条件类型、入口条件、发起部门限制、人员 / 角色 / SQL、同级方式、启用；
 * - 冻结节点：启用、冻结表、关联条件；
 * - 展示数据：块编码（C06 7.5 的 `key`）、展示标题、展示区域、展示表 / 视图、关联条件、修改的表、主键列、显示列、勾选方式、
 *   审批通过后的操作。
 */
import type { ColDef, ICellEditorParams } from 'ag-grid-community';
import type { Option, PageTable } from '../core/catalog';
import {
  booleanColumn,
  conditionOptions,
  linkColumn,
  modeOptions,
  regionOptions,
  selectColumn,
  selectionOptions
} from '../components/grid-columns';
import {
  type DisplayRow,
  type FlowDraft,
  type NodeRow,
  actionsSummary,
  approverSummary,
  columnsSummary,
  conditionSummary,
  operationsSummary
} from './flow-model';

export function flowColumns(tables: PageTable[], pageTitle: string): ColDef<FlowDraft>[] {
  return [
    { field: 'name', headerName: '流程名称', width: 200 },
    { colId: 'page', headerName: '所属页面', width: 125, editable: false, valueGetter: () => pageTitle },
    { ...linkColumn('operations', '审核操作', 300, (d: FlowDraft) => operationsSummary(d.operations, tables) || '双击选择审核操作'), flex: 1 },
    booleanColumn('enabled'),
    { field: 'order', headerName: '顺序', width: 82, cellDataType: 'number', cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 0, precision: 0, step: 1 } }
  ] as ColDef<FlowDraft>[];
}

export function nodeColumns(departments: Option[], roles: Option[], users: Option[]): ColDef<NodeRow>[] {
  return [
    { field: 'level', headerName: '级别', width: 75, cellDataType: 'number', cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 1, max: 99, precision: 0, step: 1 } },
    { field: 'name', headerName: '节点名称', width: 150 },
    selectColumn('conditionType', '条件类型', conditionOptions, 105),
    linkColumn('condition', '入口条件', 300, (d: NodeRow) => conditionSummary(d)),
    selectColumn('department', '发起部门限制', [{ label: '不限', value: null }, ...departments], 130),
    linkColumn('approvers', '人员 / 角色 / SQL', 200, (d: NodeRow) => approverSummary(d.approvers, roles, users)),
    selectColumn('mode', '同级方式', modeOptions, 130),
    booleanColumn('enabled')
  ] as ColDef<NodeRow>[];
}

export function freezeColumns(): ColDef[] {
  return [
    booleanColumn('enabled'),
    { field: 'table', headerName: '冻结表（直接写表名，只能是表）', width: 260 },
    { ...linkColumn('condition', '关联条件（只写条件，查到的行冻结）', 400, (d: { condition: string }) => d.condition || '双击配置关联条件'), flex: 1 }
  ];
}

/** `sourceColumns(name)` 返回已读到的表或视图的列；还没读到时为 null，主键列先按文本编辑 */
export function displayColumns(tables: PageTable[], sourceColumns: (name: string) => string[] | null): ColDef<DisplayRow>[] {
  const tableOptions = tables.map(t => ({ label: `${t.title}（${t.entity}）`, value: t.entity }));
  const affected = (p: { data?: DisplayRow }) => p.data?.region === 'affected';
  return [
    { field: 'key', headerName: '块编码', width: 110 },
    { field: 'title', headerName: '展示标题', width: 150 },
    selectColumn('region', '展示区域', regionOptions, 140),
    {
      field: 'source',
      headerName: '展示表 / 视图',
      width: 200,
      valueFormatter: p => tableOptions.find(o => o.value === p.value)?.label ?? String(p.value ?? ''),
      cellEditorSelector: (p: ICellEditorParams<DisplayRow>) => {
        if (p.data?.region === 'affected') return { component: 'agTextCellEditor' };
        const allowed = tables.filter(t => (p.data?.region === 'master' ? t.isMaster : !t.isMaster)).map(t => t.entity);
        return { component: 'agSelectCellEditor', params: { values: allowed } };
      }
    },
    linkColumn('condition', '关联条件', 200, (d: DisplayRow) => d.condition || (d.region === 'affected' ? '双击配置关联条件' : '（本次保存的单据和修改的行）')),
    { field: 'targetTable', headerName: '修改的表', width: 150, editable: affected },
    {
      field: 'keyColumn',
      headerName: '主键列',
      width: 120,
      editable: affected,
      cellEditorSelector: (p: ICellEditorParams<DisplayRow>) => {
        const columns = p.data ? sourceColumns(p.data.source) : null;
        return columns?.length ? { component: 'agSelectCellEditor', params: { values: ['', ...columns] } } : { component: 'agTextCellEditor' };
      }
    },
    linkColumn('columns', '显示列', 220, (d: DisplayRow) => columnsSummary(d.columns)),
    {
      ...selectColumn('selection', '勾选方式', selectionOptions, 150),
      editable: affected,
      // 下拉列表中的选项格式化时没有行数据（AG Grid 的 formatValue 不带行），也要显示选项名称；只有主表、明细块的格子显示"—"
      valueFormatter: p => (p.data && p.data.region !== 'affected' ? '—' : selectionOptions.find(o => o.value === p.value)?.label ?? '')
    },
    { ...linkColumn('actions', '审批通过后的操作', 220, (d: DisplayRow) => (d.region === 'affected' ? actionsSummary(d.actions) : '应用本次修改')), flex: 1 }
  ] as ColDef<DisplayRow>[];
}
