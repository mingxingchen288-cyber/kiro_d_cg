<script setup lang="ts">
/**
 * 配置按钮权限（1000px，C06 v24 第 8 节）："全部按钮"（`["*"]`），否则依次勾选：
 * - 页面：保存、高级查询；
 * - 新增、删除、修改：一行一个区域（主表、各明细，标题取页面配置），用户 2026-10-30"控制到明细级别"；
 * - 其余区域按钮（复制、由BOM生成明细、保存列配置等，分组显示区域标题）和导出，同旧系统按钮分组。
 */
import { computed, ref } from 'vue';
import { NButton, NCheckbox, NForm, NFormItem, NInput, NModal } from 'naive-ui';
import type { PageContent } from '../core/types';
import { PAGE_BUTTONS, areaPermissionRows, buttonGroups } from './role-model';

const props = defineProps<{ pageTitle: string; page: PageContent; exports: Array<{ key: string; name: string }>; value: string[] }>();
const emit = defineEmits<{ close: []; save: [buttons: string[]] }>();
const all = ref(props.value.includes('*'));
const chosen = ref<string[]>(props.value.filter(v => v !== '*'));
const areas = computed(() => areaPermissionRows(props.page));
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
            <div class="button-group">
              <div class="button-group-title">页面</div>
              <div class="button-group-items">
                <NCheckbox v-for="btn in PAGE_BUTTONS" :key="btn.key" :checked="chosen.includes(btn.key)" @update:checked="(c: boolean) => toggle(btn.key, c)">{{ btn.label }}</NCheckbox>
              </div>
            </div>
            <div class="button-group">
              <div class="button-group-title">新增、删除、修改（没有"修改"时这个区域已保存的行都不能改，新增的行照常填写）</div>
              <table class="area-table">
                <tbody>
                  <tr v-for="row in areas" :key="row.area" :data-area="row.area">
                    <td class="area-title">{{ row.title }}</td>
                    <td v-for="choice in row.choices" :key="choice.key">
                      <NCheckbox :checked="chosen.includes(choice.key)" @update:checked="(c: boolean) => toggle(choice.key, c)">{{ choice.label }}</NCheckbox>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
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
.area-table { border-collapse: collapse; }
.area-table td { padding: 2px 16px 2px 0; }
.area-table .area-title { min-width: 90px; color: #333; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
