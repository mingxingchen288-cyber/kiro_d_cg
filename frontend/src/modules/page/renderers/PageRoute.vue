<script setup lang="ts">
/**
 * `/page/:pageCode` 的路由组件：页面编码来自路由参数，在创建时取一次。
 * 外壳按页签直接挂载组件（不经 RouterView），非活动页签中的当前路由会变，所以页面编码不随路由变化。
 *
 * 地址带 `?record=<主键>`（C11 v3，审批待办的"原单据"）时定位到这张单据（FP-20）：只在当前路由就是本页面时处理
 * （其他页签的路由变化不管），每次带 `record` 的跳转都定位一次。
 */
import { ref, watch } from "vue";
import { useRoute } from "vue-router";
import { usePageShell } from "../index";
import GenericPage from "./GenericPage.vue";

defineOptions({ name: "PageRoute" });

const props = defineProps<{ pageCode?: string }>();
const route = useRoute();
const pageCode = props.pageCode || String(route.params.pageCode ?? "");
const shell = usePageShell();

/** 要定位的单据；`seq` 每次跳转加一，同一张单据再点一次"原单据"也重新定位 */
const focus = ref<{ record: string; seq: number } | null>(null);

watch(
  () => route.fullPath,
  () => {
    if (
      route.name !== "page" ||
      String(route.params.pageCode ?? "") !== pageCode
    )
      return;
    const record = route.query.record;
    const key = Array.isArray(record) ? record[0] : record;
    if (key)
      focus.value = { record: String(key), seq: (focus.value?.seq ?? 0) + 1 };
  },
  { immediate: true },
);
</script>

<template>
  <GenericPage
    v-if="pageCode"
    :key="pageCode"
    :page-code="pageCode"
    :shell="shell"
    :focus="focus"
  />
  <div v-else class="h-full flex-center text-#999">缺少页面编码</div>
</template>
