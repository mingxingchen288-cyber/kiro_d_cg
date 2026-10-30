<script setup lang="ts">
/**
 * 待办列表（FA-06、FA-11），沿用旧系统审批通知中心（`approval-notification-center.vue`）：上方的条数和
 * "待审批 / 我的发起 / 全部审批"三个页签；每个审批一行，列为来源页面和操作、来源单据号、提交人、提交时间、状态和当前级别；
 * 每行有"原单据"（打开来源页面并选中这张单据，FA-14）和"处理"（我的发起、全部审批为"查看"）按钮，双击行也打开审批详情
 * （`/approval/{approvalId}`）。旧系统是顶栏的抽屉，点"查看全部"把"待审批"换成"全部审批"（提示"当前显示全部审批历史"）；
 * 这里是路由 `/approval` 的页面，"全部审批"做成第三个页签，提示文字同旧系统。
 */
import { computed, onBeforeUnmount, onMounted } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, ICellRendererParams, RowDoubleClickedEvent } from 'ag-grid-community';
import type { ApprovalSummary } from '../../../contracts/http';
import type { ShellApi } from '../../../contracts/shell';
import { createPlatformApi } from '../../../contracts/api';
import { ApprovalTodoRuntime, BOXES, BOX_LABEL, type Box, PAGE_SIZE, summaryTexts } from '../todo-runtime';
import { HEADER_HEIGHT, ROW_HEIGHT, simpleTheme } from './grid-theme';

defineOptions({ name: 'ApprovalTodoPage' });

const props = defineProps<{ shell: ShellApi }>();

const runtime = new ApprovalTodoRuntime({
  api: createPlatformApi(props.shell.http),
  message: props.shell.message,
  tabs: props.shell.tabs,
  realtime: props.shell.realtime
});
const { state } = runtime;

type Row = ReturnType<typeof summaryTexts> & { approvalId: string; item: ApprovalSummary };

const rowData = computed<Row[]>(() =>
  state.rows.map(item => ({ ...summaryTexts(item), approvalId: item.approvalId, item }))
);

function renderActions(params: ICellRendererParams<Row>) {
  const row = params.data;
  const container = document.createElement('div');
  container.className = 'todo-actions';
  if (!row) return container;
  const source = document.createElement('button');
  source.type = 'button';
  source.className = 'todo-button';
  source.textContent = '原单据';
  source.addEventListener('click', () => runtime.openSource(row.item));
  const open = document.createElement('button');
  open.type = 'button';
  open.className = 'todo-button todo-button-primary';
  open.textContent = state.box === 'todo' ? '处理' : '查看';
  open.addEventListener('click', () => runtime.open(row));
  container.append(source, open);
  return container;
}

const columnDefs = computed<ColDef<Row>[]>(() => [
  { field: 'source', headerName: '来源页面和操作', minWidth: 180, flex: 1.2 },
  { field: 'recordKey', headerName: '来源单据号', minWidth: 160, flex: 1 },
  { field: 'applicant', headerName: '提交人', width: 120 },
  { field: 'submittedAt', headerName: '提交时间', width: 170 },
  { field: 'status', headerName: '状态和当前级别', width: 150 },
  {
    colId: 'actions',
    headerName: '操作',
    width: 150,
    // 页签切换后按钮文字（处理 / 查看）随之变化
    valueGetter: () => state.box,
    cellRenderer: renderActions
  }
]);

const defaultColDef: ColDef = {
  sortable: false,
  filter: false,
  resizable: true,
  suppressHeaderMenuButton: true,
  suppressHeaderFilterButton: true,
  suppressHeaderContextMenu: true
};

function onRowDoubleClicked(event: RowDoubleClickedEvent<Row>) {
  if (event.data) runtime.open(event.data);
}

let stop: (() => void) | null = null;

onMounted(() => {
  stop = runtime.watch();
  void runtime.load();
});

onBeforeUnmount(() => stop?.());
</script>

<template>
  <div class="approval-todo-page">
    <div class="notice-summary">
      <div v-for="box in BOXES" :key="box">
        <span class="summary-value">{{ state.counts[box] }}</span>
        <span class="summary-label">{{ BOX_LABEL[box] }}</span>
      </div>
    </div>

    <NTabs :value="state.box" type="line" animated @update:value="(box: Box) => runtime.switchBox(box)">
      <NTabPane v-for="box in BOXES" :key="box" :name="box" :tab="BOX_LABEL[box]" />
    </NTabs>
    <div v-if="state.box === 'all'" class="todo-scope-hint">当前显示全部审批历史</div>

    <NAlert v-if="state.error" type="error" :bordered="false" class="mb-8px">
      {{ state.error }}
      <NButton size="small" class="ml-8px" @click="runtime.load()">重新读取</NButton>
    </NAlert>

    <NSpin :show="state.loading" class="todo-grid-wrap">
      <AgGridVue
        class="todo-grid"
        :theme="simpleTheme"
        :row-data="rowData"
        :column-defs="columnDefs"
        :default-col-def="defaultColDef"
        :get-row-id="p => p.data.approvalId"
        :row-height="ROW_HEIGHT"
        :header-height="HEADER_HEIGHT"
        :suppress-context-menu="true"
        :locale-text="{ noRowsToShow: '暂无审批' }"
        @row-double-clicked="onRowDoubleClicked"
      />
    </NSpin>

    <div v-if="state.total > PAGE_SIZE" class="todo-pagination">
      <NPagination
        :page="state.page"
        :page-size="PAGE_SIZE"
        :item-count="state.total"
        @update:page="(page: number) => runtime.setPage(page)"
      />
    </div>
  </div>
</template>

<style scoped>
.approval-todo-page {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  height: 100%;
  padding: 12px;
  background: #fff;
  font-size: 12px;
}
.todo-scope-hint {
  margin-bottom: 4px;
  color: #667085;
  font-size: 12px;
}
.notice-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 260px));
  gap: 8px;
  margin-bottom: 12px;
}
.notice-summary > div {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #f8fafc;
}
.summary-value {
  display: block;
  color: #1f2937;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.2;
}
.summary-label {
  color: #667085;
  font-size: 12px;
}
.todo-grid-wrap {
  flex: 1;
  min-height: 0;
}
.todo-grid-wrap :deep(.n-spin-content) {
  height: 100%;
}
.todo-grid {
  width: 100%;
  height: 100%;
  min-height: 240px;
}
.todo-grid :deep(.todo-actions) {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 100%;
}
.todo-grid :deep(.todo-button) {
  padding: 0 8px;
  border: 0;
  border-radius: 3px;
  background: rgba(46, 51, 56, 0.05);
  color: #1f2225;
  font-size: 12px;
  line-height: 22px;
  cursor: pointer;
}
.todo-grid :deep(.todo-button:hover) {
  background: rgba(46, 51, 56, 0.09);
}
.todo-grid :deep(.todo-button-primary) {
  background: rgba(100, 108, 255, 0.12);
  color: #646cff;
}
.todo-grid :deep(.todo-button-primary:hover) {
  background: rgba(100, 108, 255, 0.2);
}
.todo-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
}
</style>
