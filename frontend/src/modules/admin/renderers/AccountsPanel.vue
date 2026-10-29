<script setup lang="ts">
/**
 * 人员管理（旧系统 `user-manage`）：工具栏 + 表格，表格内直接改，点"保存"提交。行为都在 accounts.ts。
 * 部门列用下拉选择（旧页面为部门ID的 Lookup 加部门名称两列，这里合成一列显示名称）。
 */
import { computed, onMounted, ref, shallowRef } from 'vue';
import { NButton, NInput, NModal, NSpace } from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import type {
  ColDef,
  EditableCallbackParams,
  GetRowIdParams,
  GridApi,
  GridReadyEvent,
  RowClassParams,
  RowSelectionOptions,
  ValueSetterParams
} from 'ag-grid-community';
import { type AccountField, type AccountRow, AccountsModel, INITIAL_PASSWORD } from '../accounts';
import type { AdminDeps } from '../shared';
import { onShownAgain } from './shown-again';

defineOptions({ name: 'AccountsPanel' });

const props = defineProps<{ deps: AdminDeps }>();

const model = new AccountsModel(props.deps);
const state = model.state;
const api = shallowRef<GridApi<AccountRow> | null>(null);
const selectedId = ref<string | null>(null);
const keyword = ref('');
const passwordFor = ref<AccountRow | null>(null);
const password = ref(INITIAL_PASSWORD);
const root = ref<HTMLElement | null>(null);

// 切回人员管理时重新读取部门和角色：刚在部门管理新建的部门马上能在"部门"下拉中选到
onShownAgain(root, () => void model.refreshChoices());

const selected = computed(() => (selectedId.value ? (model.row(selectedId.value) ?? null) : null));
const dirtyCount = computed(() => model.dirtyCount);

/** 每次给表格新的行对象，表格按 getRowId 只刷新变了的行 */
const rowData = computed(() => state.rows.map(row => ({ ...row, roleCodes: [...row.roleCodes] })));

const departmentRef = computed<Record<string, string>>(() => ({
  '': '（无）',
  ...Object.fromEntries(state.departments.map(d => [d.departmentId, d.name]))
}));

function setter(field: AccountField) {
  return (params: ValueSetterParams<AccountRow>) => {
    const value = params.newValue === undefined || params.newValue === null ? null : String(params.newValue);
    model.edit(params.data.id, field, value);
    return false;
  };
}

const onlyNew = (params: EditableCallbackParams<AccountRow>) => Boolean(params.data?.isNew);

const columnDefs = computed<ColDef<AccountRow>[]>(() => [
  { colId: 'userId', headerName: 'ID', field: 'userId', width: 90 },
  {
    colId: 'username',
    headerName: '用户名',
    field: 'username',
    width: 140,
    editable: onlyNew,
    valueSetter: setter('username')
  },
  {
    colId: 'displayName',
    headerName: '姓名',
    field: 'displayName',
    width: 140,
    editable: true,
    valueSetter: setter('displayName')
  },
  {
    colId: 'departmentId',
    headerName: '部门',
    width: 180,
    editable: true,
    valueGetter: params => params.data?.departmentId ?? '',
    valueSetter: setter('departmentId'),
    refData: departmentRef.value,
    cellEditor: 'agSelectCellEditor',
    // 选项按部门列表的顺序，"（无）"在最前（对象的数字键会被排到前面，不能用 Object.keys）
    cellEditorParams: { values: ['', ...state.departments.map(d => d.departmentId)] }
  },
  {
    colId: 'enabled',
    headerName: '状态',
    width: 90,
    valueGetter: params => (params.data?.enabled ? '启用' : '停用'),
    cellClass: params => (params.data?.enabled ? '' : 'text-error')
  },
  {
    colId: 'roles',
    headerName: '角色',
    flex: 1,
    minWidth: 160,
    valueGetter: params => (params.data ? model.roleNames(params.data.roleCodes) : '')
  },
  {
    colId: 'password',
    headerName: '初始密码',
    field: 'password',
    width: 130,
    editable: onlyNew,
    valueSetter: setter('password')
  }
]);

const rowSelection: RowSelectionOptions = { mode: 'singleRow', checkboxes: false, enableClickSelection: true };

