<script setup lang="ts">
import { computed, ref } from 'vue';
import { NButton, NCollapse, NCollapseItem, NModal, NTag, useMessage } from 'naive-ui';
import { generateWizard } from '@/service/api/wizard';
import type { WizardPayload } from '@/service/api/wizard';

const props = defineProps<{
  payload: WizardPayload;
}>();

const emit = defineEmits<{
  (e: 'success', pageCode: string): void;
}>();

const message = useMessage();
const generating = ref(false);

// 错误弹窗状态
const showErrorModal = ref(false);
const errorSummary = ref('');
const errorDetail = ref<{ message?: string; oraCode?: string; sql?: string; detail?: string; rootCause?: string } | null>(null);

const masterColCount = computed(() => props.payload.masterTable?.columns?.length || 0);
const detailColCounts = computed(() =>
  (props.payload.detailTables || []).map(dt => ({
    name: dt.tableName || dt.tableCode,
    count: dt.columns?.length || 0,
    real: dt.columns?.filter(c => c.isVirtual === 0).length || 0,
    virtual: dt.columns?.filter(c => c.isVirtual === 1).length || 0
  }))
);
const masterReal = computed(() => props.payload.masterTable?.columns?.filter(c => c.isVirtual === 0).length || 0);
const masterVirtual = computed(() => props.payload.masterTable?.columns?.filter(c => c.isVirtual === 1).length || 0);
const totalEntities = computed(() => {
  let count = 1; // resource
  count += 1; // master table metadata
  count += (props.payload.detailTables || []).length; // detail table metadatas
  count += masterColCount.value; // master columns
  for (const dt of props.payload.detailTables || []) {
    count += dt.columns?.length || 0;
  }
  count += 1 + (props.payload.detailTables || []).length + 1; // components (root + master + details)
  count += 1 + (props.payload.detailTables || []).length; // page rules
  return count;
});

async function handleGenerate() {
  generating.value = true;
  errorSummary.value = '';
  errorDetail.value = null;
  try {
    const result = await generateWizard(props.payload);
    if (result) {
      message.success(`生成成功，共创建 ${result.createdCount} 条记录`);
      emit('success', result.pageCode);
    }
  } catch (e: any) {
    errorSummary.value = e?.message || '生成失败，请重试';
    errorDetail.value = e?.detail || null;
    showErrorModal.value = true;
  } finally {
    generating.value = false;
  }
}
</script>

