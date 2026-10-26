<script setup lang="ts">
import { computed, ref } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { GetRowIdParams, RowSelectionOptions, SelectionChangedEvent } from 'ag-grid-community';
import { NAlert, NButton, NDatePicker, NForm, NFormItem, NInput, NInputNumber, NModal, NSpace, NSwitch, useMessage } from 'naive-ui';
import { approveApproval, fetchApprovalActionConfig, rejectApproval } from '@/service/api/approval-runtime';
import type { ApprovalRuntimeObject, ApprovalRuntimeObjectColumn, ApprovalRuntimeParameter, ApprovalRuntimePayload } from '@/service/api/approval-runtime';
import type { ApprovalDecisionMode } from '@/service/api/approval-config';
import { approvalErrorMessage as errorMessage } from './approval-errors';
import { buildApprovalObjectColumns } from './approval-object-columns';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';

type Decision = 'approve' | 'reject';
const emit = defineEmits<{ complete: [result: { action: Decision; data: any }]; busy: [value: boolean] }>();
const message = useMessage();
const visible = ref(false);
const loading = ref(false);
const uncertain = ref(false);
const errorText = ref('');
const action = ref<Decision>('approve');
const payload = ref<ApprovalRuntimePayload>();
const approvalParameters = ref<ApprovalRuntimeParameter[]>([]);
const rejectionParameters = ref<ApprovalRuntimeParameter[]>([]);
const values = ref<Record<string, any>>({});
const decisionMode = ref<ApprovalDecisionMode>('WHOLE');
const allowSourceOnlyApproval = ref(false);
const objects = ref<ApprovalRuntimeObject[]>([]);
const objectColumnDefinitions = ref<ApprovalRuntimeObjectColumn[]>([]);
const selectedObjectKeys = ref<string[]>([]);
const selectsObjects = computed(() => decisionMode.value === 'SELECTED');
const pendingObjects = computed(() => objects.value.filter(object => object.status === 'PENDING'));
const selectedCount = computed(() => action.value === 'approve' ? selectedObjectKeys.value.length : 0);
const rejectedCount = computed(() => pendingObjects.value.length - selectedCount.value);
const sourceOnlyApproval = computed(() => selectsObjects.value && allowSourceOnlyApproval.value
  && action.value === 'approve' && selectedCount.value === 0);
const missingRequiredObjects = computed(() => selectsObjects.value && !pendingObjects.value.length
  && !allowSourceOnlyApproval.value);
const parameters = computed(() => selectsObjects.value && action.value === 'approve' && selectedCount.value === 0
  && !allowSourceOnlyApproval.value
  ? rejectionParameters.value : approvalParameters.value);
const objectSelection = computed<RowSelectionOptions<ApprovalRuntimeObject>>(() => ({
  mode: 'multiRow',
  checkboxes: true,
  headerCheckbox: true,
  enableClickSelection: false,
  selectAll: 'all',
  isRowSelectable: node => action.value === 'approve' && node.data?.status === 'PENDING'
}));
const objectColumns = computed(() => buildApprovalObjectColumns(objects.value, objectColumnDefinitions.value));
const submitLabel = computed(() => {
  if (!selectsObjects.value) return '确认提交';
  if (action.value === 'reject') return '确认驳回整个审批';
  if (sourceOnlyApproval.value) return '批准，仅更新物料清单';
  if (selectedCount.value === 0) return `确认全部驳回（${rejectedCount.value} 个）`;
  return `本级同意 ${selectedCount.value} 个，驳回 ${rejectedCount.value} 个`;
});

function objectRowId(params: GetRowIdParams<ApprovalRuntimeObject>) { return params.data.key; }
function objectSelectionChanged(event: SelectionChangedEvent<ApprovalRuntimeObject>) {
  selectedObjectKeys.value = event.api.getSelectedRows().filter(object => object.status === 'PENDING').map(object => object.key);
}

function setLoading(value: boolean) { loading.value = value; emit('busy', value); }
function defaultValue(parameter: ApprovalRuntimeParameter) {
  const value = parameter.defaultValue;
  if (parameter.type === 'NUMBER') return value == null || value === '' ? null : Number(value);
  if (parameter.type === 'BOOLEAN') return value === true || value === 'true';
  if (parameter.type === 'DATE') return value == null || value === '' ? null : String(value);
  return value == null ? '' : String(value);
}

