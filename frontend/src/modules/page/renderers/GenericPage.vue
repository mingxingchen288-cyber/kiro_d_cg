<script setup lang="ts">
/**
 * 通用页面：按页面编码打开，列、明细、按钮、规则都来自页面视图（C05），不为单个页面写专门的组件。
 * 单表页只有主表区；主从页在主表区下面显示明细区，明细按 Tab 或堆叠显示，分隔线可以拖动（FP-01，旧系统为 NSplit，默认各一半）。
 * 页面行为都在 page-runtime 中，这里只负责布局和把操作交给它。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import type { ViewButton, ViewRegion } from '../../../contracts/page-view';
import { createPlatformApi } from '../../../contracts/api';
import type { ShellApi } from '../../../contracts/shell';
import PageGrid from '../grid-adapter/PageGrid.vue';
import { PageRuntime } from '../page-runtime';
import AdvancedSearchDialog from './AdvancedSearchDialog.vue';
import ApprovalProgressDialog from './ApprovalProgressDialog.vue';
import CopyDialog from './CopyDialog.vue';
import LookupDialog from './LookupDialog.vue';
import RecordForm from './RecordForm.vue';

defineOptions({ name: 'GenericPage' });

const props = defineProps<{ pageCode: string; shell: ShellApi }>();

const path = `/page/${props.pageCode}`;
const runtime = new PageRuntime(props.pageCode, {
  api: createPlatformApi(props.shell.http),
  calc: props.shell.calc,
  realtime: props.shell.realtime,
  session: props.shell.session,
  message: props.shell.message,
  tabs: props.shell.tabs,
  path
});
const state = runtime.state;
const view = computed(() => {
  void state.viewVersion;
  return runtime.view.value;
});
const showAdvanced = ref(false);

const canSave = computed(() => Boolean(view.value?.systemButtons.includes('save')));
const canAdvanced = computed(() => Boolean(view.value?.systemButtons.includes('advancedSearch')));
const masterDetail = computed(() =>
  Boolean(view.value && view.value.layout === 'masterDetail' && view.value.details.length)
);
const activeDetail = computed(
  () => view.value?.details.find(d => d.entity === state.activeDetail) ?? view.value?.details[0]
);

function buttons(region: ViewRegion) {
  void state.viewVersion;
  return runtime.regionButtons(region);
}

function enabled(region: ViewRegion, button: ViewButton) {
  void state.selected;
  void state.activeRecord;
  void state.saving;
  return runtime.buttonEnabled(region, button);
}

function buttonType(button: ViewButton) {
  if (button.action === 'addRow') return 'primary';
  if (button.action === 'deleteRow') return 'error';
  return 'default';
}

function onKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null;
  // 输入框和单元格编辑器中按浏览器自己的撤销
  if (target?.closest('input, textarea, [contenteditable="true"], .ag-cell-inline-editing')) return;
  const key = event.key.toLowerCase();
  if (!(event.ctrlKey || event.metaKey)) return;
  if (key === 'z' && !event.shiftKey) {
    event.preventDefault();
    runtime.undo();
  } else if (key === 'y' || (key === 'z' && event.shiftKey)) {
    event.preventDefault();
    runtime.redo();
  }
}

/** FP-12：有未保存修改时，刷新或关闭窗口前浏览器先确认 */
function onBeforeUnload(event: BeforeUnloadEvent) {
  if (!runtime.dirty) return;
  event.preventDefault();
  event.returnValue = '';
}

onMounted(() => {
  window.addEventListener('beforeunload', onBeforeUnload);
  void runtime.load();
});

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload);
  runtime.dispose();
});
</script>

