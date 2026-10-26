<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { NAlert, NButton, NCheckbox, NCheckboxGroup, NEmpty, NModal, NPopconfirm, NSelect, NSpace, NTabPane, NTabs, useMessage } from 'naive-ui';
import type { CellDoubleClickedEvent, CellValueChangedEvent, ColDef, ICellEditorParams } from 'ag-grid-community';
import { approvalErrorMessage as configError } from '@/components/approval/approval-errors';
import {
  deleteApprovalDefinition, fetchApprovalCatalog, fetchApprovalDefinition, fetchApprovalDefinitions,
  saveApprovalDefinition, validateApprovalDefinition
} from '@/service/api/approval-config';
import type {
  ApprovalAction, ApprovalActionParam, ApprovalApprover, ApprovalCatalog, ApprovalDataItem, ApprovalDefinition,
  ApprovalEntry, ApprovalLock, ApprovalObjectSource, ApprovalValidation
} from '@/service/api/approval-config';
import ApprovalActionParamsEditor from './ApprovalActionParamsEditor.vue';
import ApprovalApproverEditor from './ApprovalApproverEditor.vue';
import ApprovalConditionEditor from './ApprovalConditionEditor.vue';
import ApprovalConfigGrid from './ApprovalConfigGrid.vue';
import { actionEventOptions, booleanColumn, conditionOptions, largeTextColumn, modeOptions, selectColumn } from './approval-config-columns';

const props = defineProps<{ pageCode: string }>();
type DetailTab = 'entries' | 'dataItems' | 'objects' | 'locks' | 'actions';
type FlowDraft = ApprovalDefinition & { _key: string; _dirty: boolean; _uncertain: boolean };
type ConditionTarget = ApprovalDefinition['trigger'] | ApprovalEntry;
const message = useMessage();
const flows = ref<FlowDraft[]>([]);
const catalog = ref<ApprovalCatalog>({ tables: [], users: [], roles: [], departments: [], actions: [], systemParams: [] });
const selectedKey = ref('');
const current = computed(() => flows.value.find(flow => flow._key === selectedKey.value));
const tab = ref<DetailTab>('entries');
const selectedDetails = ref<object[]>([]);
const loading = ref(false);
const busy = ref(false);
const ready = ref(false);
const readinessMessage = ref('');
const loadError = ref('');
const status = ref('选择流程后编辑明细，保存时整条流程一并发布。');
const validation = ref<ApprovalValidation | null>(null);
const masterGrid = ref<InstanceType<typeof ApprovalConfigGrid>>();
const detailGrid = ref<InstanceType<typeof ApprovalConfigGrid>>();
let loadSequence = 0;
let draftSequence = 0;

const showCondition = ref(false);
const conditionTarget = ref<ConditionTarget>();
const conditionTitle = ref('');
const showApprovers = ref(false);
const approverEntry = ref<ApprovalEntry>();
const showActionParams = ref(false);
const selectedAction = ref<ApprovalAction>();
const showFields = ref(false);
const selectedLock = ref<ApprovalLock>();
const lockFields = ref<string[]>([]);
const showOperations = ref(false);
const operations = ref<string[]>([]);

const tableOptions = computed(() => catalog.value.tables.map(table => ({
  label: `${table.tableName || table.tableCode} · ${table.tableCode}`, value: table.tableCode
})));
const objectTableOptions = computed(() => catalog.value.tables
  .filter(table => !table.parentTableCode && table.tableType?.toUpperCase() === 'MASTER')
  .map(table => ({ label: `${table.tableName || table.tableCode} · ${table.tableCode}`, value: table.tableCode })));
const relatedSourceOptions = computed(() => {
  const masterCode = current.value?.tableCode || '';
  const main = fieldOptions(masterCode, true).map(field => ({ ...field, label: `主表 · ${field.label}` }));
  const details = catalog.value.tables.filter(table => table.parentTableCode === masterCode)
    .flatMap(table => fieldOptions(table.tableCode, true).map(field => ({
      label: `本次明细 · ${table.tableName || table.tableCode} · ${field.label}`,
      value: `${table.tableCode}.${field.value}`
    })));
  return [...main, ...details];
});
const lockFieldOptions = computed(() => fieldOptions(selectedLock.value?.tableCode || current.value?.tableCode || ''));
const detailRows = computed<object[]>(() => current.value?.[tab.value] || []);
const detailHelp: Record<DetailTab, string> = {
  entries: '一行一个入口；同级方式统一。双击条件、审批人可编辑。首级全部不满足时正常保存；后续某级全部不满足时，以前一级的批准结束审批，不再判断更高级别。',
  dataItems: '只读 SQL 取数；具名参数可引用原值、待审值和当前人员。结果以数据项名称引用。',
  objects: '一行一个对象来源。SQL 返回目标主单；主键、标题、显示列均填写 SQL 返回列名。审批期间固定锁定目标主单及全部明细。',
  locks: '空字段范围表示全部业务字段；全部明细包含新增、删除和换主单。流程结束成功后释放本次锁定。',
  actions: '按行顺序执行；本级动作成功后再判断下一级。动作失败回滚本次审批，锁定继续保留。'
};
const operationNames: Record<string, string> = { modified: '修改', added: '新增', deleted: '删除' };

