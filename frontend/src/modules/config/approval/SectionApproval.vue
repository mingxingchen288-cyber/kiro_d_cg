<script setup lang="ts">
/**
 * 页面配置中的"审批流"一节（FC-05），布局和样式同旧系统 SectionApproval.vue：工具栏、流程列表（主表）、
 * 三个 Tab（审批节点、冻结节点、展示数据）的明细表、校验错误、状态栏，以及双击打开的弹窗。
 * 参数和通知（C06 7.1 的 params、notify）在明细标题行的"参数""通知"中编辑。状态和动作在 ApprovalFlowEditor。
 */
import { computed, reactive, ref, watch } from 'vue';
import { NAlert, NButton, NEmpty, NInput, NPopconfirm, NSpace, NTabPane, NTabs } from 'naive-ui';
import type { CellDoubleClickedEvent, CellValueChangedEvent } from 'ag-grid-community';
import type { Option } from '../core/catalog';
import { useConfigContext } from '../core/context';
import ConfigGrid from '../components/ConfigGrid.vue';
import { ApprovalFlowEditor, type FlowTab, TAB_HELP, detailDialog } from './flow-editor';
import type { DisplayRow, FlowDraft, FreezeRow, NodeRow } from './flow-model';
import { displayColumns, flowColumns, freezeColumns, nodeColumns } from './section-columns';
import ApprovalActionsEditor from './ApprovalActionsEditor.vue';
import ApprovalApproverEditor from './ApprovalApproverEditor.vue';
import ApprovalConditionEditor from './ApprovalConditionEditor.vue';
import ApprovalDisplayColumnsEditor from './ApprovalDisplayColumnsEditor.vue';
import ApprovalNotifyEditor from './ApprovalNotifyEditor.vue';
import ApprovalOperationsEditor from './ApprovalOperationsEditor.vue';
import ApprovalParamsEditor from './ApprovalParamsEditor.vue';

const props = defineProps<{ pageCode: string }>();
const { api, store, notify } = useConfigContext();
const editor = new ApprovalFlowEditor(store, api, props.pageCode, notify);
const state = editor.state;
const current = computed(() => editor.current);
const tables = computed(() => state.catalog?.tables ?? []);
const selectedRows = ref<any[]>([]);
const masterGrid = ref<InstanceType<typeof ConfigGrid>>();
const detailGrid = ref<InstanceType<typeof ConfigGrid>>();

/** 已读到的表或视图的列（主键列下拉、显示列、写入字段用） */
const columnsOf = reactive<Record<string, string[]>>({});
async function fetchColumns(name: string) {
  const key = name.trim().toUpperCase();
  if (!key) return [];
  if (!columnsOf[key]) columnsOf[key] = (await editor.schemaColumns(key)).columns.map(c => c.name);
  return columnsOf[key];
}
const toOptions = (names: string[]): Option[] => names.map(n => ({ label: n, value: n }));

const masterCols = computed(() => flowColumns(tables.value, state.catalog?.page.title ?? props.pageCode));
const detailCols = computed(() => {
  const dir = state.directory;
  if (state.tab === 'nodes') return nodeColumns(dir.departments, dir.roles, dir.users);
  if (state.tab === 'freeze') return freezeColumns();
  return displayColumns(tables.value, name => columnsOf[name.trim().toUpperCase()] ?? null);
});
const detailRows = computed(() => editor.rows(state.tab));
const levels = computed(() => [...new Set((current.value?.nodes ?? []).map(n => Number(n.level)))].sort((a, b) => a - b));
const areaProblems = (area: 'params' | 'notify') => state.problems.filter(p => p.area === area).map(p => `${p.path ?? ''}：${p.message}`);

function flowProblem(row: FlowDraft, column: string) {
  return editor.problemAt('flow', row._key, column)[0]?.message ?? null;
}
function detailProblem(row: { _id: string }, column: string) {
  return editor.problemAt(state.tab, row._id, column)[0]?.message ?? null;
}

function stopEditing() {
  masterGrid.value?.stopEditing();
  detailGrid.value?.stopEditing();
}
function refresh() {
  masterGrid.value?.refresh();
  detailGrid.value?.refresh();
}

