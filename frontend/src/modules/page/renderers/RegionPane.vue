<script setup lang="ts">
/**
 * 一个区域（主表区或某个明细区）：表格和这个区域的原地表单（FP-03），主表区和每个明细区都用它。
 * 表单打开时表格只设为不可见（滚动位置和选中行保留），表单显示在表格的位置；各区域的表单各自打开、关上，互不影响。
 */
import { computed } from 'vue';
import PageGrid from '../grid-adapter/PageGrid.vue';
import type { PageRuntime } from '../page-runtime';
import RecordForm from './RecordForm.vue';

defineOptions({ name: 'RegionPane' });

const props = defineProps<{
  runtime: PageRuntime;
  entity: string;
  /** 主表区：表格用服务端行模型 */
  master: boolean;
  /** 表格外层的 data-testid（端到端用例按 master-grid 找主表的表格） */
  gridTestId?: string;
}>();

const formOpen = computed(() => Boolean(props.runtime.state.forms[props.entity]));
</script>

<template>
  <div class="region-pane">
    <div :data-testid="gridTestId" class="absolute inset-0" :style="{ visibility: formOpen ? 'hidden' : 'visible' }">
      <PageGrid :runtime="runtime" :entity="entity" :master="master" />
    </div>
    <RecordForm v-if="formOpen" :runtime="runtime" :entity="entity" class="absolute inset-0" />
  </div>
</template>

<style scoped>
.region-pane {
  position: relative;
}
</style>
