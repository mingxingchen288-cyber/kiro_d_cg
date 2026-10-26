<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  NButton,
  NDivider,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage
} from 'naive-ui';
import { savePageComponent } from '@/service/api/meta-config';

const props = defineProps<{
  show: boolean;
  componentConfig: string;
  componentKey: string;
  compRow?: any;
}>();

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void;
  (e: 'save', config: string): void;
}>();

const message = useMessage();

// ---- 按钮数据模型 ----
type ButtonItem = {
  action: string;
  label: string;
  position?: string;
  toolbarAlias?: string;
  requiresRow?: boolean;
  confirm?: string;
  // 执行方式
  execType?: 'builtin' | 'procedure' | 'sql' | 'java';
  procedure?: string;
  sql?: string;
  method?: string;
  handler?: string;
  params?: { source: string; mode: string; jdbcType: string }[];
};

// 当前编辑的按钮列表
const buttons = ref<ButtonItem[]>([]);
// 当前展开编辑的按钮索引
const expandedIndex = ref<number | null>(null);

// 当前显示的按钮列表
const currentButtons = computed(() => buttons.value);

// 内置 action 选项
const builtinActions = [
  { label: '新增 (addRow)', value: 'addRow' },
  { label: '复制 (copyRow)', value: 'copyRow' },
  { label: '删除 (deleteRow)', value: 'deleteRow' },
  { label: '保存 (save)', value: 'save' },
  { label: '保存列配置 (saveGridConfig)', value: 'saveGridConfig' },
  { label: '高级查询 (advancedSearch)', value: 'advancedSearch' }
];

const BUILTIN_ACTION_SET = new Set(builtinActions.map(a => a.value));
const REMOVED_ACTION_SET = new Set([
  'clipboard.copy',
  'clipboard_copy',
  'clipboard.paste',
  'clipboard_paste',
  'batchSelect',
  'batch_select'
]);

function getBuiltinActionOptions(currentIndex: number) {
  const currentAction = buttons.value[currentIndex]?.action || '';
  const usedActions = new Set(
    buttons.value
      .map((btn, index) => (index === currentIndex ? '' : btn.action))
      .filter(action => BUILTIN_ACTION_SET.has(action))
  );

  return builtinActions.filter(action => action.value === currentAction || !usedActions.has(action.value));
}

const positionOptions = [
  { label: '右键菜单', value: 'context' },
  { label: '工具栏', value: 'toolbar' },
  { label: '两处都显示', value: 'both' }
];

const execTypeOptions = [
  { label: '前端内置', value: 'builtin' },
  { label: '存储过程', value: 'procedure' },
  { label: 'SQL', value: 'sql' },
  { label: 'Java方法', value: 'java' }
];

const jdbcTypeOptions = [
  { label: 'NUMERIC', value: 'NUMERIC' },
  { label: 'VARCHAR', value: 'VARCHAR' },
  { label: 'DATE', value: 'DATE' },
  { label: 'TIMESTAMP', value: 'TIMESTAMP' }
];

const paramModeOptions = [
  { label: 'IN', value: 'IN' },
  { label: 'OUT', value: 'OUT' },
  { label: 'INOUT', value: 'INOUT' }
];

// ---- 解析 / 序列化 ----
function detectExecType(btn: any): 'builtin' | 'procedure' | 'sql' | 'java' {
  if (btn.sql) return 'sql';
  if (btn.handler || btn.method) return 'java';
  if (btn.procedure) return 'procedure';
  return 'builtin';
}

function getDefaultPosition(action?: string): 'context' | 'toolbar' {
  return action === 'advancedSearch' ? 'toolbar' : 'context';
}

function parseButtonFromRaw(raw: any): ButtonItem {
  return {
    action: raw.action || '',
    label: raw.label || '',
    position: raw.position || getDefaultPosition(raw.action),
    toolbarAlias: raw.toolbarAlias || '',
    requiresRow: raw.requiresRow || false,
    confirm: raw.confirm || '',
    execType: detectExecType(raw),
    procedure: raw.procedure || '',
    sql: raw.sql || '',
    method: raw.method || '',
    handler: raw.handler || '',
    params: Array.isArray(raw.params)
      ? raw.params.map((p: any) => ({
          source: p.source || '',
          mode: p.mode || 'IN',
          jdbcType: p.jdbcType || 'VARCHAR'
        }))
      : []
  };
}

function isRemovedAction(action?: unknown): boolean {
  return typeof action === 'string' && REMOVED_ACTION_SET.has(action.trim());
}

function serializeButton(btn: ButtonItem): any {
  const result: any = { action: btn.action, label: btn.label };
  if (btn.position && btn.position !== getDefaultPosition(btn.action)) result.position = btn.position;
  if (btn.toolbarAlias) result.toolbarAlias = btn.toolbarAlias;
  if (btn.requiresRow) result.requiresRow = true;
  if (btn.confirm) result.confirm = btn.confirm;
  // 执行方式
  if (btn.execType === 'procedure' && btn.procedure) {
    result.procedure = btn.procedure;
    if (btn.params && btn.params.length > 0) {
      result.params = btn.params.filter(p => p.source);
    }
  } else if (btn.execType === 'sql' && btn.sql) {
    result.sql = btn.sql;
  } else if (btn.execType === 'java') {
    if (btn.method) result.method = btn.method;
    else if (btn.handler) result.handler = btn.handler;
  }
  return result;
}

