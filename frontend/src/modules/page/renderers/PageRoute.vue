<script setup lang="ts">
/**
 * `/page/:pageCode` 的路由组件：页面编码来自路由参数，在创建时取一次。
 * 外壳按页签直接挂载组件（不经 RouterView），非活动页签中的当前路由会变，所以不随路由变化。
 */
import { useRoute } from 'vue-router';
import { usePageShell } from '../index';
import GenericPage from './GenericPage.vue';

defineOptions({ name: 'PageRoute' });

const props = defineProps<{ pageCode?: string }>();
const route = useRoute();
const pageCode = props.pageCode || String(route.params.pageCode ?? '');
const shell = usePageShell();
</script>

<template>
  <GenericPage v-if="pageCode" :key="pageCode" :page-code="pageCode" :shell="shell" />
  <div v-else class="h-full flex-center text-#999">缺少页面编码</div>
</template>