async function open(requestPayload: ApprovalRuntimePayload, decision: Decision, comment = ''): Promise<boolean> {
  if (loading.value) return false;
  action.value = decision;
  payload.value = { ...requestPayload, comment };
  errorText.value = '';
  uncertain.value = false;
  decisionMode.value = 'WHOLE';
  allowSourceOnlyApproval.value = false;
  objects.value = [];
  selectedObjectKeys.value = [];
  objectColumnDefinitions.value = [];
  approvalParameters.value = [];
  rejectionParameters.value = [];
  setLoading(true);
  try {
    const { data, error } = await fetchApprovalActionConfig({
      pageCode: requestPayload.pageCode, tableCode: requestPayload.tableCode,
      billId: requestPayload.billId, action: decision
    });
    if (error) throw error;
    if (!data) throw new Error('审批参数接口未返回结果，未提交审批');
    decisionMode.value = data.decisionMode || 'WHOLE';
    allowSourceOnlyApproval.value = data.allowSourceOnlyApproval === true;
    if (selectsObjects.value) {
      if (!Array.isArray(data.objects)) throw new Error('审批对象接口未返回对象列表，未提交审批');
      const objectKeys = data.objects.map(object => object.key);
      if (objectKeys.some(key => !key) || new Set(objectKeys).size !== objectKeys.length) {
        throw new Error('审批对象标识为空或重复，请核对审批配置和服务端对象快照');
      }
      objects.value = data.objects;
      objectColumnDefinitions.value = data.objectColumns || [];
    }
    approvalParameters.value = data.enabled && data.mode === 'MANUAL' && Array.isArray(data.params) ? data.params : [];
    rejectionParameters.value = selectsObjects.value && !allowSourceOnlyApproval.value
      && Array.isArray(data.rejectionParams) ? data.rejectionParams : [];
    for (const definitions of [approvalParameters.value, rejectionParameters.value]) {
      const names = definitions.map(parameter => parameter.name);
      if (names.some(name => !name) || new Set(names).size !== names.length) {
        throw new Error('审批动作参数名称为空或重复，请先修正流程配置');
      }
    }
    values.value = Object.fromEntries([...approvalParameters.value, ...rejectionParameters.value]
      .map(parameter => [parameter.name, defaultValue(parameter)]));
    if (parameters.value.length || selectsObjects.value) { visible.value = true; return true; }
  } catch (error) {
    message.error(errorMessage(error));
    return false;
  } finally { setLoading(false); }
  return submit();
}

async function submit(): Promise<boolean> {
  if (!payload.value || loading.value || uncertain.value) return false;
  if (missingRequiredObjects.value) {
    message.warning('当前没有待审批对象，请刷新审批进度');
    return false;
  }
  const missing = parameters.value.find(parameter => {
    const value = values.value[parameter.name];
    return parameter.required && (value == null || (typeof value === 'string' && !value.trim()));
  });
  if (missing) { message.warning(`请填写${missing.label || missing.name}`); return false; }
  setLoading(true);
  errorText.value = '';
  try {
    const requestPayload: ApprovalRuntimePayload = {
      ...payload.value,
      actionParams: Object.fromEntries(parameters.value.map(parameter => [parameter.name, values.value[parameter.name]]))
    };
    if (selectsObjects.value) {
      requestPayload.selectedObjectKeys = action.value === 'approve' ? [...selectedObjectKeys.value] : [];
    }
    const result = action.value === 'approve' ? await approveApproval(requestPayload) : await rejectApproval(requestPayload);
    if (result.error) {
      const error = result.error as { response?: { data?: { code?: unknown; msg?: unknown } } };
      const response = error.response?.data;
      uncertain.value = !(response?.code != null && typeof response.msg === 'string');
      errorText.value = `${errorMessage(result.error)}${uncertain.value ? '；请求结果未确认，请先查看审批进度，勿重复提交。' : ''}`;
      visible.value = true;
      return false;
    }
    if (!result.data) {
      uncertain.value = true;
      errorText.value = '审批接口未返回结果，请先查看审批进度，勿重复提交。';
      visible.value = true;
      return false;
    }
    visible.value = false;
    message.success(result.data?.message || (selectsObjects.value ? '本级审批结果已提交' : action.value === 'approve' ? '审批通过' : '已驳回'));
    emit('complete', { action: action.value, data: result.data });
    return true;
  } catch (error) {
    uncertain.value = true;
    errorText.value = `${errorMessage(error)}；请求结果未确认，请先查看审批进度，勿重复提交。`;
    visible.value = true;
    return false;
  } finally { setLoading(false); }
}
defineExpose({ open });
</script>

