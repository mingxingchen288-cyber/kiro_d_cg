<script setup lang="ts">
/**
 * 需审批的编辑字段（C06 第 2 节 `approvalRequired`、FC-08），弹窗写法同旧系统 CellEditableDialog.vue 的"需审批的编辑字段"：
 * 每张卡片一条规则——字段、条件（只用本行字段，运算符 等于 / 不等于 / 为空 / 非空，不能用 SQL）、来源页面。
 * 规则属于实体：任何写入口写这个实体都检查，停用或删除审批流不会让规则失效。保存的是实体配置项。
 */
import { onMounted, ref } from 'vue';
import { NButton, NEmpty, NInput, NModal, NPopconfirm, NSelect, NSpace, NTag } from 'naive-ui';
import type { PageTable } from '../core/catalog';
import { useConfigContext } from '../core/context';
import { ItemEditor } from '../core/item-editor';
import type { ApprovalRequiredRule } from '../core/types';
import ProblemList from '../components/ProblemList.vue';
import { LOGIC_OPTIONS } from '../rules/rule-model';
import { cleanApprovalRequired, newApprovalRequired } from './entity-model';

const props = defineProps<{ show: boolean; table: PageTable }>();
const emit = defineEmits<{ 'update:show': [show: boolean] }>();
const { store, notify } = useConfigContext();
const editor = new ItemEditor(store, 'entity', notify);
const rules = ref<ApprovalRequiredRule[]>([]);
const pages = ref<Array<{ label: string; value: string }>>([]);
const fields = props.table.fields.map(f => ({ label: `${f.label} · ${f.name}`, value: f.name }));
const ops = [
  { label: '= 等于', value: 'eq' },
  { label: '≠ 不等于', value: 'ne' },
  { label: '为空', value: 'isNull' },
  { label: '非空', value: 'isNotNull' }
];

onMounted(async () => {
  await editor.open(props.table.entity);
  rules.value = JSON.parse(JSON.stringify(editor.state.current?.content.approvalRequired ?? [])).map((r: ApprovalRequiredRule) => ({ ...r, when: r.when ?? { logic: 'AND', conditions: [] } }));
  pages.value = (await store.list('page')).map(p => ({ label: `${p.name} · ${p.key}`, value: p.key }));
});

async function save() {
  const current = editor.state.current;
  if (!current) return;
  current.content.approvalRequired = cleanApprovalRequired(rules.value);
  editor.markDirty();
  if ((await editor.save()) !== null) emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" :title="`需审批的编辑字段 - ${table.title}`" style="width: 760px; max-height: 85vh" :segmented="{ content: true, footer: true }" @update:show="emit('update:show', $event)">
    <div class="rules-area" style="max-height: 65vh">
      <NEmpty v-if="!rules.length" description="暂无必须审批的字段规则" />
      <div v-for="(rule, idx) in rules" :key="idx" class="rule-card">
        <div class="rule-header">
          <NTag size="small" type="warning">需审批</NTag>
          <span class="rule-index">#{{ idx + 1 }}</span>
          <div class="spacer" />
          <NPopconfirm @positive-click="rules.splice(idx, 1)">
            <template #trigger><NButton size="tiny" quaternary type="error">删除</NButton></template>
            确定删除？
          </NPopconfirm>
        </div>
        <div class="section-label">修改这些字段必须审批</div>
        <NSelect v-model:value="rule.fields" multiple filterable :options="fields" placeholder="选择字段" style="width: 100%; margin-bottom: 8px" />
        <div class="condition-row">
          <span class="field-label">行满足</span>
          <NSelect v-model:value="rule.when!.logic" :options="LOGIC_OPTIONS" size="small" style="width: 160px" />
          <span class="field-label">条件时（修改前或修改后的行满足都算；不写条件时所有行都满足）</span>
        </div>
        <div v-for="(cond, ci) in rule.when!.conditions" :key="ci" class="condition-row">
          <NSelect v-model:value="cond.field" :options="fields" filterable size="small" placeholder="字段" style="width: 170px" />
          <NSelect v-model:value="cond.op" :options="ops" size="small" style="width: 110px" />
          <NInput v-if="cond.op === 'eq' || cond.op === 'ne'" :value="cond.value ?? ''" size="small" placeholder="值" style="width: 130px" @update:value="v => (cond.value = v)" />
          <NButton size="tiny" quaternary type="error" @click="rule.when!.conditions.splice(ci, 1)">删除</NButton>
        </div>
        <NButton size="tiny" dashed style="margin: 4px 0 8px" @click="rule.when!.conditions.push({ field: '', op: 'eq', value: '' })">+ 添加条件</NButton>
        <div class="section-label">来源页面（至少有一个启用的审批流的所属页面在这里）</div>
        <NSelect v-model:value="rule.sourcePages" multiple filterable :options="pages" placeholder="选择页面" />
      </div>
      <ProblemList :problems="editor.state.problems" />
    </div>
    <template #footer>
      <NSpace justify="space-between" size="small">
        <NButton size="small" @click="rules.push(newApprovalRequired())">+ 新增规则</NButton>
        <NSpace size="small">
          <NButton size="small" @click="emit('update:show', false)">取消</NButton>
          <NButton size="small" type="primary" :loading="editor.state.busy" @click="save">保存</NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped src="../rules/rule-dialog.css"></style>