function fieldOptions(tableCode: string, physicalOnly = false) {
  return (catalog.value.tables.find(table => table.tableCode === tableCode)?.columns || [])
    .filter(column => !physicalOnly || !column.isVirtual)
    .map(column => ({ label: `${column.label || column.headerText || column.columnName} · ${column.columnName}`, value: column.columnName }));
}
function lockTableOptions(lock: ApprovalLock) {
  const masterCode = current.value?.tableCode;
  return tableOptions.value.filter(option => {
    if (lock.target === 'MASTER') return option.value === masterCode;
    if (lock.target === 'ALL_DETAILS' || lock.target === 'CHANGED_DETAILS') {
      return catalog.value.tables.find(table => table.tableCode === option.value)?.parentTableCode === masterCode;
    }
    return true;
  });
}
function approverSummary(entry: ApprovalEntry) {
  return entry.approvers.map(approver => {
    if (approver.type === 'SQL') return 'SQL 选人';
    if (approver.type === 'ROLE') {
      const role = catalog.value.roles.find(item => Number(item.id) === Number(approver.roleId));
      return role?.roleName || role?.roleCode || `角色 ${approver.roleId ?? '待选'}`;
    }
    const user = catalog.value.users.find(item => Number(item.id) === Number(approver.userId));
    return user?.realName || user?.username || `人员 ${approver.userId ?? '待选'}`;
  }).join('、') || '双击配置审批人';
}
function actionSummary(flow: ApprovalDefinition) {
  return flow.actions.filter(action => action.enabled && action.event === 'FLOW_APPROVED')
    .map(action => action.code === 'APPLY_PENDING_CHANGE' ? '应用待批变更' : action.procedure || '待选择过程').join('；') || '未配置';
}
function conditionSummary(target: ConditionTarget) {
  return target.conditionType === 'ALWAYS' ? '始终满足' : target.condition || '双击配置条件';
}
function linkColumn(field: string, headerName: string, width: number): ColDef {
  return { field, headerName, width, editable: false, cellClass: 'approval-link', tooltipField: field };
}

