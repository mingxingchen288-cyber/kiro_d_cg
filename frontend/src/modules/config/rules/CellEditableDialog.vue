<script setup lang="ts">
/**
 * 可编辑规则，同旧系统 CellEditableDialog.vue（760px，"可编辑规则 - 区域"）：每张卡片一条 `ui` 规则——可视化条件，
 * 作用范围（整行 / 指定字段），条件成立时的效果（不可编辑、可编辑、必填）。条件也可以改写成表达式。
 * 旧系统的"启用 SQL 判断"这里不提供：页面层的界面规则只在前端预览时执行，不能用 SQL；C06 的规则也没有数据项（v27 去掉）。
 */
import { computed } from 'vue';
import { NButton, NEmpty, NInput, NInputNumber, NModal, NPopconfirm, NRadio, NRadioGroup, NSelect, NSpace, NTag } from 'naive-ui';
import type { PageTable } from '../core/catalog';
import { useConfigContext } from '../core/context';
import ProblemList from '../components/ProblemList.vue';
import { type RuleCard, RuleEditor } from './rule-editor';
import { isVisual, newVisual } from './rule-model';
import VisualConditionEditor from './VisualConditionEditor.vue';

const props = defineProps<{ show: boolean; pageCode: string; table: PageTable; masterFields: string[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean] }>();
const { store, notify } = useConfigContext();
const editor = new RuleEditor(store, { pageCode: props.pageCode, table: props.table }, 'editable', props.masterFields, notify);
const state = editor.state;
const rowFields = computed(() => props.table.fields.map(f => ({ label: `${f.label} · ${f.name}`, value: f.name })));
const masterOptions = computed(() => props.masterFields.map(f => ({ label: f, value: f })));

type Effect = 'readonly' | 'editable' | 'required';
function effectOf(card: RuleCard): Effect {
  const e = card.content.effect ?? {};
  if (e.required) return 'required';
  return e.editable === true ? 'editable' : 'readonly';
}
function setEffect(card: RuleCard, value: Effect) {
  card.content.effect = value === 'required' ? { required: true } : { editable: value === 'editable' };
  card.dirty = true;
}
function useVisual(card: RuleCard, visual: boolean) {
  card.content.when = visual ? newVisual() : '';
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
  <NModal :show="show" preset="card" :title="`可编辑规则 - ${table.title}`" style="width: 760px; max-height: 85vh" :segmented="{ content: true, footer: true }" @update:show="emit('update:show', $event)">
    <div class="rules-area" style="max-height: 65vh">
      <NEmpty v-if="!state.loading && !state.cards.length" description="暂无可编辑规则" />
      <div v-for="(card, idx) in state.cards" :key="card._id" class="rule-card">
        <div class="rule-header">
          <NTag size="small" type="info">可编辑</NTag>
          <span class="rule-index">#{{ idx + 1 }}</span>
          <NInput v-model:value="card.key" size="tiny" :disabled="card.version !== null" style="width: 220px" @update:value="card.dirty = true" />
          <span class="field-label">排序</span>
          <NInputNumber v-model:value="card.content.order" size="tiny" style="width: 80px" @update:value="card.dirty = true" />
          <div class="spacer" />
          <NPopconfirm @positive-click="editor.remove(card)">
            <template #trigger><NButton size="tiny" quaternary type="error">删除</NButton></template>
            确定删除？
          </NPopconfirm>
        </div>
        <NRadioGroup :value="isVisual(card.content.when) ? 'visual' : 'expr'" size="small" style="margin-bottom: 8px" @update:value="v => useVisual(card, v === 'visual')">
          <NRadio value="visual">可视化条件</NRadio>
          <NRadio value="expr">表达式</NRadio>
        </NRadioGroup>
        <VisualConditionEditor v-if="isVisual(card.content.when)" :value="card.content.when" :row-fields="rowFields" :master-fields="masterOptions" @change="card.dirty = true" />
        <NInput v-else :value="String(card.content.when ?? '')" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" placeholder="如: ISERP == '1'" style="margin-bottom: 8px" @update:value="v => ((card.content.when = v), (card.dirty = true))" />
        <div class="rule-row">
          <div class="rule-field">
            <span class="field-label">作用范围</span>
            <NSelect :value="card.content.field ? 'cell' : 'row'" :options="[{ label: '整行', value: 'row' }, { label: '指定字段', value: 'cell' }]" size="small" style="width: 130px" @update:value="v => ((card.content.field = v === 'row' ? null : rowFields[0]?.value ?? null), (card.dirty = true))" />
          </div>
          <div v-if="card.content.field" class="rule-field">
            <span class="field-label">字段</span>
            <NSelect v-model:value="card.content.field" :options="rowFields" filterable size="small" style="width: 200px" @update:value="card.dirty = true" />
          </div>
          <div class="rule-field">
            <span class="field-label">条件成立时</span>
            <NSelect :value="effectOf(card)" :options="[{ label: '不可编辑', value: 'readonly' }, { label: '可编辑', value: 'editable' }, { label: '必填', value: 'required' }]" size="small" style="width: 130px" @update:value="v => setEffect(card, v)" />
          </div>
        </div>
        <ProblemList :problems="card.problems" />
      </div>
    </div>
    <template #footer>
      <NSpace justify="space-between" size="small">
        <NButton size="small" @click="add">+ 新增规则</NButton>
        <NSpace size="small">
          <NButton size="small" @click="emit('update:show', false)">取消</NButton>
          <NButton size="small" type="primary" :loading="state.busy" @click="save">保存</NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped src="./rule-dialog.css"></style>
