<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { NButton, NDrawer, NDrawerContent, NEmpty, NSpin, NSwitch } from 'naive-ui';
import { request } from '@/service/request';
import { useSqlTraceStore } from '@/store/modules/sql-trace';
import type { SqlTraceRequestRecord, SqlTraceSession } from '@/store/modules/sql-trace';

defineOptions({
  name: 'SqlTraceDrawer'
});

const traceStore = useSqlTraceStore();
const loading = ref(false);

const selectedSession = computed(() => {
  const traceId = traceStore.selectedRecord?.traceId;
  return traceId ? traceStore.sessions[traceId] : null;
});

const selectedPayload = computed(() => {
  const record = traceStore.selectedRecord;
  if (!record) return '';

  return formatJson({
    page: record.page,
    method: record.method,
    url: record.url,
    params: record.params,
    data: record.data
  });
});

function shortUrl(url: string) {
  try {
    const parsed = new URL(url, window.location.origin);
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}

function formatJson(value: unknown) {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function formatTime(value: number | string | undefined) {
  if (!value) return '';
  return new Date(value).toLocaleTimeString();
}

async function loadSession(record: SqlTraceRequestRecord | null) {
  if (!record?.traceId || traceStore.sessions[record.traceId] !== undefined) return;

  loading.value = true;
  const { data } = await request<SqlTraceSession>({
    url: `/debug/sql-traces/${record.traceId}`
  });
  traceStore.setSession(record.traceId, data || null);
  loading.value = false;
}

async function clearAll() {
  await request<void>({
    url: '/debug/sql-traces',
    method: 'DELETE'
  });
  traceStore.clearRecords();
}

watch(
  () => [traceStore.drawerVisible, traceStore.selectedRecord?.traceId],
  () => {
    if (traceStore.drawerVisible) {
      loadSession(traceStore.selectedRecord);
    }
  },
  { immediate: false }
);
</script>

<template>
  <div v-if="traceStore.isAdmin" class="sql-trace-entry">
    <NButton circle type="primary" secondary title="SQL实时追踪" @click="traceStore.openDrawer()">
      <template #icon>
        <SvgIcon icon="mdi:database-search-outline" />
      </template>
    </NButton>
    <span v-if="traceStore.records.length" class="sql-trace-count">{{ traceStore.records.length }}</span>
  </div>

  <NDrawer v-model:show="traceStore.drawerVisible" :width="860" placement="right">
    <NDrawerContent title="SQL实时追踪" closable>
      <div class="trace-header-actions">
        <span>启用</span>
        <NSwitch v-model:value="traceStore.enabled" size="small" />
        <NButton size="tiny" @click="clearAll">清空</NButton>
      </div>

      <div class="trace-shell">
        <aside class="trace-list">
          <button
            v-for="record in traceStore.records"
            :key="record.id"
            class="trace-list-item"
            :class="{ active: record.id === traceStore.selectedRecordId }"
            type="button"
            @click="traceStore.openDrawer(record.id)"
          >
            <span class="trace-list-top">
              <b>{{ record.method }}</b>
              <em>{{ record.costMs ?? '-' }}ms</em>
            </span>
            <span class="trace-url">{{ shortUrl(record.url) }}</span>
            <span class="trace-meta">
              {{ formatTime(record.startedAt) }}
              <span v-if="record.traceId">SQL</span>
              <span v-if="record.errorMsg">失败</span>
            </span>
          </button>

          <NEmpty v-if="!traceStore.records.length" description="暂无追踪请求" />
        </aside>

        <main class="trace-detail">
          <NEmpty v-if="!traceStore.selectedRecord" description="选择一条请求查看详情" />

          <template v-else>
            <section class="trace-section">
              <div class="trace-section-title">前端传到后台的条件</div>
              <pre>{{ selectedPayload }}</pre>
            </section>

            <section class="trace-section">
              <div class="trace-section-title">后台 SQL</div>
              <NSpin :show="loading">
                <template v-if="selectedSession?.sqlDetails?.length">
                  <article v-for="sql in selectedSession.sqlDetails" :key="sql.seqNo" class="sql-card">
                    <div class="sql-card-head">
                      <b>#{{ sql.seqNo }} {{ sql.sqlType }}</b>
                      <span>{{ sql.costMs }}ms · {{ sql.affectedRows ?? '-' }} rows · {{ sql.status }}</span>
                    </div>
                    <pre>{{ sql.sqlText }}</pre>
                    <p v-if="sql.errorMsg" class="sql-error">{{ sql.errorMsg }}</p>
                  </article>
                </template>
                <NEmpty v-else description="这条请求没有捕获到 SQL" />
              </NSpin>
            </section>
          </template>
        </main>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.sql-trace-entry {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 3000;
}

.sql-trace-count {
  position: absolute;
  right: -6px;
  top: -8px;
  min-width: 18px;
  height: 18px;
  border-radius: 9px;
  background: #f43f5e;
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}

.trace-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.trace-shell {
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr);
  gap: 14px;
  height: calc(100vh - 120px);
}

.trace-list {
  min-width: 0;
  overflow: auto;
  border-right: 1px solid var(--n-border-color);
  padding-right: 10px;
}

.trace-list-item {
  width: 100%;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 10px;
  margin-bottom: 8px;
  text-align: left;
  cursor: pointer;
}

.trace-list-item.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.trace-list-top,
.trace-meta,
.sql-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.trace-list-top em,
.trace-meta,
.sql-card-head span {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

.trace-url {
  display: block;
  overflow: hidden;
  margin: 6px 0;
  color: #111827;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-detail {
  min-width: 0;
  overflow: auto;
}

.trace-section {
  margin-bottom: 16px;
}

.trace-section-title {
  margin-bottom: 8px;
  color: #111827;
  font-size: 14px;
  font-weight: 600;
}

pre {
  overflow: auto;
  max-height: 260px;
  margin: 0;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #f8fafc;
  padding: 10px;
  color: #0f172a;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.sql-card {
  margin-bottom: 10px;
}

.sql-card-head {
  margin-bottom: 6px;
}

.sql-error {
  margin: 6px 0 0;
  color: #dc2626;
  font-size: 12px;
}
</style>