<template>
  <NModal v-model:show="visible" preset="card" :title="selectsObjects ? '审批对象' : '审批动作参数'" :style="{ width: selectsObjects ? 'min(1040px, 94vw)' : 'min(560px, 94vw)' }" :mask-closable="!loading" :close-on-esc="!loading" :closable="!loading">
    <NSpace vertical :size="12">
      <NAlert v-if="errorText" type="error" :bordered="false">{{ errorText }}</NAlert>
      <template v-if="selectsObjects">
        <NAlert :type="action === 'reject' || (selectedCount === 0 && !allowSourceOnlyApproval) ? 'warning' : 'info'" :bordered="false">
          <template v-if="action === 'approve'">
            本级待审批 {{ pendingObjects.length }} 个，已勾选同意 {{ selectedCount }} 个，未选将驳回 {{ rejectedCount }} 个。
            <template v-if="allowSourceOnlyApproval">默认不勾选；不选择任何对象仍可批准物料清单改价，成本核算不变。</template>
            <template v-else>默认不勾选；不选择任何对象表示全部驳回。</template>
            各级勾选仅表示本级同意，最终通过后才生效。
            <template v-if="!allowSourceOnlyApproval">至少一个对象最终通过，源价格才会生效。</template>
          </template>
          <template v-else>本次将驳回整个审批，源单据及关联单据均不应用本次待批变更。</template>
        </NAlert>
        <div :inert="loading || uncertain">
          <AgGridVue
            class="ag-theme-quartz approval-object-grid"
            theme="legacy"
            :row-data="objects"
            :column-defs="objectColumns"
            :default-col-def="{ editable: false, sortable: true, resizable: true, filter: 'agTextColumnFilter' }"
            :row-selection="action === 'approve' ? objectSelection : undefined"
            :selection-column-def="{ width: 36, minWidth: 36, maxWidth: 36 }"
            :get-row-id="objectRowId"
            :row-height="28"
            :header-height="28"
            :locale-text="{ noRowsToShow: '暂无审批对象', selectAll: '选择全部待审批对象' }"
            :animate-rows="false"
            @selection-changed="objectSelectionChanged"
          />
        </div>
      </template>
      <NForm v-if="parameters.length" label-placement="top" size="small">
        <NFormItem v-for="parameter in parameters" :key="parameter.name" :label="parameter.label || parameter.name" :required="parameter.required">
          <NInputNumber v-if="parameter.type === 'NUMBER'" v-model:value="values[parameter.name]" clearable :disabled="loading" style="width: 100%" />
          <NSwitch v-else-if="parameter.type === 'BOOLEAN'" v-model:value="values[parameter.name]" :disabled="loading" />
          <NDatePicker v-else-if="parameter.type === 'DATE'" v-model:formatted-value="values[parameter.name]" type="date" value-format="yyyy-MM-dd" clearable :disabled="loading" style="width: 100%" />
          <NInput v-else v-model:value="values[parameter.name]" :type="parameter.type === 'TEXTAREA' ? 'textarea' : 'text'" :placeholder="parameter.label || parameter.name" :disabled="loading" />
        </NFormItem>
      </NForm>
      <NSpace justify="end">
        <NButton :disabled="loading" @click="visible = false">关闭</NButton>
        <NButton type="primary" :loading="loading" :disabled="uncertain || missingRequiredObjects" @click="submit">{{ submitLabel }}</NButton>
      </NSpace>
    </NSpace>
  </NModal>
</template>

<style scoped>
.approval-object-grid {
  height: 320px;
  width: 100%;
  --ag-font-size: 13px;
  --ag-font-family: inherit;
  --ag-row-height: 28px;
  --ag-header-height: 28px;
  --ag-wrapper-border-radius: 0;
}
</style>
