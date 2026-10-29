<script setup lang="ts">
/** 校验错误列表（FC-02）：每条写出配置项、位置（path）和原因 */
import { NAlert } from 'naive-ui';
import { CONFIG_TYPE_LABELS, type ConfigType } from '../core/types';
import type { ConfigProblem } from '../core/errors';

defineProps<{ problems: ConfigProblem[] }>();

const where = (p: ConfigProblem) =>
  [p.configType ? CONFIG_TYPE_LABELS[p.configType as ConfigType] ?? p.configType : '', p.configKey ?? '', p.path ?? ''].filter(Boolean).join(' · ');
</script>

<template>
  <NAlert v-if="problems.length" type="error" :bordered="false" title="校验不通过，没有保存" class="problem-list">
    <div v-for="(p, i) in problems" :key="i">
      <span v-if="where(p)" class="where">{{ where(p) }}：</span>{{ p.message }}
    </div>
  </NAlert>
</template>

<style scoped>
.problem-list { margin: 8px 0; }
.where { color: #d03050; font-family: monospace; }
</style>