<template>
  <div class="generic-page h-full flex-col" tabindex="-1" @keydown="onKeydown">
    <div v-if="state.status === 'error'" class="flex-center flex-1 text-error">{{ state.error }}</div>
    <NSpin v-else-if="state.status === 'loading'" class="flex-center flex-1" />
    <template v-else-if="view">
      <div class="generic-page__toolbar flex-y-center gap-8px">
        <span class="text-15px font-medium">{{ view.title }}</span>
        <NSpace size="small">
          <NButton
            v-if="canSave"
            size="small"
            :disabled="state.dirtyCount === 0"
            :loading="state.saving"
            @click="runtime.save()"
          >
            保存
          </NButton>
          <NButton v-if="canAdvanced" size="small" :disabled="state.saving" @click="showAdvanced = true">
            高级查询
          </NButton>
          <NButton
            v-for="button in buttons(view.master)"
            :key="button.key"
            size="small"
            :type="buttonType(button)"
            :disabled="!enabled(view.master, button)"
            @click="runtime.clickButton(view.master, button)"
          >
            {{ button.label }}
          </NButton>
        </NSpace>
        <span v-if="state.saving" class="text-12px text-#999">保存中…</span>
        <span v-else-if="state.dirtyCount > 0" class="text-12px text-#999">{{ state.dirtyCount }} 行未保存</span>
        <span v-if="runtime.ui.advanced.value" class="text-12px text-primary">已按高级查询筛选</span>
        <span v-if="state.previewError" class="text-12px text-warning">{{ state.previewError }}</span>
        <span v-if="state.error" class="text-12px text-error">{{ state.error }}</span>
      </div>
      <div v-if="runtime.ui.effects.value.length" class="generic-page__effects">
        <span
          v-for="(effect, index) in runtime.ui.effects.value"
          :key="index"
          :class="effect.kind === 'reject' ? 'text-error' : 'text-warning'"
        >
          {{ effect.message }}
        </span>
      </div>
      <div class="min-h-0 flex-1">
        <NSplit v-if="masterDetail" direction="vertical" :default-size="0.5" :min="0.15" :max="0.85" class="h-full">
          <template #1>
            <div class="generic-page__master">
              <div
                data-testid="master-grid"
                class="absolute inset-0"
                :style="{ visibility: state.formRecord ? 'hidden' : 'visible' }"
              >
                <PageGrid :runtime="runtime" :entity="view.master.entity" master />
              </div>
              <RecordForm v-if="state.formRecord" :runtime="runtime" class="absolute inset-0" />
            </div>
          </template>
          <template #2>
            <div class="generic-page__detail h-full flex-col">
              <div class="generic-page__detail-bar flex-y-center gap-8px">
                <NTabs
                  v-if="state.detailMode === 'tabs'"
                  :value="state.activeDetail"
                  type="line"
                  size="small"
                  class="flex-1"
                  @update:value="(v: string) => (state.activeDetail = v)"
                >
                  <NTab v-for="d in view.details" :key="d.entity" :name="d.entity" :tab="d.title" />
                </NTabs>
                <span v-else class="flex-1 text-13px text-#64748b">明细</span>
                <NSpace v-if="state.detailMode === 'tabs' && activeDetail" size="small">
                  <NButton
                    v-for="button in buttons(activeDetail)"
                    :key="button.key"
                    size="tiny"
                    :type="buttonType(button)"
                    :disabled="!enabled(activeDetail, button)"
                    @click="runtime.clickButton(activeDetail, button)"
                  >
                    {{ button.label }}
                  </NButton>
                </NSpace>
                <NRadioGroup
                  size="small"
                  :value="state.detailMode"
                  @update:value="(v: 'tabs' | 'stack') => runtime.setDetailMode(v)"
                >
                  <NRadioButton value="tabs">Tab</NRadioButton>
                  <NRadioButton value="stack">堆叠</NRadioButton>
                </NRadioGroup>
              </div>
              <div class="relative min-h-0 flex-1" :class="{ 'generic-page__stack': state.detailMode === 'stack' }">
                <div v-if="!state.activeRecord" class="generic-page__empty">选中主表的一行后显示这张单据的明细</div>
                <div
                  v-for="d in view.details"
                  v-show="state.activeRecord && (state.detailMode === 'stack' || d.entity === activeDetail?.entity)"
                  :key="d.entity"
                  :data-testid="`detail-${d.entity}`"
                  class="generic-page__detail-grid"
                >
                  <div v-if="state.detailMode === 'stack'" class="flex-y-center gap-8px py-4px">
                    <span class="text-13px font-medium">{{ d.title }}</span>
                    <NButton
                      v-for="button in buttons(d)"
                      :key="button.key"
                      size="tiny"
                      :type="buttonType(button)"
                      :disabled="!enabled(d, button)"
                      @click="runtime.clickButton(d, button)"
                    >
                      {{ button.label }}
                    </NButton>
                  </div>
                  <div class="min-h-0 flex-1">
                    <PageGrid :runtime="runtime" :entity="d.entity" :master="false" />
                  </div>
                </div>
              </div>
            </div>
          </template>
        </NSplit>
        <div v-else class="generic-page__master h-full">
          <div
            data-testid="master-grid"
            class="absolute inset-0"
            :style="{ visibility: state.formRecord ? 'hidden' : 'visible' }"
          >
            <PageGrid :runtime="runtime" :entity="view.master.entity" master />
          </div>
          <RecordForm v-if="state.formRecord" :runtime="runtime" class="absolute inset-0" />
        </div>
      </div>
      <LookupDialog :runtime="runtime" />
      <CopyDialog :runtime="runtime" />
      <ApprovalProgressDialog :runtime="runtime" />
      <AdvancedSearchDialog v-if="canAdvanced" v-model:show="showAdvanced" :runtime="runtime" />
    </template>
  </div>
</template>

<style scoped>
.generic-page {
  outline: none;
}

.generic-page__toolbar {
  padding: 4px 0 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.generic-page__effects {
  display: flex;
  gap: 12px;
  font-size: 12px;
  padding-bottom: 4px;
}

.generic-page__master {
  position: relative;
  height: 100%;
}

.generic-page__detail-bar {
  min-height: 32px;
  flex-shrink: 0;
}

.generic-page__detail-grid {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
}

.generic-page__stack {
  overflow: auto;
}

.generic-page__stack .generic-page__detail-grid {
  position: relative;
  inset: auto;
  height: 300px;
  margin-bottom: 12px;
}

.generic-page__empty {
  height: 100px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 13px;
}
</style>
