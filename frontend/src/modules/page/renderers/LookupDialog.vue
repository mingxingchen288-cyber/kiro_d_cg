<script setup lang="ts">
/**
 * Lookup 对话框（FP-15）：布局沿用旧系统 LookupDialog.vue（标题、"输入关键字搜索"、结果表格、取消/确定，宽 1050）。
 * 打开时先用空关键字查询；`keywordSearch` 为 false 时不显示搜索框；只查看的 Lookup（fillBack 为 false）只有"关闭"。
 */
import { computed, ref, shallowRef, watch } from 'vue';
import type { FieldValues } from '../../../contracts/command';
import LookupGrid from '../grid-adapter/LookupGrid.vue';
import type { PageRuntime } from '../page-runtime';

defineOptions({ name: 'LookupDialog' });

const props = defineProps<{ runtime: PageRuntime }>();
const runtime = props.runtime;
const lookup = computed(() => runtime.ui.lookup.value);
/**
 * 卡片显示的内容：关闭后保留最后一次的 Lookup。NModal 关闭时有离场动画，动画期间仍渲染默认插槽，
 * 卡片若随 Lookup 一起移除，naive-ui 会报"[naive/modal]: default slot is empty"。
 */
const shown = shallowRef(lookup.value);
watch(lookup, value => {
  if (value) shown.value = value;
});
const keyword = ref('');
const selected = ref<FieldValues[]>([]);

watch(
  () => lookup.value?.field,
  () => {
    keyword.value = '';
    selected.value = [];
  }
);

function close() {
  runtime.closeLookup();
}

function confirm() {
  runtime.confirmLookup(selected.value);
}

function pick(row: FieldValues) {
  runtime.confirmLookup([row]);
}
</script>

<template>
  <NModal
    :show="Boolean(lookup)"
    :mask-closable="true"
    :close-on-esc="true"
    @update:show="(v: boolean) => !v && close()"
  >
    <NCard
      v-if="shown"
      class="lookup-dialog"
      :title="shown.title || '选择'"
      :bordered="false"
      size="small"
      closable
      role="dialog"
      @close="close"
    >
      <div v-if="shown.keywordSearch" class="mb-12px">
        <NInput
          v-model:value="keyword"
          placeholder="输入关键字搜索"
          clearable
          @keyup.enter="runtime.searchLookup(keyword)"
        />
      </div>
      <div class="lookup-dialog__grid">
        <NSpin :show="shown.loading" class="h-full">
          <LookupGrid
            :rows="shown.rows"
            :multiple="shown.multiple"
            :columns="shown.columns"
            @selection="(rows: FieldValues[]) => (selected = rows)"
            @pick="pick"
          />
        </NSpin>
      </div>
      <div class="mt-8px text-12px text-#999">
        共 {{ shown.total }} 条
        <span v-if="shown.error" class="ml-8px text-error">{{ shown.error }}</span>
      </div>
      <template #footer>
        <NSpace justify="end">
          <template v-if="shown.fillBack">
            <NButton @click="close">取消</NButton>
            <NButton type="primary" :disabled="selected.length === 0" @click="confirm">确定</NButton>
          </template>
          <NButton v-else @click="close">关闭</NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>

<style scoped>
.lookup-dialog {
  width: 1050px;
  max-width: calc(100vw - 100px);
}

.lookup-dialog__grid {
  height: 420px;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
  overflow: hidden;
}

.lookup-dialog__grid :deep(.n-spin-content) {
  height: 100%;
}
</style>
