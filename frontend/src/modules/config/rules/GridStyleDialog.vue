<script setup lang="ts">
/**
 * 样式规则，同旧系统 GridStyleDialog.vue（720px，"Grid 样式规则 - 区域"）：条件、作用范围（整行 / 指定单元格）、
 * 目标字段、背景色、字体颜色、加粗、斜体。保存为 `ui` 规则的 `effect.rowStyle` 或 `effect.cellStyle`（C06 第 5 节）。
 */
import { computed } from 'vue';
import { NButton, NColorPicker, NEmpty, NInput, NModal, NPopconfirm, NSelect, NSpace, NTag } from 'naive-ui';
import type { PageTable } from '../core/catalog';
import { useConfigContext } from '../core/context';
import type { CellStyle } from '../core/types';
import ProblemList from '../components/ProblemList.vue';
import { type RuleCard, RuleEditor } from './rule-editor';
import { isVisual, newVisual } from './rule-model';
import VisualConditionEditor from './VisualConditionEditor.vue';

const props = defineProps<{ show: boolean; pageCode: string; table: PageTable; masterFields: string[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean] }>();
const { store, notify } = useConfigContext();
const editor = new RuleEditor(store, { pageCode: props.pageCode, table: props.table }, 'style', props.masterFields, notify);
const state = editor.state;
const rowFields = computed(() => props.table.fields.map(f => ({ label: `${f.label} · ${f.name}`, value: f.name })));
const masterOptions = computed(() => props.masterFields.map(f => ({ label: f, value: f })));

function style(card: RuleCard): CellStyle {
  const effect = (card.content.effect ??= {});
  if (card.content.field) return (effect.cellStyle ??= {});
  return (effect.rowStyle ??= {});
}
function setScope(card: RuleCard, scope: 'row' | 'cell') {
  const current = { ...style(card) };
  card.content.field = scope === 'row' ? null : rowFields.value[0]?.value ?? null;
  card.content.effect = scope === 'row' ? { rowStyle: current } : { cellStyle: current };
  card.dirty = true;
}
function setStyle(card: RuleCard, key: keyof CellStyle, value: string | null) {
  const s = style(card);
  if (value) s[key] = value;
  else delete s[key];
  card.dirty = true;
}
function add() {
  const card = editor.add(null);
  card.content.when = newVisual();
}
async function save() {
  if (await editor.save()) emit('update:show', false);
}

editor.load();
</script>

<template>
  <NModal :show="show" preset="card" :title="`Grid 样式规则 - ${table.title}`" style="width: 720px; max-height: 80vh" :segmented="{ content: true, footer: true }" @update:show="emit('update:show', $event)">
    <div class="rules-area" style="max-height: 60vh">
      <NEmpty v-if="!state.loading && !state.cards.length" description="暂无样式规则" />
      <div v-for="(card, idx) in state.cards" :key="card._id" class="rule-card">
        <div class="rule-header">
          <NTag size="small" type="info">样式</NTag>
          <span class="rule-index">#{{ idx + 1 }}</span>
          <NInput v-model:value="card.key" size="tiny" :disabled="card.version !== null" style="width: 220px" @update:value="card.dirty = true" />
          <div class="spacer" />
          <NPopconfirm @positive-click="editor.remove(card)">
            <template #trigger><NButton size="tiny" quaternary type="error">删除</NButton></template>
            确定删除？
          </NPopconfirm>
        </div>
        <VisualConditionEditor v-if="isVisual(card.content.when)" :value="card.content.when" :row-fields="rowFields" :master-fields="masterOptions" @change="card.dirty = true" />
        <NInput v-else :value="String(card.content.when ?? '')" type="textarea" placeholder="条件表达式" @update:value="v => ((card.content.when = v), (card.dirty = true))" />
        <div class="rule-row">
          <div class="rule-field">
            <span class="field-label">作用范围</span>
            <NSelect :value="card.content.field ? 'cell' : 'row'" :options="[{ label: '整行', value: 'row' }, { label: '指定单元格', value: 'cell' }]" size="small" style="width: 130px" @update:value="v => setScope(card, v)" />
          </div>
          <div v-if="card.content.field" class="rule-field">
            <span class="field-label">目标字段</span>
            <NSelect v-model:value="card.content.field" :options="rowFields" filterable size="small" style="width: 180px" @update:value="card.dirty = true" />
          </div>
          <div class="rule-field">
            <span class="field-label">背景色</span>
            <NColorPicker :value="style(card).backgroundColor ?? null" size="small" :show-alpha="false" style="width: 120px" @update:value="v => setStyle(card, 'backgroundColor', v)" />
          </div>
          <div class="rule-field">
            <span class="field-label">字体颜色</span>
            <NColorPicker :value="style(card).color ?? null" size="small" :show-alpha="false" style="width: 120px" @update:value="v => setStyle(card, 'color', v)" />
          </div>
          <div class="rule-field">
            <span class="field-label">加粗</span>
            <NSelect :value="style(card).fontWeight ?? null" clearable placeholder="默认" :options="[{ label: '加粗', value: 'bold' }, { label: '正常', value: 'normal' }]" size="small" style="width: 90px" @update:value="v => setStyle(card, 'fontWeight', v)" />
          </div>
          <div class="rule-field">
            <span class="field-label">斜体</span>
            <NSelect :value="style(card).fontStyle ?? null" clearable placeholder="默认" :options="[{ label: '斜体', value: 'italic' }, { label: '正常', value: 'normal' }]" size="small" style="width: 90px" @update:value="v => setStyle(card, 'fontStyle', v)" />
          </div>
        </div>
        <ProblemList :problems="card.problems" />
      </div>
    </div>
    <template #footer>
      <NSpace justify="space-between" size="small">
        <NButton size="small" @click="add">+ 添加规则</NButton>
        <NSpace size="small">
          <NButton size="small" @click="emit('update:show', false)">取消</NButton>
          <NButton size="small" type="primary" :loading="state.busy" @click="save">保存</NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped src="./rule-dialog.css"></style>