const masterColumns = computed<ColDef[]>(() => [
  { field: 'flowName', headerName: '流程名称', width: 180 },
  { field: 'pageCode', headerName: '关联页面', width: 125, editable: false },
  selectColumn('trigger.event', '触发时机', [{ label: '正常保存', value: 'SAVE' }, { label: '手工送审', value: 'MANUAL' }], 105),
  selectColumn('direction', '同步方向', [{ label: '不进行价格同步', value: 'NONE' }, { label: '成本单 → 货品', value: 'COST_TO_GOODS' }, { label: '货品 → 成本单', value: 'GOODS_TO_COST' }], 160),
  selectColumn('decisionMode', '审批方式', [{ label: '整单审批', value: 'WHOLE' }, { label: '勾选对象审批', value: 'SELECTED' }], 145),
  booleanColumn('enabled'),
  { colId: 'finalActions', headerName: '最终通过动作', width: 230, editable: false, valueGetter: params => params.data ? actionSummary(params.data) : '' },
  { ...linkColumn('trigger.operations', '保存操作', 135), valueGetter: params => params.data?.trigger.operations.map((operation: string) => operationNames[operation] || operation).join('、') },
  { ...linkColumn('trigger.condition', '送审条件', 230), valueGetter: params => params.data ? conditionSummary(params.data.trigger) : '' },
  { ...booleanColumn('trigger.requireApplicantForSubmit', '仅申请人送审'), width: 130 },
  { ...selectColumn('tableCode', '业务主表', tableOptions.value, 190), editable: false },
  { field: 'flowPriority', headerName: '优先级', width: 82, cellDataType: 'number', cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 0, precision: 0, step: 1 } },
  { field: 'flowVersion', headerName: '版本', width: 70, editable: false },
  { colId: 'unmatchedEntryBehavior', headerName: '入口不满足时', width: 200, editable: false, valueGetter: () => '首级正常保存；后续结束审批', tooltipValueGetter: () => '首级全部入口不满足时，跳过整个审批并正常保存；后续某级全部入口不满足时，以前一级的批准结束审批，不再判断更高级别。' },
  { colId: 'draftState', headerName: '配置状态', width: 100, editable: false, valueGetter: params => params.data?._uncertain ? '待回读核对' : params.data?._dirty ? '未保存' : '已读取' }
]);
const entryColumns = computed<ColDef[]>(() => [
  { field: 'level', headerName: '级别', width: 75, cellDataType: 'number', cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 1, max: 99, precision: 0, step: 1 } },
  { field: 'name', headerName: '入口名称', width: 160 },
  selectColumn('conditionType', '条件类型', conditionOptions, 115),
  { ...linkColumn('condition', '入口条件', 270), valueGetter: params => params.data ? conditionSummary(params.data) : '' },
  selectColumn('departmentId', '发起部门限制', [{ label: '不限', value: null }, ...catalog.value.departments.map(department => ({ label: `${department.deptName || department.deptCode} (${department.id})`, value: Number(department.id) }))], 160),
  { ...linkColumn('approvers', '人员 / 角色 / SQL', 240), valueGetter: params => params.data ? approverSummary(params.data) : '' },
  selectColumn('mode', '同级方式', modeOptions, 140),
  booleanColumn('enabled')
]);
const dataColumns: ColDef[] = [
  { field: 'name', headerName: '数据项名称', width: 180 },
  { ...largeTextColumn('sql', '取数 SQL', 580), flex: 1 },
  selectColumn('resultType', '返回类型', [{ label: '单值', value: 'SCALAR' }, { label: '人员 ID 集合', value: 'USER_IDS' }], 145)
];
const objectColumns = computed<ColDef[]>(() => [
  { field: 'name', headerName: '对象来源名称', width: 160 },
  selectColumn('tableCode', '目标业务表', objectTableOptions.value, 190),
  largeTextColumn('sql', '对象查询 SQL（只读）', 420),
  { field: 'idColumn', headerName: '主键列', width: 130 },
  { field: 'labelColumn', headerName: '标题列', width: 130 },
  {
    field: 'displayFields', headerName: '显示列（逗号分隔）', width: 240,
    cellDataType: false, cellEditor: 'agTextCellEditor',
    valueGetter: params => (params.data?.displayFields || []).join(', '),
    valueSetter: params => {
      params.data.displayFields = [...new Set(String(params.newValue || '').split(/[,，]/).map(field => field.trim()).filter(Boolean))];
      return true;
    }
  },
  { colId: 'objectFreeze', headerName: '冻结范围', width: 180, editable: false, valueGetter: () => '目标主单及全部明细' }
]);
const lockColumns = computed<ColDef[]>(() => [
  booleanColumn('enabled'),
  selectColumn('target', '锁定对象', [{ label: '当前主表', value: 'MASTER' }, { label: '全部明细', value: 'ALL_DETAILS' }, { label: '本次涉及明细', value: 'CHANGED_DETAILS' }, { label: '关联记录', value: 'RELATED' }], 145),
  {
    ...selectColumn('tableCode', '目标业务表', tableOptions.value, 200),
    cellEditorParams: (params: ICellEditorParams) => ({ values: lockTableOptions(params.data).map(option => option.value) })
  },
  {
    ...selectColumn('relationField', '目标关联字段', [], 180),
    editable: params => params.data?.target === 'RELATED',
    cellEditorParams: (params: ICellEditorParams) => ({ values: fieldOptions(params.data?.tableCode || '', true).map(field => field.value) }),
    valueFormatter: params => fieldOptions(params.data?.tableCode || '').find(field => field.value === params.value)?.label || params.value || ''
  },
  { ...selectColumn('sourceField', '关联来源字段', relatedSourceOptions.value, 180), editable: params => params.data?.target === 'RELATED' },
  { ...linkColumn('fields', '锁定字段', 220), valueGetter: params => params.data?.fields.length ? params.data.fields.join('、') : '全部字段（双击选择）' },
  { colId: 'release', headerName: '释放时机', width: 270, editable: false, valueGetter: () => '通过并生效 / 驳回 / 撤销成功后' }
]);
const actionColumns = computed<ColDef[]>(() => [
  booleanColumn('enabled'),
  selectColumn('event', '执行时机', actionEventOptions, 125),
  { field: 'level', headerName: '审批级别', width: 90, cellDataType: 'number', cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 1, max: 99, precision: 0, step: 1 }, editable: params => params.data?.event === 'NODE_COMPLETED' },
  selectColumn('code', '业务动作', catalog.value.actions.map(action => ({ label: action.name, value: action.code })), 200),
  { ...selectColumn('procedure', '业务过程', (catalog.value.procedures || []).map(procedure => ({ label: procedure.label || procedure.name, value: procedure.name })), 250), editable: params => params.data?.code === 'PROCEDURE' },
  { ...selectColumn('mode', '参数方式', [{ label: '自动取值', value: 'AUTO' }, { label: '审批时填写参数', value: 'MANUAL' }], 165), editable: params => params.data?.code === 'PROCEDURE' },
  { ...linkColumn('params', '参数映射', 230), valueGetter: params => params.data?.code === 'APPLY_PENDING_CHANGE' ? '当前待批变更（无需参数）' : params.data?.params.length ? params.data.params.map((param: ApprovalActionParam) => param.label || param.name).join('、') : '双击配置参数' },
  { colId: 'failure', headerName: '失败处理', width: 240, editable: false, valueGetter: () => '回滚本次审批并保留锁定' }
]);
const detailColumns = computed(() => ({ entries: entryColumns.value, dataItems: dataColumns, objects: objectColumns.value, locks: lockColumns.value, actions: actionColumns.value })[tab.value]);

