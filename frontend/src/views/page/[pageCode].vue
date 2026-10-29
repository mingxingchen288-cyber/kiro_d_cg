<script setup lang="ts">
/**
 * 通用页面的路由入口 `/page/:pageCode`（elegant-router 按本文件生成路由）。所有页面都由这一个视图按页面编码打开，
 * 内容是 frontend-page 模块的通用页面；不为单个页面加视图文件。
 *
 * assembly 按 C11 注册 frontend-page 之前（T-AS-3），这里用 `src/service/shell.ts` 的过渡 ShellApi 调用 install。
 */
import { interimShell } from '@/service/shell';
import { isPageModuleInstalled, pageModule } from '@/modules/page';
import PageRoute from '@/modules/page/renderers/PageRoute.vue';

defineOptions({ name: 'PageView' });

defineProps<{ pageCode?: string }>();

if (!isPageModuleInstalled()) pageModule.install(interimShell());
</script>

<template>
  <PageRoute :page-code="pageCode" />
</template>
