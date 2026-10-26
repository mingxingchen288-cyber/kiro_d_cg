<script setup lang="ts">
import { $t } from '@/locales';
</script>

<template>
  <NCard :bordered="false" class="card-wrapper">
    <h3 class="text-18px font-medium">{{ $t('system.title') }}</h3>
  </NCard>
</template>
