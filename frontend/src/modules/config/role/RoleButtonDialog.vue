<script setup lang="ts">
/** 配置按钮权限，同旧系统（1000px）："全部按钮"（`["*"]`），否则按分组勾选（页面级、各区域显示区域标题、导出） */
import { computed, ref } from 'vue';
import { NButton, NCheckbox, NForm, NFormItem, NInput, NModal } from 'naive-ui';
import type { PageContent } from '../core/types';
import { buttonGroups } from './role-model';

const props = defineProps<{ pageTitle: string; page: PageContent; exports: Array<{ key: string; name: string }>; value: string[] }>();
const emit = defineEmits<{ close: []; save: [buttons: string[]] }>();
const all = ref(props.value.includes('*'));
const chosen = ref<string[]>(props.value.filter(v => v !== '*'));
const groups = computed(() => buttonGroups(props.page, props.exports));

function toggle(key: string, checked: boolean) {
  chosen.value = checked ? [...chosen.value, key] : chosen.value.filter(k => k !== key);
}
</script>

<template>
  <NModal :show="true" preset="card" title="配置按钮权限" style="width: 1000px" @update:show="emit('close')">
    <NForm label-placement="left" label-width="70" size="small">
      <NFormItem label="页面"><NInput :value="pageTitle" disabled /></NFormItem>
      <NFormItem label="按钮权限">
        <div class="button-policy-section">
          <NCheckbox v-model:checked="all">全部按钮</NCheckbox>
          <div v-if="!all" class="button-select-list">
            <span v-if="!groups.length" class="empty-text-small">该页面暂无按钮配置</span>
            <div v-for="group in groups" :key="group.groupName" class="button-group">
              <div class="button-group-title">{{ group.groupName }}</div>
              <div class="button-group-items">
                <NCheckbox v-for="btn in group.buttons" :key="btn.key" :checked="chosen.includes(btn.key)" @update:checked="(c: boolean) => toggle(btn.key, c)">{{ btn.label }}</NCheckbox>
              </div>
            </div>
          </div>
        </div>
      </NFormItem>
    </NForm>
    <template #footer>
      <div class="modal-footer">
        <NButton size="small" @click="emit('close')">取消</NButton>
        <NButton type="primary" size="small" @click="emit('save', all ? ['*'] : chosen)">确定</NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.button-policy-section { width: 100%; }
.button-select-list { margin-top: 8px; }
.button-group { margin-bottom: 10px; }
.button-group-title { font-size: 12px; color: #666; margin-bottom: 4px; font-weight: 500; }
.button-group-items { display: flex; flex-wrap: wrap; gap: 12px; }
.empty-text-small { color: #999; font-size: 12px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
