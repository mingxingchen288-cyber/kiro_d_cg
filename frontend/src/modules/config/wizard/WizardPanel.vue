<script setup lang="ts">
/**
 * 新建页面向导（FC-07），同旧系统 WizardPanel.vue：NSteps"页面菜单 / 导入表与配置字段 / 确认生成"，上一步、下一步。
 * 审计默认开启、明细显示方式默认多 Tab，由管理员确认或修改后随生成请求提交；单表页不显示明细显示方式，按预填值提交。
 * 写入表的序列不存在时提示先建序列，不能继续。生成调用 `POST /api/config/wizard/generate`（config CF-14）。
 */
import { computed, onMounted, ref } from 'vue';
import { NAlert, NButton, NForm, NFormItem, NInput, NRadio, NRadioGroup, NSelect, NSpace, NStep, NSteps, NSwitch, NTag } from 'naive-ui';
import { useConfigContext } from '../core/context';
import ProblemList from '../components/ProblemList.vue';
import { type MenuGroupOption, WizardState, menuGroups } from './wizard-state';
import WizardTableForm from './WizardTableForm.vue';

const props = defineProps<{ defaultParent: string }>();
const emit = defineEmits<{ success: [] }>();
const { api, store, notify } = useConfigContext();
const wizard = new WizardState(api, store);
const state = wizard.state;
const groups = ref<MenuGroupOption[]>([]);
const request = computed(() => (state.step === 3 ? wizard.request() : null));

async function generate() {
  if (await wizard.generate()) {
    notify.success(`页面 ${state.pageCode} 已生成：实体、页面、保存操作、菜单项和 ADMIN 角色权限`);
    emit('success');
  }
}

onMounted(async () => {
  groups.value = menuGroups(await store.loadAll('menu'));
  state.parentMenu = props.defaultParent || groups.value[0]?.value || '';
});
</script>

<template>
  <div class="wizard-panel">
    <NSteps :current="state.step" class="wizard-steps">
      <NStep title="页面菜单" />
      <NStep title="导入表与配置字段" />
      <NStep title="确认生成" />
    </NSteps>
    <div class="wizard-content">
      <NForm v-if="state.step === 1" label-placement="left" label-width="100px">
        <NFormItem label="归属菜单" required>
          <NSelect v-model:value="state.parentMenu" :options="groups" placeholder="选择归属菜单" />
        </NFormItem>
        <NFormItem label="页面名称" required>
          <NInput v-model:value="state.title" placeholder="请输入页面名称" maxlength="128" clearable />
        </NFormItem>
        <NFormItem label="页面编码" required>
          <NInput :value="state.pageCode" placeholder="只允许大写字母、数字、下划线，例如 GOODS_PRICE_MANAGE" @update:value="v => wizard.setPageCode(v)" />
        </NFormItem>
      </NForm>

      <template v-else-if="state.step === 2">
        <NForm inline label-placement="left" size="small">
          <NFormItem label="页面模式">
            <NRadioGroup :value="state.layout" @update:value="v => wizard.setLayout(v)">
              <NRadio value="single">单表</NRadio>
              <NRadio value="masterDetail">主从</NRadio>
            </NRadioGroup>
          </NFormItem>
          <NFormItem label="记录审计"><NSwitch v-model:value="state.audit" /></NFormItem>
          <NFormItem v-if="state.layout === 'masterDetail'" label="明细显示方式">
            <NSelect v-model:value="state.detailMode" :options="[{ label: '多 Tab', value: 'tabs' }, { label: '上下排列', value: 'stack' }]" style="width: 120px" />
          </NFormItem>
        </NForm>
        <h4 class="section-title">主表</h4>
        <WizardTableForm :wizard="wizard" :table="state.master" :detail="false" />
        <template v-if="state.layout === 'masterDetail'">
          <div v-for="(detail, idx) in state.details" :key="idx" class="detail-block">
            <NSpace justify="space-between" align="center">
              <h4 class="section-title">从表 {{ idx + 1 }}</h4>
              <NButton size="tiny" type="error" quaternary @click="wizard.removeDetail(idx)">移除</NButton>
            </NSpace>
            <WizardTableForm :wizard="wizard" :table="detail" :detail="true" />
          </div>
          <NButton size="small" dashed class="mt-8" @click="wizard.addDetail()">+ 添加明细表</NButton>
        </template>
      </template>

      <div v-else-if="request" class="manifest">
        <h3 class="manifest-title">生成清单</h3>
        <p>📋 实体 ({{ 1 + request.details.length }} 项)：<NTag size="small" type="info">主表</NTag> {{ request.master.entity }}（{{ request.master.table }}）<template v-for="d in request.details" :key="String(d.entity)"> · <NTag size="small" type="warning">从表</NTag> {{ d.entity }}（关联 {{ d.parentKey }}）</template></p>
        <p>🧩 页面：{{ request.pageCode }} · {{ request.title }} · {{ request.layout === 'single' ? '单表' : '主从' }}<template v-if="request.layout === 'masterDetail'"> · 明细{{ request.detailMode === 'tabs' ? '多 Tab' : '上下排列' }}</template> · 审计{{ request.audit ? '开启' : '关闭' }}</p>
        <p>💾 保存操作：{{ request.pageCode }}.save</p>
        <p>📁 菜单：挂在 {{ groups.find(g => g.value === request!.parentMenu)?.label ?? request.parentMenu }} 下</p>
        <p>🔒 ADMIN 角色：这个页面的全部按钮权限</p>
        <p>🔘 按钮：主表 新增、删除、保存列配置；明细 明细新增、明细删除、保存列配置</p>
        <NButton type="primary" :loading="state.busy" @click="generate">生成</NButton>
      </div>
      <NAlert v-if="state.errors.length" type="warning" :bordered="false" class="mt-8"><div v-for="(e, i) in state.errors" :key="i">{{ e }}</div></NAlert>
      <ProblemList :problems="state.problems" />
    </div>
    <div class="wizard-nav">
      <NSpace>
        <NButton v-if="state.step > 1" @click="wizard.prev()">上一步</NButton>
        <NButton v-if="state.step < 3" type="primary" @click="wizard.next()">下一步</NButton>
      </NSpace>
    </div>
  </div>
</template>

<style scoped>
.wizard-panel { height: 100%; display: flex; flex-direction: column; padding: 16px 0; }
.wizard-steps { flex-shrink: 0; margin-bottom: 24px; max-width: 600px; }
.wizard-content { flex: 1; overflow-y: auto; min-height: 0; }
.wizard-nav { flex-shrink: 0; padding-top: 12px; display: flex; justify-content: flex-end; }
.section-title { margin: 12px 0 8px; font-size: 14px; }
.detail-block { border-top: 1px dashed #e8e8e8; margin-top: 12px; }
.manifest p { margin: 6px 0; }
.manifest-title { margin: 0 0 12px; }
</style>