const rowClassRules = {
  'admin-row-new': (params: RowClassParams<AccountRow>) => Boolean(params.data?.isNew),
  'admin-row-changed': (params: RowClassParams<AccountRow>) => Boolean(params.data?.changed)
};

function getRowId(params: GetRowIdParams<AccountRow>) {
  return params.data.id;
}

function onGridReady(event: GridReadyEvent<AccountRow>) {
  api.value = event.api;
}

function onSelectionChanged() {
  selectedId.value = api.value?.getSelectedRows()[0]?.id ?? null;
}

function addRow() {
  const id = model.addRow();
  setTimeout(() => {
    const node = api.value?.getRowNode(id);
    if (!node) return;
    node.setSelected(true, true);
    api.value?.startEditingCell({ rowIndex: node.rowIndex ?? 0, colKey: 'username' });
  }, 0);
}

async function save() {
  api.value?.stopEditing();
  await model.save();
}

async function setEnabled(enabled: boolean) {
  if (selected.value) await model.setEnabled(selected.value.id, enabled);
}

function openPassword() {
  if (!selected.value || selected.value.isNew) return;
  passwordFor.value = selected.value;
  password.value = INITIAL_PASSWORD;
}

async function submitPassword() {
  if (!passwordFor.value) return;
  const ok = await model.changePassword(passwordFor.value.id, password.value);
  if (ok) passwordFor.value = null;
}

onMounted(() => {
  void model.load();
});
</script>

<template>
  <div ref="root" class="admin-panel h-full flex-col">
    <div class="admin-panel__toolbar flex-y-center gap-8px">
      <NSpace size="small">
        <NButton size="small" type="primary" :disabled="state.saving" @click="addRow">新增</NButton>
        <NButton
          size="small"
          type="error"
          :disabled="!selected || selected.isNew || !selected.enabled || state.saving"
          @click="setEnabled(false)"
        >
          停用
        </NButton>
        <NButton
          size="small"
          :disabled="!selected || selected.isNew || selected.enabled || state.saving"
          @click="setEnabled(true)"
        >
          启用
        </NButton>
        <NButton size="small" :disabled="!selected || selected.isNew || state.saving" @click="openPassword">
          初始化密码
        </NButton>
        <NButton size="small" :disabled="dirtyCount === 0" :loading="state.saving" @click="save">保存</NButton>
      </NSpace>
      <NInput
        v-model:value="keyword"
        size="small"
        clearable
        placeholder="用户名或姓名"
        class="w-200px"
        @keyup.enter="model.search(keyword)"
        @clear="model.search('')"
      />
      <NButton size="small" :disabled="state.saving" @click="model.search(keyword)">查询</NButton>
      <span v-if="dirtyCount > 0" class="text-12px text-#999">{{ dirtyCount }} 行未保存</span>
      <span v-if="state.error" class="text-12px text-error">{{ state.error }}</span>
    </div>
    <div class="min-h-0 flex-1">
      <AgGridVue
        class="h-full"
        :row-data="rowData"
        :column-defs="columnDefs"
        :get-row-id="getRowId"
        :row-selection="rowSelection"
        :row-class-rules="rowClassRules"
        :loading="state.loading"
        :stop-editing-when-cells-lose-focus="true"
        :undo-redo-cell-editing="false"
        @grid-ready="onGridReady"
        @selection-changed="onSelectionChanged"
      />
    </div>
    <NModal
      :show="Boolean(passwordFor)"
      preset="card"
      title="初始化密码"
      class="w-420px"
      @update:show="(v: boolean) => !v && (passwordFor = null)"
    >
      <div class="flex-col gap-8px">
        <span class="text-13px">{{ passwordFor?.displayName }}（{{ passwordFor?.username }}）的新密码：</span>
        <NInput v-model:value="password" type="password" show-password-on="click" />
        <span class="text-12px text-#999">6-18 位字母、数字或符号；预填的是旧系统初始化密码。</span>
      </div>
      <template #footer>
        <NSpace justify="end" size="small">
          <NButton size="small" @click="passwordFor = null">取消</NButton>
          <NButton size="small" type="primary" :disabled="!password" @click="submitPassword">确定</NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.admin-panel__toolbar {
  padding: 4px 0 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

:deep(.admin-row-new) {
  font-style: italic;
  background-color: #eef4ff;
}

:deep(.admin-row-changed) {
  background-color: #e8f8e6;
}
</style>