function cloneDefinition(flow: ApprovalDefinition): ApprovalDefinition {
  const { flowId, pageCode, flowName, flowVersion, flowPriority, enabled, emptyPolicy, tableCode, trigger, entries, dataItems, locks, actions,
    direction = 'NONE', decisionMode = 'WHOLE', objects = [] } = flow;
  return JSON.parse(JSON.stringify({ flowId, pageCode, flowName, flowVersion, flowPriority, enabled, emptyPolicy, tableCode, trigger, entries, dataItems, locks, actions, direction, decisionMode, objects }));
}
function asDraft(flow: ApprovalDefinition, key?: string): FlowDraft {
  return { ...cloneDefinition(flow), _key: key || `flow-${flow.flowId}`, _dirty: false, _uncertain: false };
}
function stopEditing() { masterGrid.value?.stopEditing(); detailGrid.value?.stopEditing(); }
function dirty() {
  if (current.value) current.value._dirty = true;
  validation.value = null;
  masterGrid.value?.refresh();
}
async function selectFlow(rows: FlowDraft[]) {
  if (!rows[0] || rows[0]._key === selectedKey.value) return;
  if (busy.value) {
    await nextTick();
    if (current.value) masterGrid.value?.selectRow(current.value);
    return;
  }
  detailGrid.value?.stopEditing();
  selectedKey.value = rows[0]._key;
  selectedDetails.value = [];
  validation.value = null;
}

function replaceDetailRows(flow: FlowDraft, rows: object[]) {
  switch (tab.value) {
    case 'entries': flow.entries = rows as ApprovalEntry[]; break;
    case 'dataItems': flow.dataItems = rows as ApprovalDataItem[]; break;
    case 'objects': flow.objects = rows as ApprovalObjectSource[]; break;
    case 'locks': flow.locks = rows as ApprovalLock[]; break;
    case 'actions': flow.actions = rows as ApprovalAction[]; break;
  }
}

async function loadAll() {
  const sequence = ++loadSequence;
  const pageCode = props.pageCode;
  loading.value = true;
  loadError.value = '';
  ready.value = false;
  validation.value = null;
  const results = await Promise.allSettled([fetchApprovalDefinitions(pageCode), fetchApprovalCatalog(pageCode)]);
  if (sequence !== loadSequence) return;
  const [definitions, references] = results;
  if (references.status === 'fulfilled') catalog.value = references.value;
  else loadError.value = `字段和人员目录读取失败：${configError(references.reason)}`;
  if (definitions.status === 'fulfilled') {
    const previous = selectedKey.value;
    flows.value = definitions.value.items.map(flow => asDraft(flow));
    selectedKey.value = flows.value.some(flow => flow._key === previous) ? previous : flows.value[0]?._key || '';
    ready.value = definitions.value.ready && references.status === 'fulfilled';
    readinessMessage.value = definitions.value.message || '';
    status.value = `已读取 ${flows.value.length} 条真实配置。修改后保存整条流程。`;
  } else {
    loadError.value = [loadError.value, `审批定义读取失败：${configError(definitions.reason)}`].filter(Boolean).join('；');
    flows.value = [];
    selectedKey.value = '';
  }
  selectedDetails.value = [];
  loading.value = false;
  await nextTick();
  if (current.value) masterGrid.value?.selectRow(current.value);
}

