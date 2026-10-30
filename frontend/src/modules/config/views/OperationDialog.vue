<script setup lang="ts">
/**
 * 本页面的操作（C06 第 4、6 节）：左侧列出保存操作和以"页面编码."开头、或被本页面按钮引用的操作，右侧编辑：
 * 名称、类型（保存 / 按钮 / 逃生舱）、传播（必须写）、行不存在时、可写字段、影响实体、动作（重算、写到目标、
 * 找到记录并更新、按 SQL 替换明细、按 SQL 更新、逃生舱），逃生舱另登记存储过程和会修改的表、列。旧系统按钮里的执行方式（存储过程、SQL、Java 方法）
 * 在新平台改为这里的通用动作；逃生舱只在用户点名时启用。
 */
import { computed, onMounted, ref } from 'vue';
import { NButton, NCard, NForm, NFormItem, NInput, NInputNumber, NList, NListItem, NModal, NSelect, NSpace } from 'naive-ui';
import type { PageCatalog } from '../core/catalog';
import { useConfigContext } from '../core/context';
import { ItemEditor } from '../core/item-editor';
import type { ActionStep } from '../core/types';
import ProblemList from '../components/ProblemList.vue';
import { ACTION_OPTIONS, fromLines, fromList, newAction, toLines, toList, writesFromText, writesToText } from './operation-form';

const props = defineProps<{ show: boolean; page: ItemEditor<'page'>; catalog: PageCatalog }>();
const emit = defineEmits<{ 'update:show': [show: boolean] }>();
const { store, notify } = useConfigContext();
const editor = new ItemEditor(store, 'operation', notify);
const pageCode = computed(() => props.page.state.current!.key);
const pageContent = computed(() => props.page.state.current!.content);
const referenced = computed(() =>
  new Set([pageContent.value.saveOperation, ...[pageContent.value.master, ...(pageContent.value.details ?? [])].flatMap(a => (a.buttons ?? []).map(b => b.operation).filter((o): o is string => Boolean(o)))])
);
const list = computed(() => editor.state.items.filter(i => i.key.startsWith(`${pageCode.value}.`) || referenced.value.has(i.key)));
const op = computed(() => editor.state.current?.content ?? null);
const entityOptions = computed(() => props.catalog.tables.map(t => ({ label: `${t.title} · ${t.entity}`, value: t.entity })));
const newKey = ref('');
const writesText = ref('');
const escapeOptions = computed(() => editor.state.items.map(i => ({ label: `${i.name} · ${i.key}`, value: i.key })));

async function open(key: string) {
  await editor.open(key);
  writesText.value = writesToText(op.value?.writes);
}

function create() {
  const key = newKey.value.trim() || `${pageCode.value}.newAction`;
  editor.create(key, '新操作');
  writesText.value = '';
}

function writable(entity: string) {
  return op.value?.writableFields?.[entity] ?? [];
}
function setWritable(entity: string, fields: string[]) {
  const value = op.value!;
  value.writableFields = { ...(value.writableFields ?? {}), [entity]: fields };
  if (!fields.length) delete value.writableFields[entity];
}

function addAction(kind: ActionStep['action']) {
  const value = op.value!;
  value.actions = [...(value.actions ?? []), newAction(kind)];
}

async function save() {
  const value = op.value!;
  editor.state.current!.name = value.label;
  if (value.kind === 'escapeHatch') value.writes = writesFromText(writesText.value);
  else {
    delete value.writes;
    delete value.procedure;
  }
  if (value.kind !== 'action') value.actions = [];
  await editor.save();
}

onMounted(() => editor.loadList());
</script>