// ---- 弹窗
const dialog = reactive({
  operations: false,
  condition: false,
  approvers: false,
  columns: false,
  actions: false,
  params: false,
  notify: false
});
const conditionTarget = ref<{ row: NodeRow | FreezeRow | DisplayRow; title: string; withType: boolean } | null>(null);
const approverTarget = ref<NodeRow | null>(null);
const blockTarget = ref<DisplayRow | null>(null);
const fieldOptions = ref<Option[]>([]);
const targetOptions = ref<Option[]>([]);
const escapeOptions = ref<Option[]>([]);
let entities: Awaited<ReturnType<typeof store.loadAll<'entity'>>> | null = null;

/** 显示列可选的字段：表格块取实体字段；受影响单据取表 / 视图的列，修改表注册过时加上所属主表的 master.字段 */
async function columnChoices(row: DisplayRow) {
  if (row.region !== 'affected') {
    const table = tables.value.find(t => t.entity === row.source);
    return { fields: (table?.fields ?? []).map(f => ({ label: `${f.label} · ${f.name}`, value: f.name })), target: null };
  }
  const own = toOptions(await fetchColumns(row.source));
  const targetName = (row.targetTable || row.source).toUpperCase();
  const target = toOptions(await fetchColumns(targetName));
  entities ??= await store.loadAll('entity');
  const registered = entities.find(e => e.content.table.toUpperCase() === targetName);
  const master = registered && entities.find(e => (e.content.details ?? []).some(d => d.entity === registered.key));
  const masterFields = (master ?? registered)?.content.fields.map(f => ({ label: `主表 · ${f.label} · master.${f.name}`, value: `master.${f.name}` })) ?? [];
  return { fields: [...own, ...(registered ? masterFields : [])], target };
}

async function onMasterEdit(event: CellDoubleClickedEvent) {
  if (state.busy || !event.data) return;
  editor.select((event.data as FlowDraft)._key);
  if (event.colDef.colId === 'operations') dialog.operations = true;
}

async function onDetailEdit(event: CellDoubleClickedEvent) {
  const row = event.data;
  const target = detailDialog(event.colDef.colId ?? event.colDef.field, row ?? {});
  // 不打开弹窗的格子由表格就地编辑，这里不能结束编辑（双击后表格已进入编辑）
  if (state.busy || !row || !target) return;
  stopEditing();
  if (target === 'condition') {
    const title = state.tab === 'nodes' ? `${row.name} · 入口条件（第 ${row.level} 级）` : state.tab === 'freeze' ? `${row.table || '冻结表'} · 关联条件` : `${row.title} · 关联条件`;
    conditionTarget.value = { row, title, withType: state.tab === 'nodes' };
    dialog.condition = true;
  }
  if (target === 'approvers') {
    approverTarget.value = row;
    dialog.approvers = true;
  }
  if (target === 'columns' || target === 'actions') {
    blockTarget.value = row;
    const choices = await columnChoices(row);
    fieldOptions.value = choices.fields;
    targetOptions.value = choices.target ?? [];
    if (target === 'columns') dialog.columns = true;
    else {
      escapeOptions.value = (await store.loadAll('operation')).filter(o => o.content.kind === 'escapeHatch').map(o => ({ label: `${o.name} · ${o.key}`, value: o.key }));
      dialog.actions = true;
    }
  }
}

function onDetailChange(event: CellValueChangedEvent) {
  const field = event.colDef.field;
  if (state.tab === 'display' && field === 'region') editor.regionChanged(event.data);
  if (state.tab === 'display' && field === 'source' && event.data.region === 'affected') fetchColumns(event.data.source);
  if (state.tab === 'nodes' && field === 'conditionType' && event.data.conditionType === 'always') event.data.condition = '';
  editor.markDirty();
  refresh();
}

function onTabChange(tab: FlowTab) {
  detailGrid.value?.stopEditing();
  state.tab = tab;
  selectedRows.value = [];
}

