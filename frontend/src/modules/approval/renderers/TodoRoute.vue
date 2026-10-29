<script setup lang="ts">
/** `/approval` 的路由组件：待办列表（外壳固定入口"待办"，C11）。 */
import { useApprovalShell } from '../index';
import ApprovalTodoPage from './ApprovalTodoPage.vue';

defineOptions({ name: 'ApprovalTodoRoute' });

const shell = useApprovalShell();
</script>

<template>
  <ApprovalTodoPage :shell="shell" />
</template>