async function addFlow() {
  stopEditing();
  const master = catalog.value.tables.find(table => table.tableCode === catalog.value.tableCode)
    || catalog.value.tables.find(table => ['MASTER', 'MAIN'].includes((table.tableType || '').toUpperCase())) || catalog.value.tables[0];
  const flow: FlowDraft = {
    flowId: null, pageCode: props.pageCode, flowName: '新审批流程', flowVersion: 1,
    flowPriority: Math.max(0, ...flows.value.map(row => row.flowPriority)) + 1, enabled: false, emptyPolicy: 'BLOCK',
    tableCode: master?.tableCode || '', trigger: { event: 'SAVE', requireApplicantForSubmit: false, operations: ['modified'], conditionType: 'ALWAYS', condition: '' },
    entries: [], dataItems: [], locks: [], actions: [], direction: 'NONE', decisionMode: 'WHOLE', objects: [],
    _key: `draft-${++draftSequence}`, _dirty: true, _uncertain: false
  };
  flows.value = [...flows.value, flow];
  selectedKey.value = flow._key;
  selectedDetails.value = [];
  validation.value = null;
  await nextTick();
  if (current.value) masterGrid.value?.selectRow(current.value);
}

function addDetail() {
  stopEditing();
  const flow = current.value;
  if (!flow) return;
  if (tab.value === 'entries') {
    const selected = selectedDetails.value[0] as ApprovalEntry | undefined;
    const level = selected?.level || 1;
    flow.entries.push({ nodeId: null, level, name: '新审批入口', mode: flow.entries.find(entry => entry.level === level)?.mode || 'OR', conditionType: 'ALWAYS', condition: '', enabled: true, departmentId: null, approvers: [] });
  } else if (tab.value === 'dataItems') {
    flow.dataItems.push({ name: '', sql: '', resultType: 'SCALAR' });
  } else if (tab.value === 'objects') {
    flow.objects.push({ key: crypto.randomUUID(), name: '新对象来源', tableCode: '', sql: '', idColumn: '', labelColumn: '', displayFields: [] });
  } else if (tab.value === 'locks') {
    flow.locks.push({ key: crypto.randomUUID(), enabled: true, target: 'MASTER', tableCode: flow.tableCode, relationField: '', sourceField: '', fields: [] });
  } else {
    flow.actions.push({ key: crypto.randomUUID(), enabled: true, event: 'FLOW_APPROVED', level: null, code: 'APPLY_PENDING_CHANGE', procedure: '', mode: 'AUTO', params: [] });
  }
  replaceDetailRows(flow, [...flow[tab.value]]);
  dirty();
}
function removeDetails() {
  stopEditing();
  if (!current.value) return;
  replaceDetailRows(current.value, current.value[tab.value].filter(row => !selectedDetails.value.includes(row)));
  selectedDetails.value = [];
  dirty();
}
function moveAction(offset: number) {
  stopEditing();
  const flow = current.value;
  if (!flow || selectedDetails.value.length !== 1) return;
  const index = flow.actions.indexOf(selectedDetails.value[0] as ApprovalAction);
  const next = index + offset;
  if (index < 0 || next < 0 || next >= flow.actions.length) return;
  const rows = [...flow.actions];
  [rows[index], rows[next]] = [rows[next], rows[index]];
  flow.actions = rows;
  dirty();
}
function changed(event: CellValueChangedEvent) {
  if (tab.value === 'entries' && current.value?.entries.includes(event.data)) {
    const entry = event.data as ApprovalEntry;
    if (event.colDef.field === 'level') {
      const existing = current.value.entries.find(row => row !== entry && row.level === entry.level);
      if (existing) entry.mode = existing.mode;
    }
    if (event.colDef.field === 'mode') current.value.entries.filter(row => row.level === entry.level).forEach(row => { row.mode = entry.mode; });
  }
  if (tab.value === 'locks' && event.colDef.field === 'target') {
    const lock = event.data as ApprovalLock;
    lock.tableCode = lockTableOptions(lock)[0]?.value || '';
    lock.relationField = '';
    lock.sourceField = '';
    lock.fields = [];
  }
  if (tab.value === 'locks' && event.colDef.field === 'tableCode') {
    const lock = event.data as ApprovalLock;
    lock.relationField = '';
    lock.fields = [];
  }
  if (tab.value === 'actions' && event.colDef.field === 'event') {
    const action = event.data as ApprovalAction;
    action.level = action.event === 'NODE_COMPLETED' ? 1 : null;
  }
  detailGrid.value?.refresh();
  dirty();
}

