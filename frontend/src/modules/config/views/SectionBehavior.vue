<script setup lang="ts">
/**
 * 页面行为，同旧系统 SectionBehavior.vue：每个区域（主表、各明细）一个折叠项，行依次为
 * 🔘按钮、📐计算规则、✅校验规则、🔒可编辑规则、🔒需审批的编辑字段、🎨样式规则、⚙Grid选项，每行"可视化编辑"。
 * 旧系统的"聚合规则"在 C06 中就是写在主表字段上的计算规则（`sum(map(明细, …))`），放在主表的"计算规则"里。
 * 另有"⚙操作"：本页面的操作（保存操作和按钮引用的业务操作，C06 第 4、6 节）。
 */
import { computed, ref } from 'vue';
import { NButton, NCollapse, NCollapseItem, NTag } from 'naive-ui';
import type { PageCatalog, PageTable } from '../core/catalog';
import type { ItemEditor } from '../core/item-editor';
import type { PageArea } from '../core/types';
import ApprovalRequiredDialog from '../entity/ApprovalRequiredDialog.vue';
import CellEditableDialog from '../rules/CellEditableDialog.vue';
import GridStyleDialog from '../rules/GridStyleDialog.vue';
import RuleConfigDialog from '../rules/RuleConfigDialog.vue';
import type { RuleKind } from '../rules/rule-model';
import ButtonConfigDialog from './ButtonConfigDialog.vue';
import GridOptionsDialog from './GridOptionsDialog.vue';
import OperationDialog from './OperationDialog.vue';

const props = defineProps<{ page: ItemEditor<'page'>; catalog: PageCatalog }>();
type Dialog = '' | 'BUTTON' | RuleKind | 'APPROVAL_REQUIRED' | 'GRID_OPTIONS' | 'OPERATION';
const active = ref<Dialog>('');
const activeIndex = ref(0);
const content = computed(() => props.page.state.current!.content);
const areas = computed(() => [content.value.master as PageArea, ...(content.value.details ?? [])]);
const table = computed<PageTable>(() => props.catalog.tables[activeIndex.value]);
const masterFields = computed(() => props.catalog.tables[0]?.fields.map(f => f.name) ?? []);

function open(dialog: Dialog, index: number) {
  activeIndex.value = index;
  active.value = dialog;
}

function gridSummary(area: PageArea) {
  const labels: string[] = [];
  if (area.grid.cellSelection) labels.push('范围选择');
  if (area.grid.sideBar) labels.push('侧边栏');
  if (area.grid.groupBy.length) labels.push(`分组 ${area.grid.groupBy.join('、')}`);
  return labels.join('、') || '—';
}

const rows: Array<{ kind: RuleKind | 'APPROVAL_REQUIRED'; icon: string; label: string }> = [
  { kind: 'calc', icon: '📐', label: '计算规则' },
  { kind: 'validate', icon: '✅', label: '校验规则' },
  { kind: 'editable', icon: '🔒', label: '可编辑规则' },
  { kind: 'APPROVAL_REQUIRED', icon: '🔒', label: '需审批的编辑字段' },
  { kind: 'style', icon: '🎨', label: '样式规则' }
];
</script>

<template>
  <div class="section-behavior">
    <NCollapse>
      <NCollapseItem v-for="(area, index) in areas" :key="area.entity" :title="`${index === 0 ? '主表' : '从表'}: ${catalog.tables[index]?.title ?? area.entity}`" :name="area.entity">
        <div class="behavior-block">
          <div class="behavior-row">
            <span class="row-icon">🔘</span>
            <span class="row-label">按钮</span>
            <div class="button-tags">
              <NTag v-for="btn in area.buttons ?? []" :key="btn.action" size="small" round>{{ btn.label || btn.action }}</NTag>
              <NButton size="tiny" quaternary @click="open('BUTTON', index)">+</NButton>
            </div>
          </div>
          <div v-for="row in rows" :key="row.kind" class="behavior-row">
            <span class="row-icon">{{ row.icon }}</span>
            <span class="row-label">{{ row.label }}</span>
            <span class="row-summary">{{ row.kind === 'APPROVAL_REQUIRED' ? '实体的必须审批字段规则（所有写入口都检查）' : '每条规则一个配置项' }}</span>
            <NButton size="tiny" type="primary" quaternary @click="open(row.kind, index)">可视化编辑</NButton>
          </div>
          <div class="behavior-row">
            <span class="row-icon">⚙</span>
            <span class="row-label">Grid选项</span>
            <span class="row-summary">{{ gridSummary(area) }}</span>
            <NButton size="tiny" type="primary" quaternary @click="open('GRID_OPTIONS', index)">可视化编辑</NButton>
          </div>
          <div v-if="index === 0" class="behavior-row">
            <span class="row-icon">⚙</span>
            <span class="row-label">操作</span>
            <span class="row-summary">保存操作 {{ content.saveOperation }}；按钮引用的业务操作</span>
            <NButton size="tiny" type="primary" quaternary @click="open('OPERATION', index)">可视化编辑</NButton>
          </div>
        </div>
      </NCollapseItem>
    </NCollapse>

    <ButtonConfigDialog v-if="active === 'BUTTON'" :show="true" :page="page" :area="areas[activeIndex]" :title="table.title" @update:show="active = ''" />
    <GridOptionsDialog v-if="active === 'GRID_OPTIONS'" :show="true" :page="page" :area="areas[activeIndex]" :title="table.title" :fields="table.fields" @update:show="active = ''" />
    <RuleConfigDialog v-if="active === 'calc' || active === 'validate'" :show="true" :kind="active" :page-code="page.state.current!.key" :table="table" :tables="catalog.tables" :master-fields="masterFields" @update:show="active = ''" />
    <CellEditableDialog v-if="active === 'editable'" :show="true" :page-code="page.state.current!.key" :table="table" :master-fields="masterFields" @update:show="active = ''" />
    <GridStyleDialog v-if="active === 'style'" :show="true" :page-code="page.state.current!.key" :table="table" :master-fields="masterFields" @update:show="active = ''" />
    <ApprovalRequiredDialog v-if="active === 'APPROVAL_REQUIRED'" :show="true" :table="table" @update:show="active = ''" />
    <OperationDialog v-if="active === 'OPERATION'" :show="true" :page="page" :catalog="catalog" @update:show="active = ''" />
  </div>
</template>

<style scoped>
.section-behavior { padding: 8px 0; }
.behavior-block { padding: 4px 0; }
.behavior-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f0f0f0; }
.behavior-row:last-child { border-bottom: none; }
.row-icon { font-size: 14px; width: 20px; text-align: center; }
.row-label { font-size: 13px; font-weight: 500; width: 120px; flex-shrink: 0; }
.row-summary { font-size: 12px; color: #666; flex: 1; }
.button-tags { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; max-width: calc(8 * 80px); }
</style>
