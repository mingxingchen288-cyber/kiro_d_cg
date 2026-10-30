<script setup lang="ts">
/**
 * 审批详情页（FA-01～FA-09），样式对照旧系统 `ApprovalDetailDialog.vue`：顶部"← 返回待办"、标题和状态，基本信息一行；
 * 卡片依次为审批进度、来源单据主表（审批中时带"待生效"）、修改明细（每张明细表一个卡片 Tab）、受影响单据（每块一个卡片 Tab，
 * 标题后显示条数）、处理（意见、人工参数、撤回 / 驳回 / 通过）。旧系统是全屏弹窗，这里是路由 `/approval/:approvalId` 的页面。
 * 旧系统折叠显示的"审批记录"（动作日志）在 C09 的审批详情中没有对应字段，各次处理的人、时间和意见在审批进度中显示。
 * 已结束的审批，修改内容为结束那一刻存下的值（C06 7.6）；结束时没有保存的（`viewUnsaved`），写明没有保存，对照旧系统
 * "该审批未保存修改内容展示数据"。
 */
import { computed, onMounted } from 'vue';
import type { ShellApi } from '../../../contracts/shell';
import { createPlatformApi } from '../../../contracts/api';
import { ApprovalDetailRuntime, type ParamValue } from '../detail-runtime';
import { detailPath } from '../todo-runtime';
import { formatTime, pageText, sourceText, statusLabel, type ViewAffectedTable } from '../view-model';
import ApprovalStepsGrid from './ApprovalStepsGrid.vue';
import ApprovalViewGrid from './ApprovalViewGrid.vue';

defineOptions({ name: 'ApprovalDetailPage' });

const props = defineProps<{ approvalId: string; shell: ShellApi }>();

const runtime = new ApprovalDetailRuntime(props.approvalId, {
  api: createPlatformApi(props.shell.http),
  message: props.shell.message
});
const { state } = runtime;
const detail = runtime.detail;
const view = runtime.view;

const pending = computed(() => detail.value?.status === 'pending');
/** 已结束的审批显示结束那一刻存下的修改内容；结束时没有保存的（C06 7.6），不显示修改内容，写明没有保存 */
const unsaved = computed(() => detail.value?.viewUnsaved === true);
const actions = computed(() => detail.value?.actions ?? { canPass: false, canReject: false, canWithdraw: false });
const hasActions = computed(() => actions.value.canPass || actions.value.canReject || actions.value.canWithdraw);
const busy = computed(() => state.loading || state.previewing || state.submitting);
const blocked = computed(() => busy.value || Boolean(state.error));
const flowNames = computed(() => runtime.flowNames());
const params = computed(() => (actions.value.canPass ? (detail.value?.params ?? []) : []));
const editable = computed(() => view.value?.affected.some(b => runtime.selectableKeys(b).length > 0) ?? false);
const selection = computed(() => runtime.selectionCount());

/** 受影响单据下方的说明（文字取自旧系统 objectSelectionHint，按新的勾选方式改写） */
const affectedHint = computed(() => {
  if (!pending.value) return '勾选状态为实际审批结果，只读不可修改。';
  if (!editable.value) return '当前仅可查看；所有级别审批完成后，勾选的行才会生效。';
  return '未勾选的行不写入；有勾选行的单据在通过后重算。后续级别只能在此前保留的行内再取消。';
});

function blockName(block: ViewAffectedTable) {
  return `${block.flow}:${block.key}`;
}

/** 各块的勾选、能勾选的主键和条数；放在 computed 中，输入意见时表格不重新取行 */
const blocks = computed(() => {
  const map = new Map<string, { checked: readonly string[]; selectable: string[]; count: number }>();
  for (const block of view.value?.affected ?? []) {
    map.set(blockName(block), {
      checked: runtime.checkedKeys(block),
      selectable: runtime.selectableKeys(block),
      count: runtime.groupCount(block)
    });
  }
  return map;
});