function openCondition(target: ConditionTarget, title: string) {
  stopEditing(); conditionTarget.value = target; conditionTitle.value = title; showCondition.value = true;
}
function masterEdit(event: CellDoubleClickedEvent) {
  if (!event.data || busy.value) return;
  if (event.colDef.field === 'trigger.condition') openCondition(event.data.trigger, `${event.data.flowName} · 送审条件`);
  if (event.colDef.field === 'trigger.operations') { operations.value = [...event.data.trigger.operations]; showOperations.value = true; }
}
function detailEdit(event: CellDoubleClickedEvent) {
  const row = event.data;
  if (!row || busy.value) return;
  if (tab.value === 'entries' && event.colDef.field === 'condition') openCondition(row, `${row.name} · 入口条件`);
  if (tab.value === 'entries' && event.colDef.field === 'approvers') { approverEntry.value = row; showApprovers.value = true; }
  if (tab.value === 'actions' && event.colDef.field === 'params' && row.code === 'PROCEDURE') { selectedAction.value = row; showActionParams.value = true; }
  if (tab.value === 'locks' && event.colDef.field === 'fields') { selectedLock.value = row; lockFields.value = [...row.fields]; showFields.value = true; }
}
function saveCondition(value: Pick<ConditionTarget, 'conditionType' | 'condition'>) {
  if (conditionTarget.value) Object.assign(conditionTarget.value, value);
  detailGrid.value?.refresh(); dirty();
}
function saveApprovers(rows: ApprovalApprover[]) { if (approverEntry.value) approverEntry.value.approvers = rows; detailGrid.value?.refresh(); dirty(); }
function saveParams(rows: ApprovalActionParam[]) { if (selectedAction.value) selectedAction.value.params = rows; detailGrid.value?.refresh(); dirty(); }
function saveLockFields() { if (selectedLock.value) selectedLock.value.fields = [...lockFields.value]; showFields.value = false; detailGrid.value?.refresh(); dirty(); }
function saveOperations() { if (current.value) current.value.trigger.operations = [...operations.value] as ApprovalDefinition['trigger']['operations']; showOperations.value = false; dirty(); }

async function validateCurrent() {
  stopEditing();
  if (!current.value) return;
  busy.value = true;
  try {
    validation.value = await validateApprovalDefinition(cloneDefinition(current.value));
    if (validation.value.valid) message.success('定义校验通过；尚未保存，也未执行 SQL 或审批动作');
  } catch (error) { message.error(configError(error)); }
  finally { busy.value = false; }
}
async function saveCurrent() {
  stopEditing();
  const flow = current.value;
  if (!flow || !ready.value || flow._uncertain) return;
  busy.value = true;
  let saved: ApprovalDefinition | undefined;
  let writeStarted = false;
  try {
    validation.value = await validateApprovalDefinition(cloneDefinition(flow));
    if (!validation.value.valid) return;
    writeStarted = true;
    saved = await saveApprovalDefinition(cloneDefinition(flow));
    if (!saved.flowId) throw new Error('保存已返回，但未返回流程 ID，请刷新核对');
    const persisted = await fetchApprovalDefinition(saved.flowId);
    const index = flows.value.findIndex(item => item._key === flow._key);
    flows.value[index] = asDraft(persisted, flow._key);
    status.value = `“${persisted.flowName}”版本 ${persisted.flowVersion} 已保存并回读；现有审批仍使用各自绑定的版本。`;
    message.success('流程及明细已整体保存，并已回读确认');
    await nextTick();
    if (current.value) masterGrid.value?.selectRow(current.value);
  } catch (error) {
    if (!writeStarted) { message.error(configError(error)); return; }
    flow._uncertain = true;
    status.value = saved ? '保存已返回，回读未完成；请刷新核对实际版本。' : '请求未完成，请刷新核对实际保存结果后再操作。';
    message.error(`${status.value} ${configError(error)}`);
    masterGrid.value?.refresh();
  } finally { busy.value = false; }
}
async function deleteCurrent() {
  const flow = current.value;
  if (!flow) return;
  if (!flow.flowId) { flows.value = flows.value.filter(row => row !== flow); selectedKey.value = flows.value[0]?._key || ''; return; }
  busy.value = true;
  try {
    await deleteApprovalDefinition(flow.flowId);
    const persisted = await fetchApprovalDefinitions(props.pageCode);
    const deleted = persisted.items.find(item => item.flowId === flow.flowId);
    flows.value = flows.value.flatMap(row => row._key !== flow._key ? [row] : deleted ? [asDraft(deleted, flow._key)] : []);
    if (!flows.value.some(row => row._key === selectedKey.value)) selectedKey.value = flows.value[0]?._key || '';
    await nextTick();
    if (current.value) masterGrid.value?.selectRow(current.value);
    message.success('删除／停用已提交并回读，审批历史保留');
  }
  catch (error) { message.error(`操作结果需刷新核对：${configError(error)}`); }
  finally { busy.value = false; }
}

