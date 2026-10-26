<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { NButton, NCollapse, NCollapseItem, NSpace, NTag, useMessage } from 'naive-ui';
import { fetchRulesByComponent } from '@/service/api/meta-config';
import ButtonConfigDialog from '../../ButtonConfigDialog.vue';
import GridOptionsDialog from '../../GridOptionsDialog.vue';
import GridStyleDialog from '../../GridStyleDialog.vue';
import RuleConfigDialog from '../../RuleConfigDialog.vue';
import CellEditableDialog from '../../CellEditableDialog.vue';

const props = defineProps<{
  pageCode: string;
  components: any[];
}>();

const emit = defineEmits<{
  (e: 'refresh'): void;
}>();

const message = useMessage();

// 每个组件的规则数据
const rulesByComponent = ref<Record<string, any[]>>({});

// 加载规则
async function loadRules(componentKey: string) {
  try {
    const rules = await fetchRulesByComponent(props.pageCode, componentKey);
    rulesByComponent.value[componentKey] = rules || [];
  } catch {
    // ignore
  }
}

// 获取按钮列表
// 内置按钮 action（不需要在页面配置中显示）
const BUILTIN_ACTIONS = new Set([
  'addRow', 'deleteRow', 'save', 'query', 'advancedSearch',
  'copyRow', 'saveGridConfig', 'approval', 'submit'
]);

function getButtons(comp: any): any[] {
  try {
    const config = comp.componentConfig ? JSON.parse(comp.componentConfig) : {};
    let buttons: any[];
    if (config.tabs) {
      buttons = config.tabs.flatMap((t: any) => t.buttons || []);
    } else {
      buttons = config.buttons || [];
    }
    // 过滤掉内置按钮，只展示自定义按钮
    return buttons.filter((btn: any) => !BUILTIN_ACTIONS.has(btn.action));
  } catch {
    return [];
  }
}

// 规则计数
function getRuleCount(componentKey: string, ruleType: string): number {
  const rules = rulesByComponent.value[componentKey] || [];
  const rule = rules.find((r: any) => r.ruleType === ruleType);
  if (!rule || !rule.rules) return 0;
  try {
    const parsed = JSON.parse(rule.rules);
    return Array.isArray(parsed) ? parsed.length : (Object.keys(parsed).length > 0 ? 1 : 0);
  } catch {
    return rule.rules.length > 2 ? 1 : 0;
  }
}

function getRuleSummary(componentKey: string, ruleType: string): string {
  const count = getRuleCount(componentKey, ruleType);
  return count > 0 ? `${count} 条` : '0 条';
}

function getGridOptionsSummary(componentKey: string): string {
  const rules = rulesByComponent.value[componentKey] || [];
  const rule = rules.find((r: any) => r.ruleType === 'GRID_OPTIONS');
  if (!rule || !rule.rules) return '—';
  try {
    const obj = JSON.parse(rule.rules);
    const labels: string[] = [];
    if (obj.cellSelection) labels.push('范围选择');
    if (obj.sideBar) labels.push('侧边栏');
    if (obj.autoSizeColumns) labels.push('列宽自适应');
    return labels.length > 0 ? labels.join('、') : '—';
  } catch {
    return '—';
  }
}

function getLookupSummary(componentKey: string): string {
  const rules = rulesByComponent.value[componentKey] || [];
  const rule = rules.find((r: any) => r.ruleType === 'LOOKUP');
  if (!rule || !rule.rules) return '0 个';
  try {
    const arr = JSON.parse(rule.rules);
    if (!Array.isArray(arr)) return '0 个';
    return `${arr.length} 个`;
  } catch {
    return '0 个';
  }
}

// 弹窗控制
const activeDialog = ref<string>('');
const activeComp = ref<any>(null);
const activeRuleRow = ref<any>(null);
const dialogJson = ref('');

function openDialog(type: string, comp: any) {
  const rules = rulesByComponent.value[comp.componentKey] || [];
  const rule = rules.find((r: any) => r.ruleType === type);
  activeDialog.value = type;
  activeComp.value = comp;
  activeRuleRow.value = rule || { pageCode: props.pageCode, componentKey: comp.componentKey, ruleType: type, rules: '[]' };
  dialogJson.value = rule?.rules || (type === 'GRID_OPTIONS' ? '{}' : '[]');
}

function onDialogSave() {
  // 弹窗保存后刷新规则和组件
  if (activeComp.value) {
    loadRules(activeComp.value.componentKey);
  }
  // 通知父组件刷新（按钮配置修改了 componentConfig）
  emit('refresh');
  activeDialog.value = '';
}

// 展开时加载规则
function handleCollapseChange(names: string | string[] | number | number[]) {
  const expanded = Array.isArray(names) ? names : [names];
  for (const key of expanded) {
    if (typeof key === 'string' && !rulesByComponent.value[key]) {
      loadRules(key);
    }
  }
}

function getComponentLabel(comp: any): string {
  const typeMap: Record<string, string> = { GRID: '主表', DETAIL_GRID: '从表' };
  const type = typeMap[comp.componentType] || comp.componentType;
  const name = comp.refTableName || comp.refTableCode || comp.componentKey;
  return `${type}: ${name}`;
}

onMounted(() => {
  // 预加载第一个组件的规则
  if (props.components.length > 0) {
    loadRules(props.components[0].componentKey);
  }
});
</script>

