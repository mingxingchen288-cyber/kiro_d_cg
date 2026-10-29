<script setup lang="ts">
/**
 * 导出配置，同旧系统 SectionExport.vue：列表（导出名称、导出编码、主表 Sheet、字体、操作）和"新增导出""刷新"；
 * 编辑弹窗：页面编码、导出名称、导出编码、文件名、主表 Sheet、导出字体、明细布局、主表 SQL、主表关联列、主表列，
 * 导出明细（Sheet 名称、明细 SQL、明细关联列、明细列）。每个导出是一个 `export` 配置项（C06 第 9 节）。
 * 旧系统的列配置是 JSON 文本，这里改成表格逐列填写；"排序"在 C06 中没有对应字段，不提供。
 */
import { computed, h, onMounted, ref } from 'vue';
import { NButton, NCard, NDataTable, NForm, NFormItem, NGrid, NGridItem, NInput, NModal, NPopconfirm, NSelect, NSpace } from 'naive-ui';
import { useConfigContext } from '../core/context';
import { ItemEditor } from '../core/item-editor';
import type { TypedItem } from '../core/store';
import { newContent } from '../core/defaults';
import ProblemList from '../components/ProblemList.vue';
import ExportColumnsGrid from './ExportColumnsGrid.vue';

const props = defineProps<{ pageCode: string }>();
const { store, notify } = useConfigContext();
const editor = new ItemEditor(store, 'export', notify);
const configs = ref<Array<TypedItem<'export'>>>([]);
const loading = ref(false);
const show = ref(false);
const isNew = ref(false);
const content = computed(() => editor.state.current?.content ?? null);
const fonts = ['Calibri', 'Arial', 'Times New Roman', 'Microsoft YaHei', 'SimSun', 'SimHei', 'DengXian'].map(v => ({ label: v, value: v }));