<template>
  <div class="wizard-step3">
    <h3 class="manifest-title">生成清单</h3>

    <!-- 目录 -->
    <div class="manifest-section">
      <h4>📁 目录 (1 项)</h4>
      <p class="manifest-item">{{ payload.resourceName }} ({{ payload.resourceCode }})</p>
    </div>

    <!-- 表元数据 -->
    <div class="manifest-section">
      <h4>📋 表元数据 ({{ 1 + (payload.detailTables || []).length }} 项)</h4>
      <p class="manifest-item">
        <NTag size="small" type="info">主表</NTag>
        {{ payload.masterTable.tableName || payload.masterTable.tableCode }}
        ({{ payload.masterTable.tableCode }})
      </p>
      <p v-for="(dt, idx) in payload.detailTables" :key="idx" class="manifest-item">
        <NTag size="small" type="warning">从表</NTag>
        {{ dt.tableName || dt.tableCode }} ({{ dt.tableCode }})
      </p>
    </div>

    <!-- 页面组件 -->
    <div class="manifest-section">
      <h4>🧩 页面组件 ({{ 2 + (payload.detailTables || []).length }} 项)</h4>
      <p class="manifest-item">root (LAYOUT)</p>
      <p class="manifest-item">{{ payload.masterTable.tableCode }} (GRID → {{ payload.masterTable.tableCode }})</p>
      <p v-for="(dt, idx) in payload.detailTables" :key="idx" class="manifest-item">
        {{ dt.tableCode }} (DETAIL_GRID → {{ dt.tableCode }})
      </p>
    </div>

    <!-- 列配置 -->
    <div class="manifest-section">
      <h4>📊 列配置 ({{ masterColCount + detailColCounts.reduce((s, d) => s + d.count, 0) }} 列)</h4>
      <p class="manifest-item">
        {{ payload.masterTable.tableName || payload.masterTable.tableCode }}:
        {{ masterColCount }} 列 ({{ masterReal }} 真实, {{ masterVirtual }} 虚拟)
      </p>
      <p v-for="(dt, idx) in detailColCounts" :key="idx" class="manifest-item">
        {{ dt.name }}: {{ dt.count }} 列 ({{ dt.real }} 真实, {{ dt.virtual }} 虚拟)
      </p>
    </div>

    <!-- 按钮配置 -->
    <div class="manifest-section">
      <h4>🔘 按钮配置</h4>
      <p class="manifest-item">主表: 新增、删除、保存、保存列配置</p>
      <p v-for="(dt, idx) in payload.detailTables" :key="idx" class="manifest-item">
        {{ dt.tableName || dt.tableCode }}: 明细新增、明细删除、保存列配置
      </p>
    </div>

    <!-- 主从关系 -->
    <div v-if="payload.mode === 'master-detail'" class="manifest-section">
      <h4>🔗 主从关系</h4>
      <p v-for="(dt, idx) in payload.detailTables" :key="idx" class="manifest-item">
        {{ payload.masterTable.tableCode }}.{{ payload.masterTable.pkColumn }}
        → {{ dt.tableCode }}.{{ dt.parentFkColumn }}
      </p>
    </div>

    <!-- 总计 -->
    <div class="manifest-total">
      预计创建 <strong>{{ totalEntities }}</strong> 条记录，页面编码：<code>{{ payload.pageCode }}</code>
    </div>

    <!-- Error display -->
    <div v-if="errorSummary && !showErrorModal" class="error-message">{{ errorSummary }}</div>

    <!-- 错误详情弹窗 -->
    <NModal v-model:show="showErrorModal" preset="card" title="生成失败" :style="{ width: '600px' }">
      <div class="error-modal-content">
        <p class="error-summary">{{ errorSummary }}</p>
        <NCollapse v-if="errorDetail">
          <NCollapseItem title="查看详情" name="detail">
            <div class="error-detail">
              <p v-if="errorDetail.oraCode"><strong>ORA 错误码：</strong>{{ errorDetail.oraCode }}</p>
              <p v-if="errorDetail.sql"><strong>报错 SQL：</strong></p>
              <pre v-if="errorDetail.sql" class="error-pre">{{ errorDetail.sql }}</pre>
              <p v-if="errorDetail.message"><strong>错误信息：</strong>{{ errorDetail.message }}</p>
              <p v-if="errorDetail.rootCause"><strong>根因：</strong></p>
              <pre v-if="errorDetail.rootCause" class="error-pre">{{ errorDetail.rootCause }}</pre>
            </div>
          </NCollapseItem>
        </NCollapse>
      </div>
      <template #footer>
        <NButton @click="showErrorModal = false">关闭</NButton>
      </template>
    </NModal>

    <!-- Generate button -->
    <div class="generate-actions">
      <NButton type="primary" size="large" :loading="generating" :disabled="generating" @click="handleGenerate">
        ✓ 确认生成
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.wizard-step3 {
  padding: 8px 0;
  max-width: 700px;
}
.manifest-title {
  margin: 0 0 16px;
}
.manifest-section {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #fafafa;
  border-radius: 4px;
}
.manifest-section h4 {
  margin: 0 0 4px;
  font-size: 14px;
}
.manifest-item {
  margin: 2px 0;
  padding-left: 16px;
  font-size: 13px;
  color: #555;
}
.manifest-total {
  margin: 16px 0;
  padding: 8px 12px;
  background: #e6f7ff;
  border-radius: 4px;
  font-size: 14px;
}
.error-message {
  margin: 8px 0;
  padding: 8px;
  background: #fff2f0;
  border: 1px solid #ffccc7;
  border-radius: 4px;
  color: #d03050;
}
.error-modal-content {
  padding: 4px 0;
}
.error-summary {
  font-size: 14px;
  color: #d03050;
  margin-bottom: 12px;
}
.error-detail p {
  margin: 4px 0;
  font-size: 13px;
}
.error-pre {
  background: #f5f5f5;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
  padding: 8px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}
.generate-actions {
  margin-top: 16px;
  text-align: center;
}
</style>