<template>
  <NModal :show="show" preset="card" :title="`操作 - ${page.state.current!.content.title}`" style="width: min(1100px, 96vw); max-height: 90vh" @update:show="emit('update:show', $event)">
    <div class="dialog-body">
      <div class="op-list">
        <NList hoverable clickable size="small">
          <NListItem v-for="item in list" :key="item.key" :class="{ active: editor.state.current?.key === item.key }" @click="open(item.key)">
            <div class="op-name">{{ item.name }}</div>
            <div class="op-key">{{ item.key }} · 版本 {{ item.version }}</div>
          </NListItem>
        </NList>
        <NSpace size="small" class="mt-8">
          <NInput v-model:value="newKey" size="small" :placeholder="`${pageCode}.xxx`" style="width: 150px" />
          <NButton size="small" @click="create">新增操作</NButton>
        </NSpace>
      </div>
      <div v-if="op" class="op-form">
        <NForm label-placement="left" label-width="100px" size="small">
          <NFormItem label="编码"><NInput :value="editor.state.current!.key" disabled /></NFormItem>
          <NFormItem label="名称"><NInput v-model:value="op.label" /></NFormItem>
          <NFormItem label="类型">
            <NSelect v-model:value="op.kind" :options="[{ label: '页面保存（save）', value: 'save' }, { label: '按钮（action）', value: 'action' }, { label: '逃生舱（escapeHatch，只在用户点名时启用）', value: 'escapeHatch' }]" />
          </NFormItem>
          <NFormItem label="传播">
            <NSelect v-model:value="op.propagation" :options="[{ label: '继续触发审批和同步（continue）', value: 'continue' }, { label: '写到的目标不再触发（end）', value: 'end' }]" />
          </NFormItem>
          <NFormItem label="行已被删除时">
            <NSelect v-model:value="op.rowNotFound" :options="[{ label: '跳过并提示（skip）', value: 'skip' }, { label: '拒绝（reject）', value: 'reject' }]" />
          </NFormItem>
          <NFormItem v-for="table in catalog.tables" :key="table.entity" :label="`可写 · ${table.title}`">
            <NSelect :value="writable(table.entity)" multiple filterable :options="table.fields.map(f => ({ label: `${f.label} · ${f.name}`, value: f.name }))" @update:value="v => setWritable(table.entity, v)" />
          </NFormItem>
          <NFormItem label="影响实体"><NSelect v-model:value="op.impact" multiple :options="entityOptions" /></NFormItem>
          <template v-if="op.kind === 'escapeHatch'">
            <NFormItem label="存储过程"><NInput v-model:value="op.procedure" placeholder="如 P_COST_BOM_INSERT" /></NFormItem>
            <NFormItem label="会修改的表、列"><NInput v-model:value="writesText" type="textarea" placeholder="每行一个表：T_COST_PINGGU: PRICE, AMOUNT（不能含 ERP 列）" /></NFormItem>
          </template>
        </NForm>
        <template v-if="op.kind === 'action'">
          <div class="section-label">动作（按顺序执行，后一个动作用前一个动作计算后的结果）</div>
          <NCard v-for="(action, ai) in op.actions ?? []" :key="ai" size="small" class="mb-8">
            <NSpace align="center" justify="space-between">
              <strong>{{ ai + 1 }}. {{ ACTION_OPTIONS.find(o => o.value === action.action)?.label }}</strong>
              <NButton text type="error" @click="op.actions!.splice(ai, 1)">删除</NButton>
            </NSpace>
            <template v-if="action.action === 'recalculate'">
              <NSelect v-model:value="action.target" :options="[{ label: '重算来源（source）', value: 'source' }, { label: '重算目标（targets）', value: 'targets' }]" style="width: 240px" />
            </template>
            <template v-if="action.action === 'escapeHatch'">
              <NSelect v-model:value="action.operation" :options="escapeOptions" filterable placeholder="已登记的逃生舱操作" />
            </template>
            <template v-if="action.action === 'updateTargets'">
              <NCard v-for="(target, ti) in action.targets" :key="ti" size="small" embedded class="mt-8">
                <NSpace :wrap="true">
                  <NInput v-model:value="target.entity" placeholder="目标实体" style="width: 160px" />
                  <NInput :value="target.detailEntity ?? ''" placeholder="目标明细实体（可空）" style="width: 180px" @update:value="v => (target.detailEntity = v || null)" />
                  <NInput :value="toLines(target.match)" type="textarea" placeholder="match：明细字段=来源实体.字段，每行一个" style="width: 300px" @update:value="v => (target.match = fromLines(v))" />
                  <NButton text type="error" @click="action.targets.splice(ti, 1)">删除目标</NButton>
                </NSpace>
                <div v-for="(m, mi) in target.fieldMapping" :key="mi" class="map-row">
                  <NInput v-model:value="m.from" placeholder="来源实体.字段" />
                  <span>→</span>
                  <NInput v-model:value="m.to" placeholder="目标字段" />
                  <NButton text type="error" @click="target.fieldMapping.splice(mi, 1)">删</NButton>
                </div>
                <NButton size="tiny" dashed @click="target.fieldMapping.push({ from: '', to: '' })">+ 字段映射</NButton>
              </NCard>
              <NButton size="tiny" dashed class="mt-8" @click="action.targets.push({ entity: '', fieldMapping: [] })">+ 目标</NButton>
            </template>
            <template v-if="action.action === 'updateRecords'">
              <NSpace :wrap="true" class="mt-8">
                <NSelect
                  :value="action.find.kind"
                  :options="[{ label: '按关联键', value: 'relationKey' }, { label: '按关联 SQL', value: 'sql' }]"
                  style="width: 140px"
                  @update:value="v => (action.find = v === 'sql' ? { kind: 'sql', entity: action.find.entity, sql: '', recordKeyColumn: '' } : { kind: 'relationKey', entity: action.find.entity, targetKey: '', sourceKey: '', rows: 'all' })"
                />
                <NInput v-model:value="action.find.entity" placeholder="找到的对象所在实体" style="width: 180px" />
                <template v-if="action.find.kind === 'relationKey'">
                  <NInput v-model:value="action.find.targetKey" placeholder="目标关联字段" style="width: 140px" />
                  <NInput v-model:value="action.find.sourceKey" placeholder="来源实体.字段" style="width: 180px" />
                  <span class="hint">按钮命令用选中单据的全部行（rows 为 all）</span>
                </template>
              </NSpace>
              <template v-if="action.find.kind === 'sql'">
                <NInput v-model:value="action.find.sql" type="textarea" class="mt-8" placeholder="只能是一条查询语句，参数用绑定变量" />
                <NSpace :wrap="true" class="mt-8">
                  <NInput :value="toLines(action.find.binds)" type="textarea" placeholder="绑定变量：名称=来源实体.字段" style="width: 260px" @update:value="v => action.find.kind === 'sql' && (action.find.binds = fromLines(v))" />
                  <NInput v-model:value="action.find.recordKeyColumn" placeholder="单据主键列" style="width: 130px" />
                  <NInput :value="toList(action.find.rowKeyColumns)" placeholder="明细主键列（逗号分隔）" style="width: 170px" @update:value="v => action.find.kind === 'sql' && (action.find.rowKeyColumns = fromList(v))" />
                  <NInput :value="action.find.labelColumn ?? ''" placeholder="标题列（可空）" style="width: 130px" @update:value="v => action.find.kind === 'sql' && (action.find.labelColumn = v || null)" />
                  <NInput :value="toList(action.find.displayColumns)" placeholder="显示列（逗号分隔）" style="width: 170px" @update:value="v => action.find.kind === 'sql' && (action.find.displayColumns = fromList(v))" />
                </NSpace>
              </template>
              <div v-for="(m, mi) in action.fieldMapping" :key="mi" class="map-row">
                <NInput v-model:value="m.from" placeholder="来源实体.字段" />
                <span>→</span>
                <NInput v-model:value="m.to" placeholder="目标字段" />
                <NButton text type="error" @click="action.fieldMapping.splice(mi, 1)">删</NButton>
              </div>
              <NButton size="tiny" dashed @click="action.fieldMapping.push({ from: '', to: '' })">+ 字段映射</NButton>
            </template>
            <template v-if="action.action === 'replaceDetails'">
              <NSpace :wrap="true" align="center" class="mt-8">
                <NSelect v-model:value="action.entity" :options="entityOptions" placeholder="要替换的明细" style="width: 220px" />
                <span class="hint">删掉选中单据这个明细的全部行，再把 SQL 的每一行新增为一行；列名写成字段名，计算字段和名称不写</span>
              </NSpace>
              <NInput v-model:value="action.sql" type="textarea" class="mt-8" placeholder="只能是一条查询语句，参数用绑定变量" />
              <NInput
                :value="toLines(action.binds)"
                type="textarea"
                class="mt-8"
                placeholder="绑定变量：名称=主表实体.字段，每行一个"
                style="width: 320px"
                @update:value="v => action.action === 'replaceDetails' && (action.binds = fromLines(v))"
              />
            </template>
            <template v-if="action.action === 'updateRows'">
              <NSpace :wrap="true" align="center" class="mt-8">
                <NSelect v-model:value="action.entity" :options="entityOptions" placeholder="要修改的实体" style="width: 220px" />
                <NInput v-model:value="action.recordKeyColumn" placeholder="单据主键列" style="width: 130px" />
                <NInput
                  :value="toList(action.rowKeyColumns)"
                  placeholder="明细主键列（明细写一列）"
                  style="width: 190px"
                  @update:value="v => action.action === 'updateRows' && (action.rowKeyColumns = fromList(v))"
                />
                <span class="hint">不用选中行；SQL 不用绑定变量，其余列名写成要改的字段名</span>
              </NSpace>
              <NInput v-model:value="action.sql" type="textarea" class="mt-8" placeholder="只能是一条查询语句，结果含单据主键列、明细主键列和要改的字段" />
            </template>
          </NCard>
          <NSpace size="small">
            <NButton v-for="o in ACTION_OPTIONS" :key="o.value" size="tiny" dashed @click="addAction(o.value)">+ {{ o.label }}</NButton>
          </NSpace>
        </template>
        <ProblemList :problems="editor.state.problems" />
        <NSpace justify="end" class="mt-8">
          <span class="hint">{{ editor.state.status }}</span>
          <NButton size="small" :loading="editor.state.busy" @click="editor.validate()">校验</NButton>
          <NButton size="small" type="primary" :loading="editor.state.busy" @click="save">保存</NButton>
        </NSpace>
      </div>
      <div v-else class="op-form empty">从左侧选择一个操作，或新增操作</div>
    </div>
  </NModal>
</template>

<style scoped>
.dialog-body { display: flex; gap: 12px; max-height: 72vh; }
.op-list { width: 240px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid #e8e8e8; padding-right: 8px; }
.op-form { flex: 1; overflow-y: auto; min-width: 0; }
.op-form.empty { color: #999; display: flex; align-items: center; justify-content: center; }
.op-name { font-size: 13px; }
.op-key { font-size: 12px; color: #999; }
.active { background: #e8f2ff; }
.section-label { font-size: 13px; font-weight: 500; margin: 8px 0; }
.map-row { display: grid; grid-template-columns: 1fr auto 1fr auto; gap: 6px; align-items: center; margin: 6px 0; }
.hint { color: #999; font-size: 12px; }
</style>
