<script setup lang="ts">
import { type Component, computed, defineAsyncComponent, h, markRaw, shallowRef, watch } from 'vue';
import { useRoute } from 'vue-router';
import { router } from '@/router';
import { useAppStore } from '@/store/modules/app';
import { useTabStore } from '@/store/modules/tab';

defineOptions({
  name: 'GlobalContent'
});

interface Props {
  showPadding?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  showPadding: true
});

const appStore = useAppStore();
const tabStore = useTabStore();

/**
 * 已挂载的 tab 组件实例缓存
 * key = tab.id, value = 解析后的组件
 */
const mountedTabs = shallowRef<Map<string, Component>>(new Map());

/** 根据 tab 的 routeKey 从 router 中解析出对应的视图组件 */
function resolveTabComponent(tab: App.Global.Tab): Component | null {
  const routes = router.getRoutes();
  const matched = routes.find(r => r.name === tab.routeKey);
  if (!matched) return null;

  const comp = matched.components?.default;
  if (!comp) return null;

  // 动态页面（有 pageCode）：包装组件，固定传入 pageCode prop
  if (tab.pageCode) {
    const pageCode = tab.pageCode;
    const asyncComp = typeof comp === 'function' ? defineAsyncComponent(comp as () => Promise<any>) : comp;
    return markRaw({
      name: `tab-${tab.id}`,
      setup() {
        return () => h(asyncComp as Component, { pageCode });
      }
    });
  }

  // 非动态页面，直接使用
  if (typeof comp === 'function') {
    return markRaw(defineAsyncComponent(comp as () => Promise<any>));
  }
  return markRaw(comp as Component);
}

/** 确保 tab 对应的组件已挂载 */
function ensureTabMounted(tab: App.Global.Tab) {
  const map = mountedTabs.value;
  if (map.has(tab.id)) return;

  const comp = resolveTabComponent(tab);
  if (comp) {
    const newMap = new Map(map);
    newMap.set(tab.id, comp);
    mountedTabs.value = newMap;
  }
}

/** 清理已关闭 tab 的组件 */
function cleanClosedTabs(currentTabIds: Set<string>) {
  const map = mountedTabs.value;
  let changed = false;
  const newMap = new Map<string, Component>();
  for (const [id, comp] of map) {
    if (currentTabIds.has(id)) {
      newMap.set(id, comp);
    } else {
      changed = true;
    }
  }
  if (changed) {
    mountedTabs.value = newMap;
  }
}

// 监听 tabs 变化，挂载新 tab、清理已关闭 tab
watch(
  () => tabStore.tabs,
  tabs => {
    const tabIds = new Set(tabs.map(t => t.id));
    const activeTab = tabs.find(t => t.id === tabStore.activeTabId);
    if (activeTab) {
      ensureTabMounted(activeTab);
    }
    cleanClosedTabs(tabIds);
  },
  { immediate: true }
);

// 当 activeTabId 变化时，确保对应 tab 已挂载
watch(
  () => tabStore.activeTabId,
  () => {
    const activeTab = tabStore.tabs.find(t => t.id === tabStore.activeTabId);
    if (activeTab) {
      ensureTabMounted(activeTab);
    }
  },
  { immediate: true }
);

/** 判断 tab 是否需要 padding */
function tabNeedsPadding(tab: App.Global.Tab) {
  if (tab.pageCode) return false;
  return props.showPadding;
}

/** 获取已挂载的 tab 列表 */
const renderedTabs = computed(() => {
  const map = mountedTabs.value;
  const result: { id: string; component: Component; tab: App.Global.Tab }[] = [];
  for (const tab of tabStore.tabs) {
    const comp = map.get(tab.id);
    if (comp) {
      result.push({ id: tab.id, component: comp, tab });
    }
  }
  return result;
});

/** 是否处于 tab 模式（有活跃 tab 且 tab 已初始化） */
const useTabMode = computed(() => Boolean(tabStore.activeTabId));
</script>

<template>
  <!-- 有活跃 tab 时：v-show 多实例模式 -->
  <div v-if="useTabMode" class="relative flex-grow bg-layout">
    <div
      v-for="item in renderedTabs"
      v-show="item.id === tabStore.activeTabId && appStore.reloadFlag"
      :key="item.id"
      :class="{ 'p-16px': tabNeedsPadding(item.tab) }"
      class="absolute inset-0 overflow-auto"
    >
      <component :is="item.component" class="h-full" />
    </div>
  </div>
  <!-- 无活跃 tab 时（登录页等）：传统 RouterView -->
  <RouterView v-else v-slot="{ Component: RouteComp }">
    <component :is="RouteComp" v-if="appStore.reloadFlag" class="flex-grow bg-layout" />
  </RouterView>
</template>

<style scoped></style>