// ---- 初始化 ----
watch(
  () => props.show,
  val => {
    if (!val) return;
    expandedIndex.value = null;
    try {
      const config = props.componentConfig ? JSON.parse(props.componentConfig) : {};
      buttons.value = (config.buttons || [])
        .filter((btn: any) => !isRemovedAction(btn?.action))
        .map(parseButtonFromRaw);
    } catch {
      buttons.value = [];
    }
  },
  { immediate: true }
);

// ---- 操作 ----
function addButton() {
  const newBtn: ButtonItem = {
    action: '',
    label: '',
    position: 'context',
    requiresRow: false,
    execType: 'builtin',
    params: []
  };
  buttons.value.push(newBtn);
  expandedIndex.value = buttons.value.length - 1;
}

function removeButton(index: number) {
  buttons.value.splice(index, 1);
  if (expandedIndex.value === index) expandedIndex.value = null;
  else if (expandedIndex.value !== null && expandedIndex.value > index) expandedIndex.value -= 1;
}

function toggleExpand(index: number) {
  expandedIndex.value = expandedIndex.value === index ? null : index;
}

function moveButton(index: number, direction: -1 | 1) {
  const list = buttons.value;
  const target = index + direction;
  if (target < 0 || target >= list.length) return;
  [list[index], list[target]] = [list[target], list[index]];
  if (expandedIndex.value === index) expandedIndex.value = target;
  else if (expandedIndex.value === target) expandedIndex.value = index;
}

function addParam(btn: ButtonItem) {
  if (!btn.params) btn.params = [];
  btn.params.push({ source: '', mode: 'IN', jdbcType: 'VARCHAR' });
}

function removeParam(btn: ButtonItem, index: number) {
  btn.params?.splice(index, 1);
}

function onActionChange(btn: ButtonItem) {
  // 如果选了内置 action，自动设为前端内置
  if (BUILTIN_ACTION_SET.has(btn.action)) {
    btn.execType = 'builtin';
    btn.position = getDefaultPosition(btn.action);
    // 自动填充 label
    const found = builtinActions.find(a => a.value === btn.action);
    if (found && !btn.label) {
      btn.label = found.label.split(' (')[0];
    }
  }
}

function getExecTag(btn: ButtonItem): string {
  switch (btn.execType) {
    case 'procedure':
      return '存储过程';
    case 'sql':
      return 'SQL';
    case 'java':
      return 'Java';
    default:
      return '内置';
  }
}

function getExecTagType(btn: ButtonItem): 'default' | 'success' | 'warning' | 'info' {
  switch (btn.execType) {
    case 'procedure':
      return 'success';
    case 'sql':
      return 'warning';
    case 'java':
      return 'info';
    default:
      return 'default';
  }
}

function getPositionLabel(pos?: string): string {
  return positionOptions.find(o => o.value === pos)?.label || '右键菜单';
}