<template>
  <div class="section-behavior">
    <NCollapse @update:expanded-names="handleCollapseChange">
      <NCollapseItem
        v-for="comp in components"
        :key="comp.componentKey"
        :title="getComponentLabel(comp)"
        :name="comp.componentKey"
      >
        <div class="behavior-block">
          <!-- 按钮 -->
          <div class="behavior-row">
            <span class="row-icon">🔘</span>
            <span class="row-label">按钮</span>
            <div class="button-tags">
              <NTag v-for="btn in getButtons(comp)" :key="btn.action" size="small" round>
                {{ btn.label || btn.action }}
              </NTag>
              <NButton size="tiny" quaternary @click="openDialog('BUTTON', comp)">+</NButton>
            </div>
          </div>

          <!-- 计算规则 -->
          <div class="behavior-row">
            <span class="row-icon">📐</span>
            <span class="row-label">计算规则</span>
            <span class="row-summary">{{ getRuleSummary(comp.componentKey, 'CALC') }}</span>
            <NButton size="tiny" type="primary" quaternary @click="openDialog('CALC', comp)">可视化编辑</NButton>
          </div>

          <!-- 聚合规则 -->
          <div class="behavior-row">
            <span class="row-icon">📊</span>
            <span class="row-label">聚合规则</span>
            <span class="row-summary">{{ getRuleSummary(comp.componentKey, 'AGGREGATE') }}</span>
            <NButton size="tiny" type="primary" quaternary @click="openDialog('AGGREGATE', comp)">可视化编辑</NButton>
          </div>

          <!-- 校验规则 -->
          <div class="behavior-row">
            <span class="row-icon">✅</span>
            <span class="row-label">校验规则</span>
            <span class="row-summary">{{ getRuleSummary(comp.componentKey, 'VALIDATION') }}</span>
            <NButton size="tiny" type="primary" quaternary @click="openDialog('VALIDATION', comp)">可视化编辑</NButton>
          </div>

          <!-- 可编辑规则 -->
          <div class="behavior-row">
            <span class="row-icon">🔒</span>
            <span class="row-label">可编辑规则</span>
            <span class="row-summary">{{ getRuleSummary(comp.componentKey, 'EDITABLE') }}</span>
            <NButton size="tiny" type="primary" quaternary @click="openDialog('EDITABLE', comp)">可视化编辑</NButton>
          </div>

          <!-- 需审批的编辑字段 -->
          <div class="behavior-row">
            <span class="row-icon">🔒</span>
            <span class="row-label">需审批的编辑字段</span>
            <span class="row-summary">{{ getRuleSummary(comp.componentKey, 'APPROVAL_REQUIRED') }}</span>
            <NButton size="tiny" type="primary" quaternary @click="openDialog('APPROVAL_REQUIRED', comp)">可视化编辑</NButton>
          </div>

          <!-- 样式规则 -->
          <div class="behavior-row">
            <span class="row-icon">🎨</span>
            <span class="row-label">样式规则</span>
            <span class="row-summary">{{ getRuleSummary(comp.componentKey, 'GRID_STYLE') }}</span>
            <NButton size="tiny" type="primary" quaternary @click="openDialog('GRID_STYLE', comp)">可视化编辑</NButton>
          </div>

          <!-- Grid选项 -->
          <div class="behavior-row">
            <span class="row-icon">⚙</span>
            <span class="row-label">Grid选项</span>
            <span class="row-summary">{{ getGridOptionsSummary(comp.componentKey) }}</span>
            <NButton size="tiny" type="primary" quaternary @click="openDialog('GRID_OPTIONS', comp)">可视化编辑</NButton>
          </div>
        </div>
      </NCollapseItem>
    </NCollapse>

    <!-- 弹窗 -->
    <GridOptionsDialog
      v-if="activeDialog === 'GRID_OPTIONS'"
      :show="true"
      :rules-json="dialogJson"
      :component-key="activeComp?.componentKey"
      :rule-row="activeRuleRow"
      @update:show="activeDialog = ''"
      @save="onDialogSave"
    />
    <GridStyleDialog
      v-if="activeDialog === 'GRID_STYLE'"
      :show="true"
      :rules-json="dialogJson"
      :page-code="pageCode"
      :component-key="activeComp?.componentKey"
      :rule-row="activeRuleRow"
      @update:show="activeDialog = ''"
      @save="onDialogSave"
    />
    <RuleConfigDialog
      v-if="activeDialog === 'CALC' || activeDialog === 'AGGREGATE' || activeDialog === 'VALIDATION'"
      :show="true"
      :rules-json="dialogJson"
      :rule-type="activeDialog as any"
      :page-code="pageCode"
      :component-key="activeComp?.componentKey"
      :rule-row="activeRuleRow"
      @update:show="activeDialog = ''"
      @save="onDialogSave"
    />
    <CellEditableDialog
      v-if="activeDialog === 'EDITABLE' || activeDialog === 'APPROVAL_REQUIRED'"
      :show="true"
      :rules-json="dialogJson"
      :rule-type="activeDialog"
      :page-code="pageCode"
      :component-key="activeComp?.componentKey"
      :rule-row="activeRuleRow"
      @update:show="activeDialog = ''"
      @save="onDialogSave"
    />
    <ButtonConfigDialog
      v-if="activeDialog === 'BUTTON'"
      :show="true"
      :component-config="activeComp?.componentConfig || ''"
      :component-key="activeComp?.componentKey || ''"
      :comp-row="activeComp"
      @update:show="activeDialog = ''"
      @save="onDialogSave"
    />
  </div>
</template>

<style scoped>
.section-behavior {
  padding: 8px 0;
}
.behavior-block {
  padding: 4px 0;
}
.behavior-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
}
.behavior-row:last-child {
  border-bottom: none;
}
.row-icon {
  font-size: 14px;
  width: 20px;
  text-align: center;
}
.row-label {
  font-size: 13px;
  font-weight: 500;
  width: 80px;
  flex-shrink: 0;
}
.row-summary {
  font-size: 12px;
  color: #666;
  flex: 1;
}
.button-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
  max-width: calc(8 * 80px); /* roughly 8 buttons per row */
}
</style>
