<script setup lang="ts">
/**
 * 计算规则、校验规则弹窗，同旧系统 RuleConfigDialog.vue（1060px）：左侧一张卡片一条规则，右侧"字段参考"，
 * 点字段把引用插到正在编辑的输入框光标处（本区域字段直接写字段名；明细里引用主表写 `master.字段`；主表里引用明细写明细实体编码，
 * 例如 `sum(map(COST_MATERIAL, #.USAGE * #.PRICE))`）。表达式为 ZEN 表达式（C06 第 5 节）。
 * 多公式按分支写，"分支字段 + 匹配方式 + 值"生成分支条件；校验的"规则 + 值"生成条件。
 */
import { computed, ref } from 'vue';
import { NButton, NEmpty, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NSwitch, NTag } from 'naive-ui';
import type { PageTable } from '../core/catalog';
import { useConfigContext } from '../core/context';
import ProblemList from '../components/ProblemList.vue';
import { type RuleCard, RuleEditor } from './rule-editor';
import { MATCH_OPTIONS, type MatchType, RULE_KIND_TITLES, VALIDATE_OPTIONS, type ValidateType, matchCondition, validateCondition } from './rule-model';

const props = defineProps<{ show: boolean; kind: 'calc' | 'validate'; pageCode: string; table: PageTable; tables: PageTable[]; masterFields: string[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean] }>();
const { store, notify } = useConfigContext();
const editor = new RuleEditor(store, { pageCode: props.pageCode, table: props.table }, props.kind, props.masterFields, notify);
const state = editor.state;
const sidebarFilter = ref('');
const helpers = ref<Record<string, { field: string | null; match: MatchType; value: string; rule: ValidateType }>>({});
const fieldOptions = computed(() => props.table.fields.map(f => ({ label: `${f.label} · ${f.name}`, value: f.name })));
const layerOptions = [
  { label: '实体（写到该实体时都执行）', value: 'entity' },
  { label: '本页面（只在前端预览）', value: 'page' },
  { label: '操作（执行该操作时）', value: 'operation' }
];

/** 字段参考：本区域、主表（明细中写 master.）、明细（主表中写实体编码） */
const groups = computed(() => {
  const k = sidebarFilter.value.trim().toLowerCase();
  return props.tables
    .map(t => ({
      t,
      fields: t.fields.filter(f => !k || f.name.toLowerCase().includes(k) || f.label.toLowerCase().includes(k))
    }))
    .filter(g => g.fields.length);
});

function tokenOf(t: PageTable, field: string) {
  if (t.entity === props.table.entity) return field;
  if (t.isMaster) return `master.${field}`;
  return `${t.entity}`;
}

/** 正在编辑的输入框：点字段参考时插在光标处 */
let focused: { el: HTMLTextAreaElement | HTMLInputElement; apply: (text: string) => void } | null = null;
function track(event: FocusEvent, apply: (text: string) => void) {
  focused = { el: event.target as HTMLTextAreaElement, apply };
}
function insertField(t: PageTable, field: string) {
  if (!focused) return;
  const { el, apply } = focused;
  const token = tokenOf(t, field);
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? start;
  apply(`${el.value.slice(0, start)}${token}${el.value.slice(end)}`);
}

function helper(card: RuleCard, index = 0) {
  const key = `${card._id}-${index}`;
  helpers.value[key] ??= { field: card.content.field, match: 'regex', value: '', rule: 'required' };
  return helpers.value[key];
}

function dirty(card: RuleCard) {
  card.dirty = true;
}

function whenText(card: RuleCard) {
  return typeof card.content.when === 'string' ? card.content.when : '';
}

function setMulti(card: RuleCard, multi: boolean) {
  card.multi = multi;
  if (multi && !card.content.branches?.length) card.content.branches = [{ when: null, expression: card.content.expression ?? '' }];
  dirty(card);
}

async function save() {
  if (await editor.save()) emit('update:show', false);
}

editor.load();
</script>