function paramValue(name: string) {
  return state.params[name] ?? null;
}

function setParam(name: string, value: ParamValue) {
  state.params[name] = value;
}

function back() {
  props.shell.tabs.open('/approval', '待办');
  props.shell.tabs.close(detailPath(props.approvalId));
}

onMounted(() => {
  void runtime.load();
});
</script>

<template>
  <div class="approval-detail-page" role="region" aria-label="审批详情">
    <header class="approval-detail-header">
      <NButton text type="primary" :disabled="state.submitting" @click="back">← 返回待办</NButton>
      <h1>审批详情</h1>
      <template v-if="detail">
        <span class="approval-source">{{ pageText(detail) }} · 来源单据 {{ sourceText(detail.source) }}</span>
        <span class="approval-status">{{ statusLabel(detail) }}</span>
      </template>
    </header>
    <div v-if="detail" class="approval-information" aria-label="基本信息">
      <span>
        来自页面：
        <b>{{ pageText(detail) }}</b>
      </span>
      <span>
        来源单据号：
        <b>{{ sourceText(detail.source) }}</b>
      </span>
      <span>
        提交人：
        <b>{{ detail.applicant.displayName }}</b>
      </span>
      <span>
        提交时间：
        <b>{{ formatTime(detail.submittedAt) }}</b>
      </span>
      <span>
        当前级别：
        <b>第 {{ detail.currentLevel }} 级</b>
      </span>
      <span>
        审批编号：
        <b>{{ detail.approvalId }}</b>
      </span>
    </div>
    <main class="approval-detail-body">
      <NAlert v-if="state.error" type="error" :bordered="false" class="mb-8px">
        {{ state.error }}
        <NButton size="small" class="ml-8px" :disabled="state.submitting" @click="runtime.load()">重新读取详情</NButton>
      </NAlert>
      <NAlert v-if="state.reconfirm" type="warning" :bordered="false" class="mb-8px">
        审批内容已变化，已重新读取详情。请核对修改内容和勾选后再次确认。
      </NAlert>
      <NSpin :show="state.loading">
        <section class="approval-card">
          <h2>
            审批进度
            <NTooltip>
              <template #trigger>
                <button type="button" class="approval-help" aria-label="审批进度说明">ⓘ</button>
              </template>
              各流程按配置推进，全部通过后统一生效
            </NTooltip>
          </h2>
          <ApprovalStepsGrid :steps="detail?.steps ?? []" />
        </section>

        <section v-if="unsaved" class="approval-card" aria-label="修改内容">
          <h2>修改内容</h2>
          <NAlert type="warning" :bordered="false">
            这个审批结束时的修改前、修改后的值没有保存，无法显示修改内容。
          </NAlert>
        </section>

        <template v-if="view && !unsaved">
          <section class="approval-card">
            <h2>
              {{ view.master.title || '主表变更' }}
              <span v-if="pending" class="approval-pending-badge">待生效</span>
              <NTooltip>
                <template #trigger>
                  <button type="button" class="approval-help" aria-label="修改内容说明">ⓘ</button>
                </template>
                {{ pending ? '修改后的值为本次待审修改按计算规则重算的结果，尚未生效' : '显示审批结束时的修改前、修改后的值' }}
              </NTooltip>
            </h2>
            <ApprovalViewGrid kind="master" :columns="view.master.columns" :rows="view.master.rows" />
          </section>

          <section v-if="view.details.length" class="approval-card">
            <NTabs
              type="card"
              size="small"
              class="approval-section-tabs"
              :tab-style="{ padding: '4px 10px' }"
              :pane-style="{ paddingTop: '6px' }"
            >
              <template #prefix>
                <h2>
                  修改明细
                  <NTooltip>
                    <template #trigger>
                      <button type="button" class="approval-help" aria-label="明细显示说明">ⓘ</button>
                    </template>
                    A → B 表示修改前后；新增只显示新值，删除保留原值。触发审批列显示此行实际命中的流程。
                  </NTooltip>
                </h2>
              </template>
              <NTabPane
                v-for="table in view.details"
                :key="table.key"
                :name="table.key"
                :tab="`${table.title}（${table.rows.length}）`"
              >
                <ApprovalViewGrid kind="detail" :columns="table.columns" :rows="table.rows" :flow-names="flowNames" />
              </NTabPane>
            </NTabs>
          </section>

          <section v-if="view.affected.length" class="approval-card">
            <NTabs
              type="card"
              size="small"
              class="approval-section-tabs"
              :tab-style="{ padding: '4px 10px' }"
              :pane-style="{ paddingTop: '6px' }"
            >
              <template #prefix>
                <h2>
                  受影响单据
                  <NTooltip>
                    <template #trigger>
                      <button type="button" class="approval-help" aria-label="受影响单据说明">ⓘ</button>
                    </template>
                    按修改的记录勾选，同一记录的几行共用一个勾选框；改了勾选后按勾选重新计算修改后的值
                  </NTooltip>
                </h2>
              </template>
              <NTabPane
                v-for="block in view.affected"
                :key="blockName(block)"
                :name="blockName(block)"
                :tab="`${block.title}（${blocks.get(blockName(block))?.count ?? 0} 条）`"
              >
                <ApprovalViewGrid
                  kind="affected"
                  :columns="block.columns"
                  :rows="block.rows"
                  :checked-keys="blocks.get(blockName(block))?.checked"
                  :selectable-keys="blocks.get(blockName(block))?.selectable"
                  :disabled="busy || Boolean(state.error)"
                  @toggle="(key: string, value: boolean) => runtime.toggle(block, key, value)"
                  @toggle-all="(value: boolean) => runtime.toggleAll(block, value)"
                />
              </NTabPane>
            </NTabs>
            <p class="approval-hint">
              {{ affectedHint }}
              <span v-if="state.previewing">正在按勾选重新计算…</span>
            </p>
          </section>
        </template>

        <section v-if="hasActions" class="approval-card approval-decision" aria-label="审批处理">
          <div class="approval-comment">
            <label>
              审批意见
              <small>驳回时必填</small>
            </label>
            <NInput
              v-model:value="state.comment"
              type="textarea"
              placeholder="请输入意见…"
              :autosize="{ minRows: 2, maxRows: 6 }"
              :disabled="state.submitting"
            />
          </div>
          <NForm v-if="params.length" class="approval-parameters" label-placement="left" label-width="100" size="small">
            <p class="approval-hint approval-parameters-hint">通过时填写：</p>
            <NFormItem
              v-for="param in params"
              :key="param.name"
              :label="param.label || param.name"
              :required="param.required"
            >
              <NInputNumber
                v-if="param.type === 'number'"
                :value="typeof paramValue(param.name) === 'number' ? (paramValue(param.name) as number) : null"
                :disabled="state.submitting"
                clearable
                @update:value="(v: number | null) => setParam(param.name, v)"
              />
              <NSwitch
                v-else-if="param.type === 'boolean'"
                :value="paramValue(param.name) === true"
                :disabled="state.submitting"
                @update:value="(v: boolean) => setParam(param.name, v)"
              />
              <NDatePicker
                v-else-if="param.type === 'date'"
                :formatted-value="typeof paramValue(param.name) === 'string' ? (paramValue(param.name) as string) : null"
                type="date"
                value-format="yyyy-MM-dd"
                :disabled="state.submitting"
                clearable
                @update:formatted-value="(v: string | null) => setParam(param.name, v)"
              />
              <NInput
                v-else
                :value="typeof paramValue(param.name) === 'string' ? (paramValue(param.name) as string) : ''"
                :disabled="state.submitting"
                :placeholder="param.label || param.name"
                @update:value="(v: string) => setParam(param.name, v)"
              />
            </NFormItem>
          </NForm>
          <p v-if="actions.canPass && selection.total > 0" class="approval-hint">
            已勾选 {{ selection.checked }} / {{ selection.total }} 条可审批的记录。
          </p>
          <div class="approval-footer-actions">
            <NButton v-if="actions.canWithdraw" :disabled="blocked" @click="runtime.withdraw()">撤回</NButton>
            <NButton v-if="actions.canReject" type="error" ghost :disabled="blocked" @click="runtime.reject()">
              驳回
            </NButton>
            <NButton
              v-if="actions.canPass"
              type="primary"
              :loading="state.submitting"
              :disabled="blocked"
              @click="runtime.pass()"
            >
              通过
            </NButton>
          </div>
        </section>
      </NSpin>
    </main>
  </div>
