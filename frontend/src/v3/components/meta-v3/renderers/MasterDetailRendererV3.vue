<script setup lang="ts">
import MasterDetailLayoutV3 from '@/v3/components/MasterDetailLayoutV3.vue';
import type { PageComponentWithRules } from '@/v3/composables/meta-v3/types';

defineProps<{
  component: PageComponentWithRules;
  runtime: any;
}>();
</script>

<template>
  <MasterDetailLayoutV3 :runtime="runtime" />
</template>