watch(tab, () => { detailGrid.value?.stopEditing(); selectedDetails.value = []; });
watch(() => props.pageCode, loadAll, { immediate: true });
</script>

<template>
  <div class="section-approval">
    <NAlert v-if="loadError" type="error" :bordered="false" class="notice">{{ loadError }}</NAlert>
    <NAlert v-if="!loading && !ready && !loadError" type="warning" :bordered="false" class="notice">{{ readinessMessage || '审批数据库迁移尚未就绪，当前无法保存发布。' }}</NAlert>
    <div class="toolbar">
      <NSpace size="small">
        <NButton size="small" :disabled="loading || busy || !catalog.tables.length" @click="addFlow">新增流程</NButton>
        <NButton size="small" type="primary" :loading="busy" :disabled="!current || !ready || current._uncertain || loading" @click="saveCurrent">保存并发布当前流程</NButton>
        <NButton size="small" :disabled="!current || busy || loading || !!loadError" @click="validateCurrent">校验配置</NButton>
        <NPopconfirm @positive-click="deleteCurrent">
          <template #trigger><NButton size="small" :disabled="!current || busy || !ready" type="error" quaternary>删除／停用</NButton></template>
          有审批历史的流程只会停用，历史记录保留。确认处理当前流程？
        </NPopconfirm>
        <NPopconfirm :disabled="!flows.some(flow => flow._dirty)" @positive-click="loadAll">
          <template #trigger><NButton size="small" :disabled="busy || loading" @click="!flows.some(flow => flow._dirty) && loadAll()">刷新</NButton></template>
          刷新会丢弃当前页面尚未保存的配置草稿，确认继续？
        </NPopconfirm>
      </NSpace>
      <span class="hint">主表：选择流程，下方明细随选中行切换</span>
    </div>
    <ApprovalConfigGrid ref="masterGrid" :rows="flows" :columns="masterColumns" :height="192" :loading="loading" :disabled="busy" @select="selectFlow" @change="dirty" @edit="masterEdit" />
    <div class="divider" />
    <template v-if="current">
      <div class="detail-heading">从表：{{ current.flowName }}<span class="hint">{{ current._dirty ? '有未保存配置' : `当前版本 ${current.flowVersion}` }}</span></div>
      <NTabs v-model:value="tab" type="line" size="small" animated>
        <NTabPane name="entries" :tab="`审批入口 (${current.entries.length})`" />
        <NTabPane name="dataItems" :tab="`自定义数据 / SQL (${current.dataItems.length})`" />
        <NTabPane name="objects" :tab="`审批对象 (${current.objects.length})`" />
        <NTabPane name="locks" :tab="`锁定范围 (${current.locks.length})`" />
        <NTabPane name="actions" :tab="`审批动作 (${current.actions.length})`" />
      </NTabs>
      <div class="toolbar detail-toolbar">
        <NSpace size="small">
          <NButton size="small" :disabled="busy" @click="addDetail">新增明细</NButton>
          <NButton size="small" :disabled="busy || !selectedDetails.length" @click="removeDetails">删除选中明细</NButton>
          <template v-if="tab === 'actions'"><NButton size="small" :disabled="selectedDetails.length !== 1" @click="moveAction(-1)">上移</NButton><NButton size="small" :disabled="selectedDetails.length !== 1" @click="moveAction(1)">下移</NButton></template>
        </NSpace>
        <span class="hint">{{ detailHelp[tab] }}</span>
      </div>
      <NAlert v-if="tab === 'objects'" type="info" :bordered="false" class="notice">查询 SQL 可用 :billId、:contextJson、:old_字段编码、:new_字段编码、:user_字段编码及 :data_数据项名称绑定源数据。勾选对象审批中，未选对象驳回；各级勾选只表示本级同意，最终通过后才生效。<template v-if="current.direction === 'GOODS_TO_COST' && current.decisionMode === 'SELECTED'">批准时未勾选任何对象，最终通过后仅更新物料清单，成本核算不变。</template>同步仅由用户主动保存发起，到目标单据为止。</NAlert>
      <ApprovalConfigGrid :key="tab" ref="detailGrid" :rows="detailRows" :columns="detailColumns" :height="292" :disabled="busy" multiple @select="selectedDetails = $event" @change="changed" @edit="detailEdit" />
    </template>
    <NEmpty v-else-if="!loading" description="当前页面尚无审批流程，可新增流程后配置入口、锁定与动作" class="empty" />
    <NAlert v-if="validation && !validation.valid" type="error" :bordered="false" class="notice validation"><div v-for="(error, index) in validation.errors" :key="index">{{ error }}</div></NAlert>
    <NAlert v-if="validation?.warnings?.length" type="warning" :bordered="false" class="notice validation"><div v-for="(warning, index) in validation.warnings" :key="index">{{ warning }}</div></NAlert>
    <div class="footer" role="status">{{ status }}</div>
    <ApprovalConditionEditor v-if="conditionTarget && current" v-model:show="showCondition" :title="conditionTitle" :condition-type="conditionTarget.conditionType" :condition="conditionTarget.condition" :catalog="catalog" :table-code="current.tableCode" :data-items="current.dataItems" @save="saveCondition" />
    <ApprovalApproverEditor v-if="approverEntry" v-model:show="showApprovers" :entry-name="approverEntry.name" :approvers="approverEntry.approvers" :catalog="catalog" @save="saveApprovers" />
    <ApprovalActionParamsEditor v-if="selectedAction" v-model:show="showActionParams" :params="selectedAction.params" :manual="selectedAction.mode === 'MANUAL'" @save="saveParams" />
    <NModal v-model:show="showFields" preset="card" title="选择锁定字段" style="width: min(680px, 94vw)">
      <NSpace vertical :size="16">
        <NSelect v-model:value="lockFields" :options="lockFieldOptions" multiple filterable clearable placeholder="留空表示锁定全部业务字段" />
        <div class="hint">仅选择的字段禁止修改；删除记录仍受锁定保护。全部明细锁也阻止新增和改所属主单。</div>
        <div class="modal-actions"><NButton @click="showFields = false">取消</NButton><NButton type="primary" @click="saveLockFields">应用到当前草稿</NButton></div>
      </NSpace>
    </NModal>
    <NModal v-model:show="showOperations" preset="card" title="哪些保存操作触发送审" style="width: min(560px, 94vw)">
      <NSpace vertical :size="16">
        <NCheckboxGroup v-model:value="operations"><NSpace><NCheckbox value="modified" label="修改" /><NCheckbox value="added" label="新增" /><NCheckbox value="deleted" label="删除" /></NSpace></NCheckboxGroup>
        <div class="modal-actions"><NButton @click="showOperations = false">取消</NButton><NButton type="primary" @click="saveOperations">应用到当前草稿</NButton></div>
      </NSpace>
    </NModal>
  </div>
</template>

<style scoped>
.section-approval { min-width: 0; padding: 8px 0; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 8px 0; }
.hint { color: #687384; font-size: 12px; font-weight: normal; }
.notice { margin-bottom: 8px; }
.divider { height: 8px; margin: 10px 0 4px; background: #f5f7fa; border-top: 1px solid #dce2e9; border-bottom: 1px solid #dce2e9; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; padding: 6px 0; font-weight: 500; }
.detail-toolbar { padding-top: 4px; }
.section-approval :deep(.n-tabs-pane-wrapper) { display: none; }
.section-approval :deep(.n-tabs-tab) { padding: 6px 0; font-size: 13px; }
.footer { margin-top: 10px; padding: 9px 12px; border-top: 1px solid #dce2e9; background: #f5f7fa; font-size: 12px; color: #687384; }
.validation { margin-top: 10px; }
.empty { padding: 36px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