</template>

<style scoped>
.approval-detail-page {
  width: 100%;
  height: 100%;
  background: #f6f9fc;
  color: #173153;
  font-size: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.approval-detail-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 46px;
  padding: 6px 14px;
  background: #fff;
  border-bottom: 1px solid #e7ebf1;
}
h1 {
  margin: 0;
  color: #0a192f;
  font-size: 16px;
  font-weight: 700;
  white-space: nowrap;
}
.approval-source {
  min-width: 0;
  overflow-wrap: anywhere;
}
.approval-status {
  color: #6962ff;
  background: #f3f1ff;
  border: 1px solid #dbd6ff;
  border-radius: 15px;
  padding: 3px 8px;
  white-space: nowrap;
}
.approval-footer-actions .n-button {
  min-width: 68px;
}
.approval-detail-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 10px 12px;
}
.approval-card {
  background: #fff;
  border: 1px solid #e2e7ed;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
  min-width: 0;
}
h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
  margin: 0 0 5px;
  font-size: 13px;
  color: #0a192f;
  font-weight: 650;
}
.approval-help {
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: #657896;
  font-size: 14px;
  line-height: 20px;
  cursor: pointer;
}
.approval-pending-badge {
  padding: 1px 6px;
  border-radius: 3px;
  background: #fff7e6;
  color: #a36510;
  font-size: 12px;
  font-weight: 400;
}
.approval-information {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 5px 24px;
  padding: 8px 14px;
  border-bottom: 1px solid #e7ebf1;
  background: #fff;
  color: #657896;
}
.approval-information b {
  color: #173153;
  font-weight: 400;
}
.approval-section-tabs :deep(.n-tabs-nav__prefix) {
  padding-right: 12px;
}
.approval-section-tabs h2 {
  margin: 0;
  white-space: nowrap;
}
.approval-decision {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px 12px;
}
.approval-comment {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  grid-column: 1;
  align-items: center;
}
.approval-comment small {
  color: #e96b6b;
  display: block;
}
.approval-parameters {
  grid-column: 1 / -1;
  max-width: 620px;
}
.approval-parameters-hint {
  margin: 0 0 6px;
}
.approval-footer-actions {
  display: flex;
  grid-column: 2;
  grid-row: 1;
  gap: 8px;
  justify-content: flex-end;
}
.approval-hint {
  color: #657896;
  margin: 6px 0 0;
  line-height: 1.5;
}
.approval-decision > .approval-hint {
  grid-column: 1 / -1;
  margin: 0;
}
@media (max-width: 850px) {
  .approval-detail-header {
    flex-wrap: wrap;
    gap: 8px;
    padding: 8px 14px;
  }
  .approval-information {
    gap: 5px 16px;
  }
  .approval-source {
    flex-basis: 100%;
    order: 1;
  }
  .approval-decision {
    grid-template-columns: minmax(0, 1fr);
  }
  .approval-footer-actions {
    grid-column: 1;
    grid-row: auto;
  }
  h2 {
    flex-wrap: wrap;
    gap: 5px;
  }
}
</style>
