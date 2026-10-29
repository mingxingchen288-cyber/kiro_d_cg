<script setup lang="ts">
/**
 * 复制对话框（FP-13）：主表区复制一行时勾选主表字段，以及每个明细要复制的行和字段；明细区复制时勾选行（默认是表格中
 * 选中的行）和字段。默认全选，与旧系统相同。
 */
import { computed, reactive, watch } from 'vue';
import type { ViewRegion } from '../../../contracts/page-view';
import { copyableFields } from '../copy';
import { displayText } from '../fields';
import type { PageRuntime } from '../page-runtime';

defineOptions({ name: 'CopyDialog' });

const props = defineProps<{ runtime: PageRuntime }>();
const runtime = props.runtime;
const copy = computed(() => runtime.ui.copy.value);
const view = computed(() => runtime.view.value);
const isMaster = computed(() => copy.value?.entity === view.value?.master.entity);

const form = reactive({
  fields: [] as string[],
  rows: [] as string[],
  details: {} as Record<string, { rows: string[]; fields: string[] }>
});

watch(copy, value => {
  if (!value) return;
  form.fields = [...value.selection.fields];
  form.rows = [...value.rows];
  form.details = Object.fromEntries(
    Object.entries(value.selection.details ?? {}).map(([entity, d]) => [
      entity,
      { rows: [...d.rows], fields: [...d.fields] }
    ])
  );
});

/** 明细行的显示：取前三个可见字段的值 */
function rowLabel(region: ViewRegion, id: string) {
  const values = runtime.model.values(region.entity, id);
  return region.fields
    .filter(f => f.visible && f.name !== region.primaryKey)
    .slice(0, 3)
    .map(f => displayText(f, values[f.name] ?? null))
    .filter(Boolean)
    .join(' / ');
}

function detailRows(region: ViewRegion) {
  const recordId = copy.value?.recordId;
  if (!recordId) return [];
  return runtime.model
    .detailIds(region.entity, recordId)
    .filter(id => !runtime.model.buffer.isDeleted(region.entity, id));
}

const region = computed(() => (copy.value ? runtime.model.region(copy.value.entity) : undefined));

function confirm() {
  if (isMaster.value) void runtime.confirmCopy({ fields: form.fields, details: form.details });
  else void runtime.confirmCopy({ fields: form.fields }, form.rows);
}
</script>

<template>
  <NModal :show="Boolean(copy)" @update:show="(v: boolean) => !v && runtime.closeCopy()">
    <NCard
      v-if="copy && region && view"
      class="copy-dialog"
      title="复制"
      :bordered="false"
      size="small"
      closable
      @close="runtime.closeCopy()"
    >
      <div class="copy-dialog__body">
        <template v-if="isMaster">
          <div class="copy-dialog__title">{{ view.title }}：要复制的字段</div>
          <NCheckboxGroup v-model:value="form.fields">
            <NSpace>
              <NCheckbox v-for="f in copyableFields(view.master)" :key="f.name" :value="f.name" :label="f.label" />
            </NSpace>
          </NCheckboxGroup>
          <template v-for="detail in view.details" :key="detail.entity">
            <template v-if="form.details[detail.entity]">
              <NDivider title-placement="left">{{ detail.title }}</NDivider>
              <div class="copy-dialog__title">要复制的行</div>
              <NCheckboxGroup v-model:value="form.details[detail.entity].rows">
                <NSpace vertical>
                  <NCheckbox v-for="id in detailRows(detail)" :key="id" :value="id" :label="rowLabel(detail, id)" />
                </NSpace>
              </NCheckboxGroup>
              <div class="copy-dialog__title mt-8px">要复制的字段</div>
              <NCheckboxGroup v-model:value="form.details[detail.entity].fields">
                <NSpace>
                  <NCheckbox v-for="f in copyableFields(detail)" :key="f.name" :value="f.name" :label="f.label" />
                </NSpace>
              </NCheckboxGroup>
            </template>
          </template>
        </template>
        <template v-else>
          <div class="copy-dialog__title">要复制的行</div>
          <NCheckboxGroup v-model:value="form.rows">
            <NSpace vertical>
              <NCheckbox v-for="id in detailRows(region)" :key="id" :value="id" :label="rowLabel(region, id)" />
            </NSpace>
          </NCheckboxGroup>
          <div class="copy-dialog__title mt-8px">要复制的字段</div>
          <NCheckboxGroup v-model:value="form.fields">
            <NSpace>
              <NCheckbox v-for="f in copyableFields(region)" :key="f.name" :value="f.name" :label="f.label" />
            </NSpace>
          </NCheckboxGroup>
        </template>
      </div>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="runtime.closeCopy()">取消</NButton>
          <NButton type="primary" @click="confirm">确定</NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>

<style scoped>
.copy-dialog {
  width: 760px;
  max-width: calc(100vw - 100px);
}

.copy-dialog__body {
  max-height: 60vh;
  overflow: auto;
}

.copy-dialog__title {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}
</style>