function addRow() {
  stopEditing();
  editor.addRow(selectedRows.value.map(r => r._id));
}
function removeRows() {
  stopEditing();
  editor.removeRows(selectedRows.value.map(r => r._id));
  selectedRows.value = [];
}

async function save() {
  stopEditing();
  await editor.saveCurrent();
  refresh();
}
async function validate() {
  stopEditing();
  await editor.validateCurrent();
  refresh();
}

watch(
  () => state.flows.filter(f => f.display.some(d => d.region === 'affected')).flatMap(f => f.display.map(d => d.source)),
  sources => sources.filter(Boolean).forEach(s => fetchColumns(s)),
  { immediate: true }
);

editor.load();
</script>

<template>
  <div class="section-approval">
    <NAlert v-if="state.loadError" type="error" :bordered="false" class="notice">{{ state.loadError }}</NAlert>
    <div class="toolbar">
      <NSpace size="small">
        <NButton size="small" :disabled="state.loading || state.busy || !tables.length" @click="editor.addFlow()">新增流程</NButton>
        <NButton size="small" type="primary" :loading="state.busy" :disabled="!current || state.loading" @click="save">保存并发布当前流程</NButton>
        <NButton size="small" :disabled="!current || state.busy || state.loading" @click="validate">校验配置</NButton>
        <NPopconfirm @positive-click="editor.removeCurrent()">
          <template #trigger><NButton size="small" :disabled="!current || state.busy" type="error" quaternary>删除／停用</NButton></template>
          删除后本流程不再触发，已经发起的审批按提交时的定义走完；只想暂停时取消勾选"启用"再保存。确认删除当前流程？
        </NPopconfirm>
        <NPopconfirm :disabled="!editor.hasDirty()" @positive-click="editor.load()">
          <template #trigger><NButton size="small" :disabled="state.busy || state.loading" @click="!editor.hasDirty() && editor.load()">刷新</NButton></template>
          刷新会丢弃当前页面尚未保存的配置草稿，确认继续？
        </NPopconfirm>
      </NSpace>
      <span class="hint">主表：选择流程，下方明细随选中行切换</span>
    </div>
    <ConfigGrid ref="masterGrid" :rows="state.flows" :columns="masterCols" :height="192" :loading="state.loading" :disabled="state.busy" row-key="_key" :problem-of="flowProblem" @select="rows => rows[0] && editor.select(rows[0]._key)" @change="editor.markDirty()" @edit="onMasterEdit" />
    <div class="divider" />
    <template v-if="current">
      <div class="detail-heading">
        <span>从表：{{ current.name }}</span>
        <span class="heading-extra">
          <span class="hint">编码</span>
          <NInput v-model:value="current.key" size="tiny" :disabled="current.version !== null" style="width: 200px" @update:value="editor.markDirty()" />
          <NButton text size="small" type="primary" @click="dialog.params = true">参数 ({{ current.params.length }})</NButton>
          <NButton text size="small" type="primary" @click="dialog.notify = true">通知 ({{ current.notify.length }})</NButton>
          <span class="hint">{{ current.dirty ? '有未保存配置' : `当前版本 ${current.version}` }}</span>
        </span>
      </div>
      <NTabs :value="state.tab" type="line" size="small" animated @update:value="onTabChange">
        <NTabPane name="nodes" :tab="`审批节点 (${current.nodes.length})`" />
        <NTabPane name="freeze" :tab="`冻结节点 (${current.freeze.length})`" />
        <NTabPane name="display" :tab="`展示数据 (${current.display.length})`" />
      </NTabs>
      <div class="toolbar detail-toolbar">
        <NSpace size="small">
          <NButton size="small" :disabled="state.busy" @click="addRow">新增明细</NButton>
          <NButton size="small" :disabled="state.busy || !selectedRows.length" @click="removeRows">删除选中明细</NButton>
          <template v-if="state.tab === 'display'">
            <NButton size="small" :disabled="selectedRows.length !== 1" @click="editor.moveDisplay(selectedRows[0]._id, -1)">上移</NButton>
            <NButton size="small" :disabled="selectedRows.length !== 1" @click="editor.moveDisplay(selectedRows[0]._id, 1)">下移</NButton>
          </template>
        </NSpace>
        <span class="hint">{{ TAB_HELP[state.tab] }}</span>
      </div>
      <ConfigGrid :key="`${current._key}-${state.tab}`" ref="detailGrid" :rows="detailRows" :columns="detailCols as any" :height="292" :disabled="state.busy" multiple row-key="_id" :problem-of="detailProblem" @select="selectedRows = $event" @change="onDetailChange" @edit="onDetailEdit" />
    </template>
    <NEmpty v-else-if="!state.loading" description="当前页面尚无审批流程，可新增流程后配置审批节点、冻结节点和展示数据" class="empty" />
    <NAlert v-if="state.problems.length" type="error" :bordered="false" class="notice validation">
      <div v-for="(problem, index) in state.problems" :key="index">{{ problem.path ? `${problem.path}：` : '' }}{{ problem.message }}</div>
    </NAlert>
    <div class="footer" role="status">{{ state.status }}</div>

    <template v-if="current">
      <ApprovalOperationsEditor v-model:show="dialog.operations" :flow-name="current.name" :tables="tables" :operations="current.operations" @save="ops => (editor.applyOperations(ops), refresh())" />
      <ApprovalConditionEditor
        v-if="conditionTarget"
        v-model:show="dialog.condition"
        :title="conditionTarget.title"
        :with-type="conditionTarget.withType"
        :condition-type="(conditionTarget.row as NodeRow).conditionType ?? 'sql'"
        :condition="conditionTarget.row.condition"
        :tables="tables"
        :params="current.params"
        @save="value => (editor.applyCondition(conditionTarget!.row, value), refresh())"
      />
      <ApprovalApproverEditor v-if="approverTarget" v-model:show="dialog.approvers" :node-name="approverTarget.name" :approvers="approverTarget.approvers" :roles="state.directory.roles" :users="state.directory.users" @save="rows => (editor.applyApprovers(approverTarget!, rows), refresh())" />
      <ApprovalDisplayColumnsEditor v-if="blockTarget" v-model:show="dialog.columns" :title="blockTarget.title" :columns="blockTarget.columns" :field-options="fieldOptions" :target-options="blockTarget.region === 'affected' ? targetOptions : null" @save="cols => (editor.applyColumns(blockTarget!, cols), refresh())" />
      <ApprovalActionsEditor v-if="blockTarget" v-model:show="dialog.actions" :title="blockTarget.title" :actions="blockTarget.actions" :target-options="targetOptions" :escape-options="escapeOptions" :load-columns="async name => toOptions(await fetchColumns(name))" @save="actions => (editor.applyActions(blockTarget!, actions), refresh())" />
      <ApprovalParamsEditor v-model:show="dialog.params" :params="current.params" :levels="levels" :problems="areaProblems('params')" @save="rows => editor.applyParams(rows)" />
      <ApprovalNotifyEditor v-model:show="dialog.notify" :rules="current.notify" :roles="state.directory.roles" :problems="areaProblems('notify')" @save="rows => editor.applyNotify(rows)" />
    </template>
  </div>
</template>

<style scoped>
.section-approval { min-width: 0; padding: 8px 0; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 8px 0; }
.hint { color: #687384; font-size: 12px; font-weight: normal; }
.notice { margin-bottom: 8px; }
.divider { height: 8px; margin: 10px 0 4px; background: #f5f7fa; border-top: 1px solid #dce2e9; border-bottom: 1px solid #dce2e9; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; padding: 6px 0; font-weight: 500; }
.heading-extra { display: flex; align-items: center; gap: 10px; }
.detail-toolbar { padding-top: 4px; }
.section-approval :deep(.n-tabs-pane-wrapper) { display: none; }
.section-approval :deep(.n-tabs-tab) { padding: 6px 0; font-size: 13px; }
.footer { margin-top: 10px; padding: 9px 12px; border-top: 1px solid #dce2e9; background: #f5f7fa; font-size: 12px; color: #687384; }
.validation { margin-top: 10px; }
.empty { padding: 36px; }
</style>
