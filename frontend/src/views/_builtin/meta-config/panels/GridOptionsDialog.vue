<script setup lang="ts">
import { ref, watch } from 'vue';
import { NButton, NInput, NInputNumber, NModal, NSpace, NSwitch, useMessage } from 'naive-ui';
import { savePageRule } from '@/service/api/meta-config';

const props = defineProps<{
  show: boolean;
  rulesJson: string;
  componentKey: string;
  ruleRow?: any;
}>();

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void;
  (e: 'save', json: string): void;
}>();

const message = useMessage();

type GridOptions = {
  cellSelection?: boolean;
  sideBar?: boolean;
  autoSizeColumns?: boolean;
  autoSizeMode?: string;
  groupDefaultExpanded?: number;
  cacheBlockSize?: number;
};

const options = ref<GridOptions>({});

const optionItems = [
  { key: 'cellSelection', label: '单元格范围选择', desc: '像Excel一样框选多个单元格', type: 'switch' },
  { key: 'sideBar', label: '侧边栏', desc: '列筛选面板、列显隐控制', type: 'switch' },
  { key: 'autoSizeColumns', label: '列宽自适应', desc: '自动调整列宽', type: 'switch' }
] as const;

watch(
  () => props.show,
  val => {
    if (!val) return;
    try {
      options.value = props.rulesJson ? JSON.parse(props.rulesJson) : {};
    } catch {
      options.value = {};
    }
  },
  { immediate: true }
);

const saving = ref(false);

async function handleSave() {
  // 清理 undefined/null 值
  const cleaned: Record<string, any> = {};
  for (const [k, v] of Object.entries(options.value)) {
    if (v != null) cleaned[k] = v;
  }
  const json = JSON.stringify(cleaned);

  if (props.ruleRow) {
    saving.value = true;
    try {
      await savePageRule({ ...props.ruleRow, rules: json });
      message.success('表格选项已保存');
      emit('save', json);
      emit('update:show', false);
    } catch {
      message.error('保存失败');
    } finally {
      saving.value = false;
    }
  } else {
    emit('save', json);
    emit('update:show', false);
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="`表格选项 - ${componentKey}`"
    style="width: 460px"
    :mask-closable="true"
    :segmented="{ content: true, footer: true }"
    @update:show="v => emit('update:show', v)"
  >
    <div class="options-list">
      <div v-for="item in optionItems" :key="item.key" class="option-row">
        <div class="option-info">
          <span class="option-label">{{ item.label }}</span>
          <span class="option-desc">{{ item.desc }}</span>
        </div>
        <NSwitch v-model:value="(options as any)[item.key]" size="small" />
      </div>
    </div>

    <template #footer>
      <NSpace justify="end" size="small">
        <NButton size="small" @click="emit('update:show', false)">取消</NButton>
        <NButton size="small" type="primary" :loading="saving" @click="handleSave">保存</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.options-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.option-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 4px;
  border-bottom: 1px solid #f0f0f0;
}
.option-row:last-child {
  border-bottom: none;
}
.option-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.option-label {
  font-size: 14px;
  color: #333;
}
.option-desc {
  font-size: 12px;
  color: #999;
}
</style>