<template>
  <NModal :show="show" preset="card" :title="`${RULE_KIND_TITLES[kind]} - ${table.title}`" style="width: 1060px; max-height: 85vh" :segmented="{ content: true, footer: true }" @update:show="emit('update:show', $event)">
    <div class="dialog-body">
      <div class="rules-area">
        <NEmpty v-if="!state.loading && state.cards.length === 0" :description="`暂无${RULE_KIND_TITLES[kind]}`" />
        <div v-for="(card, idx) in state.cards" :key="card._id" class="rule-card">
          <div class="rule-header">
            <NTag size="small" :type="kind === 'validate' ? 'info' : card.multi ? 'warning' : 'info'">{{ kind === 'validate' ? '校验' : card.multi ? '多公式' : '单公式' }}</NTag>
            <span class="rule-index">#{{ idx + 1 }}</span>
            <NInput v-model:value="card.key" size="tiny" :disabled="card.version !== null" placeholder="规则编码" style="width: 220px" @update:value="dirty(card)" />
            <span v-if="card.version !== null" class="rule-index">版本 {{ card.version }}</span>
            <div class="spacer" />
            <NSelect :value="card.content.layer" :options="layerOptions" size="tiny" style="width: 200px" @update:value="v => (v === 'operation' ? ((card.content.layer = v), (card.content.target = '')) : editor.setLayer(card, v), dirty(card))" />
            <NInput v-if="card.content.layer === 'operation'" v-model:value="card.content.target" size="tiny" placeholder="操作编码" style="width: 160px" @update:value="dirty(card)" />
            <NSwitch v-if="kind === 'calc'" :value="card.multi" size="small" @update:value="v => setMulti(card, v)">
              <template #checked>多公式</template>
              <template #unchecked>单公式</template>
            </NSwitch>
            <NPopconfirm @positive-click="editor.remove(card)">
              <template #trigger><NButton size="tiny" quaternary type="error">删除</NButton></template>
              确定删除？保存后删除这条规则的配置项。
            </NPopconfirm>
          </div>
          <div class="rule-row">
            <div class="rule-field">
              <span class="field-label">{{ kind === 'calc' ? '目标字段' : '字段' }}</span>
              <NSelect v-model:value="card.content.field" :options="fieldOptions" size="small" filterable tag clearable placeholder="输入或选择" class="w-200" @update:value="dirty(card)" />
            </div>
            <div class="rule-field">
              <span class="field-label">排序</span>
              <NInputNumber v-model:value="card.content.order" size="small" class="w-80" @update:value="dirty(card)" />
            </div>
            <template v-if="kind === 'validate'">
              <div class="rule-field">
                <span class="field-label">规则</span>
                <NSelect v-model:value="helper(card).rule" :options="VALIDATE_OPTIONS" size="small" class="w-140" />
              </div>
              <div v-if="helper(card).rule !== 'required' && helper(card).rule !== 'custom'" class="rule-field">
                <span class="field-label">值</span>
                <NInput v-model:value="helper(card).value" size="small" placeholder="规则值" class="w-140" />
              </div>
              <NButton v-if="helper(card).rule !== 'custom'" size="small" @click="(card.content.when = validateCondition(card.content.field ?? '', helper(card).rule, helper(card).value)), dirty(card)">生成条件</NButton>
            </template>
            <div class="rule-field field-grow">
              <span class="field-label">{{ kind === 'validate' ? '条件（成立时拒绝或提示）' : '条件 (可选)' }}</span>
              <NInput :value="whenText(card)" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" size="small" placeholder="如: GOODSTYPE != '包材'" @focus="(e: FocusEvent) => track(e, v => ((card.content.when = v), dirty(card)))" @update:value="v => ((card.content.when = v), dirty(card))" />
            </div>
          </div>
          <div v-if="kind === 'validate'" class="rule-row">
            <div class="rule-field">
              <span class="field-label">级别</span>
              <NSelect v-model:value="card.content.level" :options="[{ label: '拒绝保存', value: 'reject' }, { label: '提示', value: 'prompt' }]" size="small" class="w-140" @update:value="dirty(card)" />
            </div>
            <div class="rule-field field-grow">
              <span class="field-label">错误提示</span>
              <NInput v-model:value="card.content.message" size="small" placeholder="校验失败时的提示信息" @update:value="dirty(card)" />
            </div>
          </div>
          <div v-if="kind === 'calc' && !card.multi" class="rule-row">
            <div class="rule-field field-grow">
              <span class="field-label">表达式</span>
              <NInput :value="card.content.expression ?? ''" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" size="small" placeholder="如: USAGE * PRICE" @focus="(e: FocusEvent) => track(e, v => ((card.content.expression = v), dirty(card)))" @update:value="v => ((card.content.expression = v), dirty(card))" />
            </div>
          </div>
          <template v-if="kind === 'calc' && card.multi">
            <div v-for="(branch, bi) in card.content.branches ?? []" :key="bi" class="formula-card">
              <div class="rule-row">
                <div class="rule-field">
                  <span class="field-label">分支字段</span>
                  <NSelect v-model:value="helper(card, bi + 1).field" :options="fieldOptions" size="small" filterable tag placeholder="选择分支依据" class="w-180" />
                </div>
                <div class="rule-field">
                  <span class="field-label">匹配方式</span>
                  <NSelect v-model:value="helper(card, bi + 1).match" :options="MATCH_OPTIONS" size="small" class="w-100" />
                </div>
                <div class="rule-field">
                  <span class="field-label">值</span>
                  <NInput v-model:value="helper(card, bi + 1).value" size="small" placeholder="如: 硬片|铝箔" class="w-180" />
                </div>
                <NButton size="small" @click="(branch.when = matchCondition(helper(card, bi + 1).field ?? '', helper(card, bi + 1).match, helper(card, bi + 1).value)), dirty(card)">生成条件</NButton>
                <NPopconfirm @positive-click="card.content.branches!.splice(bi, 1), dirty(card)">
                  <template #trigger><NButton size="tiny" quaternary type="error" class="align-self-end">删除</NButton></template>
                  删除此分支？
                </NPopconfirm>
              </div>
              <div class="rule-row">
                <div class="rule-field field-grow">
                  <span class="field-label">条件（按顺序取第一个成立的分支）</span>
                  <NInput :value="typeof branch.when === 'string' ? branch.when : ''" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" size="small" @focus="(e: FocusEvent) => track(e, v => ((branch.when = v), dirty(card)))" @update:value="v => ((branch.when = v), dirty(card))" />
                </div>
              </div>
              <div class="rule-row">
                <div class="rule-field field-grow">
                  <span class="field-label">表达式</span>
                  <NInput v-model:value="branch.expression" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" size="small" placeholder="如: 批量/每盒片数" @focus="(e: FocusEvent) => track(e, v => ((branch.expression = v), dirty(card)))" @update:value="dirty(card)" />
                </div>
              </div>
            </div>
            <NButton size="tiny" dashed class="mt-4" @click="(card.content.branches = [...(card.content.branches ?? []), { when: null, expression: '' }]), dirty(card)">+ 添加分支</NButton>
          </template>
          <template v-if="card.content.layer !== 'page'">
            <div v-for="(item, di) in card.content.dataItems ?? []" :key="di" class="formula-card">
              <div class="rule-row">
                <div class="rule-field"><span class="field-label">数据项名称（表达式中写 data.名称）</span><NInput v-model:value="item.name" size="small" class="w-180" @update:value="dirty(card)" /></div>
                <div class="rule-field field-grow"><span class="field-label">SQL（只读查询，参数用绑定变量）</span><NInput v-model:value="item.sql" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" size="small" @update:value="dirty(card)" /></div>
                <NButton size="tiny" quaternary type="error" @click="card.content.dataItems!.splice(di, 1), dirty(card)">删除</NButton>
              </div>
            </div>
            <NButton size="tiny" dashed class="mt-4" @click="(card.content.dataItems = [...(card.content.dataItems ?? []), { name: '', sql: '', binds: {} }]), dirty(card)">+ 数据项（有数据项的规则只在后端执行）</NButton>
          </template>
          <ProblemList :problems="card.problems" />
        </div>
      </div>
      <div class="field-sidebar">
        <div class="sidebar-header">字段参考</div>
        <NInput v-model:value="sidebarFilter" size="tiny" placeholder="搜索字段..." clearable class="sidebar-filter" />
        <div class="sidebar-scroll">
          <div v-for="g in groups" :key="g.t.entity" class="field-group">
            <div class="group-title">
              <NTag size="tiny" :type="g.t.isMaster ? 'success' : 'info'">{{ g.t.isMaster ? '主' : '从' }}</NTag>
              <span>{{ g.t.title }}</span>
            </div>
            <div v-for="f in g.fields" :key="f.name" class="field-item" @mousedown.prevent="insertField(g.t, f.name)">
              <span class="field-name">{{ f.label }}</span><span class="field-code">{{ f.name }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <NSpace justify="space-between" size="small">
        <NButton size="small" @click="editor.add(null)">+ 添加规则</NButton>
        <NSpace size="small">
          <span class="rule-index">{{ state.status }}</span>
          <NButton size="small" @click="emit('update:show', false)">取消</NButton>
          <NButton size="small" type="primary" :loading="state.busy" @click="save">保存</NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped src="./rule-dialog.css"></style>
