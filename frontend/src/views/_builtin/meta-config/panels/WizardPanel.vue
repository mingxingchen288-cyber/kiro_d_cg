<script setup lang="ts">
import { computed, ref } from 'vue';
import { NButton, NSpace, NSteps, NStep, useMessage } from 'naive-ui';
import { useRouter } from 'vue-router';
import { useWizardState, validateStep1, validateStep2 } from './composables/useWizardState';
import WizardStep1 from './components/WizardStep1.vue';
import WizardStep2 from './components/WizardStep2.vue';
import WizardStep3 from './components/WizardStep3.vue';
import { useRouteStore } from '@/store/modules/route';

const props = withDefaults(defineProps<{
  defaultParentId?: number | null;
  defaultParentName?: string;
}>(), {
  defaultParentId: null,
  defaultParentName: ''
});

const emit = defineEmits<{
  (e: 'success'): void;
}>();

const router = useRouter();
const routeStore = useRouteStore();
const message = useMessage();

const {
  state,
  canGoNext,
  goNext,
  goPrev,
  addDetailTable,
  removeDetailTable,
  resetStep2OnModeChange,
  buildPayload
} = useWizardState();

// 初始化时用传入的默认值填充归属菜单
if (props.defaultParentId) {
  state.step1.parentId = props.defaultParentId;
  state.step1.parentName = props.defaultParentName || '';
}

const step1Errors = ref<string[]>([]);
const step2Errors = ref<string[]>([]);

function handleNext() {
  if (state.currentStep === 1) {
    const errors = validateStep1(state.step1);
    if (errors.length > 0) {
      step1Errors.value = errors.map(e => e.message);
      message.warning(errors[0].message);
      return;
    }
    step1Errors.value = [];
  }
  if (state.currentStep === 2) {
    const errors = validateStep2(state.step2);
    if (errors.length > 0) {
      step2Errors.value = errors.map(e => e.message);
      message.warning(errors[0].message);
      return;
    }
    step2Errors.value = [];
  }
  goNext();
}

const payload = computed(() => {
  if (state.currentStep === 3) {
    return buildPayload();
  }
  return null;
});

async function handleSuccess(pageCode: string) {
  // Refresh routes and menu
  try {
    await routeStore.initAuthRoute();
  } catch {
    // ignore route refresh errors
  }

  // 通知父组件刷新目录树
  emit('success');

  // 从路由表里按 meta.pageCode 找真实路由路径
  const allRoutes = router.getRoutes();
  const matched = allRoutes.find(r => (r.meta as any)?.pageCode === pageCode);
  const targetPath = matched?.path || null;

  if (targetPath) {
    try {
      await router.push(targetPath);
      return;
    } catch {
      // fall through to manual link
    }
  }

  // 降级：显示提示
  message.info(`生成成功！页面编码: ${pageCode}，请从左侧菜单进入或刷新页面后访问。`);
}
</script>

<template>
  <div class="wizard-panel">
    <!-- Steps indicator -->
    <NSteps :current="state.currentStep" class="wizard-steps">
      <NStep title="页面菜单" />
      <NStep title="导入表与配置字段" />
      <NStep title="确认生成" />
    </NSteps>

    <!-- Step content -->
    <div class="wizard-content">
      <WizardStep1 v-if="state.currentStep === 1" :step1="state.step1" />
      <WizardStep2
        v-else-if="state.currentStep === 2"
        :step1="state.step1"
        :step2="state.step2"
        @mode-change="resetStep2OnModeChange"
        @add-detail="addDetailTable"
        @remove-detail="removeDetailTable"
      />
      <WizardStep3
        v-else-if="state.currentStep === 3 && payload"
        :payload="payload"
        @success="handleSuccess"
      />
    </div>

    <!-- Navigation buttons -->
    <div class="wizard-nav">
      <NSpace>
        <NButton v-if="state.currentStep > 1" @click="goPrev">上一步</NButton>
        <NButton v-if="state.currentStep < 3" type="primary" @click="handleNext">下一步</NButton>
      </NSpace>
    </div>
  </div>
</template>

<style scoped>
.wizard-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 0;
}
.wizard-steps {
  flex-shrink: 0;
  margin-bottom: 24px;
  max-width: 600px;
}
.wizard-content {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.wizard-nav {
  flex-shrink: 0;
  padding-top: 16px;
  border-top: 1px solid #e8e8e8;
}
</style>