// ---- 保存 ----
async function handleSave() {
  try {
    const config = props.componentConfig ? JSON.parse(props.componentConfig) : {};
    config.buttons = buttons.value.map(serializeButton);
    const configJson = JSON.stringify(config);
    if (props.compRow) {
      await savePageComponent({ ...props.compRow, componentConfig: configJson });
      message.success('按钮配置已保存');
    }
    emit('save', configJson);
    emit('update:show', false);
  } catch (e) {
    message.error(`保存失败: ${e}`);
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="`按钮配置 - ${componentKey}`"
    style="width: 720px; max-height: 90vh"
    :mask-closable="true"
    :segmented="{ content: true, footer: true }"
    @update:show="v => emit('update:show', v)"
  >
    <!-- 按钮列表 -->
    <div class="button-list" style="max-height: 70vh; overflow-y: auto">
      <NEmpty v-if="currentButtons.length === 0" description="暂无按钮配置" />

      <div
        v-for="(btn, index) in currentButtons"
        :key="index"
        class="button-card"
        :class="{ expanded: expandedIndex === index }"
      >
        <!-- 摘要行 -->
        <div class="button-summary" @click="toggleExpand(index)">
          <div class="summary-left">
            <span class="btn-index">#{{ index + 1 }}</span>
            <span class="btn-label">{{ btn.label || '(未命名)' }}</span>
            <NTag size="small" :type="getExecTagType(btn)">{{ getExecTag(btn) }}</NTag>
            <NTag size="small">{{ getPositionLabel(btn.position) }}</NTag>
            <NTag v-if="btn.requiresRow" size="small" type="warning">需选行</NTag>
          </div>
          <div class="summary-right">
            <NButton text size="small" :disabled="index === 0" @click.stop="moveButton(index, -1)">↑</NButton>
            <NButton
              text
              size="small"
              :disabled="index === currentButtons.length - 1"
              @click.stop="moveButton(index, 1)"
            >
              ↓
            </NButton>
            <NPopconfirm @positive-click="removeButton(index)">
              <template #trigger>
                <NButton text size="small" type="error" @click.stop>删除</NButton>
              </template>
              确定删除此按钮？
            </NPopconfirm>
          </div>
        </div>

        <!-- 展开编辑 -->
        <div v-if="expandedIndex === index" class="button-detail">
          <NForm label-placement="left" label-width="90" size="small">
            <div class="form-row">
              <NFormItem label="Action" class="form-item-half">
                <NSelect
                  v-model:value="btn.action"
                  :options="getBuiltinActionOptions(index)"
                  filterable
                  tag
                  placeholder="选择或输入自定义action"
                  @update:value="onActionChange(btn)"
                />
              </NFormItem>
              <NFormItem label="按钮名称" class="form-item-half">
                <NInput v-model:value="btn.label" placeholder="显示名称" />
              </NFormItem>
            </div>

            <div class="form-row">
              <NFormItem label="显示位置" class="form-item-half">
                <NSelect v-model:value="btn.position" :options="positionOptions" />
              </NFormItem>
              <NFormItem label="需要选行" class="form-item-quarter">
                <NSwitch v-model:value="btn.requiresRow" />
              </NFormItem>
            </div>

            <div v-if="btn.position === 'toolbar' || btn.position === 'both'" class="form-row">
              <NFormItem label="工具栏别名" class="form-item-half">
                <NInput v-model:value="btn.toolbarAlias" placeholder="下拉菜单中显示的名称" />
              </NFormItem>
              <NFormItem label="确认提示" class="form-item-half">
                <NInput v-model:value="btn.confirm" placeholder="留空则不弹确认框" />
              </NFormItem>
            </div>

            <NDivider style="margin: 8px 0">执行方式</NDivider>

            <NFormItem label="执行方式">
              <NSelect v-model:value="btn.execType" :options="execTypeOptions" style="width: 200px" />
            </NFormItem>

            <!-- 存储过程 -->
            <template v-if="btn.execType === 'procedure'">
              <NFormItem label="存储过程">
                <NInput v-model:value="btn.procedure" placeholder="如 P_COST_BOM_INSERT" />
              </NFormItem>
              <NFormItem label="参数">
                <div class="params-section">
                  <div v-for="(param, pi) in btn.params" :key="pi" class="param-row">
                    <NInput v-model:value="param.source" placeholder="来源 (如 data.id)" style="flex: 2" size="small" />
                    <NSelect v-model:value="param.mode" :options="paramModeOptions" style="width: 80px" size="small" />
                    <NSelect
                      v-model:value="param.jdbcType"
                      :options="jdbcTypeOptions"
                      style="width: 110px"
                      size="small"
                    />
                    <NButton text size="small" type="error" @click="removeParam(btn, pi)">×</NButton>
                  </div>
                  <NButton size="tiny" dashed @click="addParam(btn)">+ 添加参数</NButton>
                </div>
              </NFormItem>
            </template>

            <!-- SQL -->
            <template v-if="btn.execType === 'sql'">
              <NFormItem label="SQL语句">
                <NInput
                  v-model:value="btn.sql"
                  type="textarea"
                  :rows="3"
                  placeholder="如 UPDATE T_XX SET STATUS=1 WHERE ID=:id"
                />
              </NFormItem>
            </template>

            <!-- Java -->
            <template v-if="btn.execType === 'java'">
              <NFormItem label="方法">
                <NInput v-model:value="btn.method" placeholder="如 costService.recalculate" />
              </NFormItem>
            </template>
          </NForm>
        </div>
      </div>
    </div>

    <template #footer>
      <NSpace justify="space-between" style="width: 100%">
        <NButton size="small" dashed @click="addButton">+ 添加按钮</NButton>
        <NSpace size="small">
          <NButton size="small" @click="emit('update:show', false)">取消</NButton>
          <NButton size="small" type="primary" @click="handleSave">保存</NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.tab-switcher {
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e8e8e8;
}

.button-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.button-card {
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  overflow: visible;
  transition: border-color 0.2s;
}

.button-card:hover {
  border-color: #b3d8ff;
}

.button-card.expanded {
  border-color: #409eff;
}

.button-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  background: #fafafa;
  transition: background 0.2s;
}

.button-summary:hover {
  background: #f0f7ff;
}

.summary-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-index {
  color: #999;
  font-size: 12px;
  min-width: 24px;
}

.btn-label {
  font-weight: 500;
  font-size: 13px;
}

.button-detail {
  padding: 12px 16px;
  border-top: 1px solid #e8e8e8;
  background: #fff;
}

.form-row {
  display: flex;
  gap: 12px;
}

.form-item-half {
  flex: 1;
}

.form-item-quarter {
  flex: 0 0 120px;
}

.params-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.param-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