async function load() {
  loading.value = true;
  try {
    configs.value = (await store.loadAll('export')).filter(e => e.content.page === props.pageCode);
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editor.create('', '新导出', { ...newContent('export', '', '新导出'), page: props.pageCode });
  isNew.value = true;
  show.value = true;
}

async function openEdit(key: string) {
  await editor.open(key);
  isNew.value = false;
  show.value = true;
}

async function save() {
  const current = editor.state.current!;
  current.content.name = current.name;
  if ((await editor.save()) !== null) {
    show.value = false;
    await load();
  }
}

async function remove(key: string) {
  await editor.open(key);
  if (await editor.remove()) await load();
}

const columns = [
  { title: '导出名称', key: 'name', render: (row: TypedItem<'export'>) => row.name },
  { title: '导出编码', key: 'key', minWidth: 180 },
  { title: '主表Sheet', key: 'sheet', render: (row: TypedItem<'export'>) => row.content.master.sheet },
  { title: '字体', key: 'font', render: (row: TypedItem<'export'>) => row.content.font ?? 'Calibri' },
  { title: '版本', key: 'version', width: 60 },
  {
    title: '操作',
    key: 'actions',
    width: 140,
    render: (row: TypedItem<'export'>) =>
      h(NSpace, { size: 'small' }, () => [
        h(NButton, { size: 'tiny', onClick: () => openEdit(row.key) }, () => '编辑'),
        h(NPopconfirm, { onPositiveClick: () => remove(row.key) }, { trigger: () => h(NButton, { size: 'tiny', type: 'error', quaternary: true }, () => '删除'), default: () => '确定删除这个导出配置？' })
      ])
  }
];

onMounted(load);
</script>

<template>
  <div class="section-export">
    <NSpace size="small" class="mb-8">
      <NButton size="small" type="primary" @click="openCreate">新增导出</NButton>
      <NButton size="small" quaternary :loading="loading" @click="load">刷新</NButton>
    </NSpace>
    <NDataTable v-if="configs.length" :columns="columns" :data="configs" :row-key="(row: TypedItem<'export'>) => row.key" size="small" :bordered="false" />
    <p v-else-if="!loading" class="empty-hint">暂无导出配置</p>
    <ProblemList v-if="!show" :problems="editor.state.problems" />

    <NModal v-model:show="show" preset="card" :title="isNew ? '新增导出' : `编辑导出 · ${editor.state.current?.name ?? ''}`" style="width: min(1000px, 96vw); max-height: 90vh" :body-style="{ overflow: 'auto' }">
      <template v-if="content && editor.state.current">
        <NForm label-placement="left" label-width="100px" size="small">
          <NGrid :cols="2" :x-gap="12">
            <NGridItem><NFormItem label="页面编码"><NInput :value="content.page" disabled /></NFormItem></NGridItem>
            <NGridItem><NFormItem label="导出名称"><NInput v-model:value="editor.state.current.name" placeholder="例如：物料成本核算表导出" /></NFormItem></NGridItem>
            <NGridItem><NFormItem label="导出编码"><NInput v-model:value="editor.state.current.key" :disabled="!isNew" placeholder="例如：cost-pinggu-export" /></NFormItem></NGridItem>
            <NGridItem><NFormItem label="文件名"><NInput v-model:value="content.fileName" placeholder="例如：物料成本核算表" /></NFormItem></NGridItem>
            <NGridItem><NFormItem label="主表 Sheet"><NInput v-model:value="content.master.sheet" /></NFormItem></NGridItem>
            <NGridItem><NFormItem label="导出字体"><NSelect v-model:value="content.font" :options="fonts" tag filterable placeholder="Calibri" /></NFormItem></NGridItem>
            <NGridItem>
              <NFormItem label="明细布局">
                <NSelect v-model:value="content.detailLayout" :options="[{ label: '每张主单一张明细工作表', value: 'perMaster' }, { label: '每个明细配置一张工作表', value: 'perDetail' }]" />
              </NFormItem>
            </NGridItem>
            <NGridItem><NFormItem label="主表关联列"><NInput v-model:value="content.master.keyColumn" placeholder="与页面主表主键相等的列，例如 DOCID" /></NFormItem></NGridItem>
          </NGrid>
          <NFormItem label="主表 SQL"><NInput v-model:value="content.master.sql" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" placeholder="只能是一条查询语句；导出时平台按主表行权限和当前查询条件限定结果，不在 SQL 里拼条件" /></NFormItem>
          <NFormItem label="主表列"><ExportColumnsGrid :columns="content.master.columns" style="width: 100%" /></NFormItem>
        </NForm>
        <div class="detail-title">
          导出明细
          <NButton size="tiny" type="primary" @click="(content.details ??= []).push({ sheet: '', sql: '', linkColumn: '', columns: [] })">新增明细</NButton>
        </div>
        <NCard v-for="(detail, i) in content.details ?? []" :key="i" size="small" class="mb-8">
          <NForm label-placement="left" label-width="100px" size="small">
            <NGrid :cols="2" :x-gap="12">
              <NGridItem><NFormItem label="Sheet名称"><NInput v-model:value="detail.sheet" placeholder="例如：原辅料明细" /></NFormItem></NGridItem>
              <NGridItem><NFormItem label="明细关联列"><NInput v-model:value="detail.linkColumn" placeholder="例如：DOCID" /></NFormItem></NGridItem>
            </NGrid>
            <NFormItem label="明细 SQL"><NInput v-model:value="detail.sql" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" /></NFormItem>
            <NFormItem label="明细列"><ExportColumnsGrid :columns="detail.columns" style="width: 100%" /></NFormItem>
          </NForm>
          <NSpace justify="end"><NButton size="tiny" type="error" quaternary @click="content.details!.splice(i, 1)">删除明细</NButton></NSpace>
        </NCard>
        <p v-if="!content.details?.length" class="empty-hint">暂无导出明细</p>
        <ProblemList :problems="editor.state.problems" />
      </template>
      <template #footer>
        <NSpace justify="end">
          <NButton size="small" @click="show = false">取消</NButton>
          <NButton size="small" :loading="editor.state.busy" @click="editor.validate()">校验</NButton>
          <NButton size="small" type="primary" :loading="editor.state.busy" @click="save">保存导出</NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.section-export { padding: 8px 0; }
.empty-hint { color: #999; font-size: 13px; }
.detail-title { display: flex; align-items: center; gap: 8px; font-weight: 500; margin: 12px 0 8px; }
</style>
