<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { NForm, NFormItem, NInput, NTreeSelect, useMessage } from 'naive-ui';
import { fetchAllResources } from '@/service/api/meta-config';
import { generateResourceCode } from '../composables/useWizardState';
import type { WizardStep1State } from '../composables/useWizardState';

const props = defineProps<{
  step1: WizardStep1State;
}>();

const message = useMessage();
const resourceTree = ref<any[]>([]);
const loading = ref(false);

// Build tree for NTreeSelect (包含根目录选项)
function buildTree(resources: any[]) {
  const dirs = resources.filter(r => r.resourceType === 'DIRECTORY');
  const map = new Map<number, any>();
  for (const r of dirs) {
    map.set(r.id, { key: r.id, label: r.resourceName, children: [] });
  }
  const roots: any[] = [];
  for (const r of dirs) {
    const node = map.get(r.id)!;
    if (r.parentId && map.has(r.parentId)) {
      map.get(r.parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  // 包裹一个虚拟根节点，允许用户选择挂在顶层
  return [{ key: -1, label: '根目录（顶级）', children: roots }];
}

async function loadResources() {
  loading.value = true;
  try {
    const data = await fetchAllResources();
    resourceTree.value = buildTree(data);
  } catch {
    message.error('加载目录树失败');
  } finally {
    loading.value = false;
  }
}

// Auto-generate code when name changes
watch(
  () => props.step1.resourceName,
  name => {
    if (name) {
      props.step1.resourceCode = generateResourceCode(name);
    }
  }
);

// Restrict resourceCode input to valid characters
function handleCodeInput(value: string) {
  props.step1.resourceCode = value.toUpperCase().replace(/[^A-Z0-9_]/g, '').slice(0, 64);
}

onMounted(loadResources);
</script>

<template>
  <div class="wizard-step1">
    <NForm label-placement="left" label-width="100px" :show-feedback="true">
      <NFormItem
        label="归属菜单"
        :validation-status="!step1.parentId ? 'error' : undefined"
        :feedback="!step1.parentId ? '请选择归属菜单' : ''"
      >
        <NTreeSelect
          v-model:value="step1.parentId"
          :options="resourceTree"
          placeholder="选择归属菜单"
          :loading="loading"
          default-expand-all
          clearable
          style="width: 100%"
        />
      </NFormItem>
      <NFormItem
        label="页面名称"
        :validation-status="!step1.resourceName ? 'error' : undefined"
        :feedback="!step1.resourceName ? '页面名称必填' : (step1.resourceName.length > 128 ? '不能超过128字符' : '')"
      >
        <NInput v-model:value="step1.resourceName" placeholder="请输入页面名称" maxlength="128" clearable />
      </NFormItem>
      <NFormItem
        label="页面编码"
        :validation-status="step1.resourceCode && !/^[A-Z0-9_]+$/.test(step1.resourceCode) ? 'error' : undefined"
        :feedback="step1.resourceCode && !/^[A-Z0-9_]+$/.test(step1.resourceCode) ? '只允许大写字母、数字、下划线' : ''"
      >
        <NInput :value="step1.resourceCode" placeholder="自动生成，可手动修改" @input="handleCodeInput" />
      </NFormItem>
      <NFormItem label="图标">
        <NInput v-model:value="step1.icon" placeholder="folder" maxlength="64" clearable />
      </NFormItem>
    </NForm>
  </div>
</template>

<style scoped>
.wizard-step1 {
  max-width: 600px;
  padding: 16px 0;
}
</style>
