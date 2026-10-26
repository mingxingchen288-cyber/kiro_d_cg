<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { NButton, NForm, NFormItem, NInput, NSelect, NSpace, useMessage } from 'naive-ui';
import { saveResource } from '@/service/api/meta-config';

const props = defineProps<{
  resource: any;
}>();

const emit = defineEmits<{
  (e: 'refresh'): void;
}>();

const message = useMessage();
const saving = ref(false);

const form = reactive({
  resourceName: props.resource.resourceName || '',
  icon: props.resource.icon || '',
  sortOrder: props.resource.sortOrder ?? 0
});

// 路由自动生成（不让用户编辑）
const autoRoute = computed(() => {
  const pageCode = props.resource.pageCode;
  if (!pageCode) return '';
  // 按父级目录生成路由：/dynamic/{pageCode}
  // 如果有父级且父级有路由前缀，则拼上
  return `/dynamic/${pageCode}`;
});

// 常用图标选项
const iconOptions = [
  { label: '📁 文件夹', value: 'mdi:folder' },
  { label: '📄 文件', value: 'mdi:file-document' },
  { label: '📊 图表', value: 'mdi:chart-bar' },
  { label: '🧮 计算器', value: 'mdi:calculator-variant' },
  { label: '📦 包裹', value: 'mdi:package-variant' },
  { label: '🚚 运输', value: 'mdi:truck-delivery' },
  { label: '💰 货币', value: 'mdi:currency-usd' },
  { label: '👥 用户', value: 'mdi:account-group' },
  { label: '🔒 锁', value: 'mdi:lock' },
  { label: '⚙ 设置', value: 'mdi:cog' },
  { label: '🏢 部门', value: 'mdi:office-building' },
  { label: '📋 列表', value: 'mdi:format-list-bulleted' },
  { label: '🔍 搜索', value: 'mdi:magnify' },
  { label: '📝 编辑', value: 'mdi:pencil' },
  { label: '📈 趋势', value: 'mdi:trending-up' },
  { label: '🏭 工厂', value: 'mdi:factory' },
  { label: '💊 药品', value: 'mdi:pill' },
  { label: '🧪 实验', value: 'mdi:flask' },
  { label: '📑 审批', value: 'mdi:file-check' },
  { label: '🗂 归档', value: 'mdi:archive' }
];

async function handleSave() {
  saving.value = true;
  try {
    await saveResource({
      ...props.resource,
      resourceName: form.resourceName,
      icon: form.icon,
      route: autoRoute.value,
      sortOrder: form.sortOrder
    });
    message.success('保存成功');
    emit('refresh');
  } catch (e: any) {
    message.error(e?.message || '保存失败');
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="section-basic-info">
    <NForm label-placement="left" label-width="80px" inline>
      <NFormItem label="页面名称">
        <NInput v-model:value="form.resourceName" style="width: 200px" />
      </NFormItem>
      <NFormItem label="页面编码">
        <NInput :value="resource.pageCode" disabled style="width: 200px" />
      </NFormItem>
      <NFormItem label="路由">
        <NInput :value="autoRoute" disabled style="width: 200px" />
      </NFormItem>
      <NFormItem label="图标">
        <NSelect
          v-model:value="form.icon"
          :options="iconOptions"
          filterable
          tag
          size="small"
          placeholder="选择或输入图标"
          style="width: 180px"
        />
      </NFormItem>
      <NFormItem label="排序">
        <NInput v-model:value="form.sortOrder" style="width: 80px" />
      </NFormItem>
      <NFormItem>
        <NButton type="primary" size="small" :loading="saving" @click="handleSave">保存</NButton>
      </NFormItem>
    </NForm>
  </div>
</template>

<style scoped>
.section-basic-info {
  padding: 8px 0;
}
</style>
