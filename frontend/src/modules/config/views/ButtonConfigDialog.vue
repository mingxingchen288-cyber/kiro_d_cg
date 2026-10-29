<script setup lang="ts">
/**
 * 区域按钮，同旧系统 ButtonConfigDialog.vue（720px，"按钮配置 - 区域"）：每个按钮一张卡片，动作（内置或输入业务动作）、
 * 显示名称；业务动作选引用的操作并写"需选行"（C06 第 3 节：业务动作必须写 operation 和 requiresSelection，内置动作都不写）。
 * 保存、高级查询是页面级按钮，不写在区域里。旧系统按钮里的存储过程、SQL、Java 方法在新平台是操作库中的操作（OperationDialog）。
 */
import { onMounted, ref } from 'vue';
import { NButton, NCard, NInput, NModal, NSelect, NSpace, NSwitch, NTag } from 'naive-ui';
import { useConfigContext } from '../core/context';
import type { ItemEditor } from '../core/item-editor';
import type { ButtonConfig, PageArea } from '../core/types';
import ProblemList from '../components/ProblemList.vue';

const props = defineProps<{ show: boolean; page: ItemEditor<'page'>; area: PageArea; title: string }>();
const emit = defineEmits<{ 'update:show': [show: boolean] }>();
const { store } = useConfigContext();
const BUILTIN = ['addRow', 'copyRow', 'deleteRow', 'saveGridConfig'];
const actionOptions = [
  { label: '新增 (addRow)', value: 'addRow' },
  { label: '复制 (copyRow)', value: 'copyRow' },
  { label: '删除 (deleteRow)', value: 'deleteRow' },
  { label: '保存列配置 (saveGridConfig)', value: 'saveGridConfig' }
];
const buttons = ref<ButtonConfig[]>(JSON.parse(JSON.stringify(props.area.buttons ?? [])));
const operations = ref<Array<{ label: string; value: string }>>([]);
const isBuiltin = (b: ButtonConfig) => BUILTIN.includes(b.action);

function actionChanged(b: ButtonConfig) {
  if (isBuiltin(b)) {
    delete b.operation;
    delete b.requiresSelection;
    b.label ||= actionOptions.find(o => o.value === b.action)?.label.split(' ')[0] ?? b.action;
  } else b.requiresSelection ??= true;
}

async function save() {
  props.area.buttons = buttons.value.map(b =>
    isBuiltin(b) ? { action: b.action, label: b.label } : { action: b.action, label: b.label, operation: b.operation ?? null, requiresSelection: Boolean(b.requiresSelection) }
  );
  props.page.markDirty();
  if ((await props.page.save()) !== null) emit('update:show', false);
}

onMounted(async () => {
  operations.value = (await store.list('operation')).map(o => ({ label: `${o.name} · ${o.key}`, value: o.key }));
});
</script>

<template>
  <NModal :show="show" preset="card" :title="`按钮配置 - ${title}`" style="width: 720px; max-height: 90vh" :segmented="{ content: true, footer: true }" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="10" class="body">
      <NCard v-for="(btn, i) in buttons" :key="i" size="small">
        <NSpace align="center" :wrap="true">
          <NTag size="small" :type="isBuiltin(btn) ? 'info' : 'warning'">{{ isBuiltin(btn) ? '内置' : '业务动作' }}</NTag>
          <NSelect v-model:value="btn.action" :options="actionOptions" filterable tag placeholder="选择或输入自定义action" style="width: 220px" @update:value="actionChanged(btn)" />
          <NInput v-model:value="btn.label" placeholder="显示名称" style="width: 140px" />
          <template v-if="!isBuiltin(btn)">
            <NSelect v-model:value="btn.operation" :options="operations" filterable placeholder="引用的操作" style="width: 220px" />
            <span class="hint">需选行</span>
            <NSwitch :value="Boolean(btn.requiresSelection)" @update:value="v => (btn.requiresSelection = v)" />
          </template>
          <NButton text size="small" type="error" @click="buttons.splice(i, 1)">删除</NButton>
        </NSpace>
      </NCard>
      <ProblemList :problems="page.state.problems" />
    </NSpace>
    <template #footer>
      <NSpace justify="space-between" style="width: 100%">
        <NButton size="small" dashed @click="buttons.push({ action: 'addRow', label: '新增' })">+ 添加按钮</NButton>
        <NSpace>
          <NButton size="small" @click="emit('update:show', false)">取消</NButton>
          <NButton size="small" type="primary" :loading="page.state.busy" @click="save">保存</NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.body { max-height: 65vh; overflow-y: auto; }
.hint { color: #999; font-size: 12px; }
</style>
