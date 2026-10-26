<script setup lang="ts">
import { computed } from 'vue';
import type { CSSProperties } from 'vue';
import MetaPageRendererV3 from '@/v3/components/meta-v3/renderers/MetaPageRendererV3.vue';
import type { PageComponentWithRules } from '@/v3/composables/meta-v3/types';

type LayoutConfig = {
  direction?: 'vertical' | 'horizontal';
  gap?: number | string;
  align?: string;
  justify?: string;
  width?: string | number;
  height?: string | number;
  flex?: string | number;
  className?: string;
  fill?: boolean;
};

const props = defineProps<{
  component: PageComponentWithRules;
  runtime: any;
}>();

function parseLayoutConfig(config?: string): LayoutConfig {
  if (!config) return {};
  try {
    return JSON.parse(config) as LayoutConfig;
  } catch (error) {
    console.warn('[MetaV3] layout config parse failed', error);
    return {};
  }
}

function toCssSize(value?: string | number) {
  if (value == null) return undefined;
  return typeof value === 'number' ? `${value}px` : value;
}

const layoutClass = computed(() => {
  const config = parseLayoutConfig(props.component.componentConfig);
  return config.className || '';
});

const layoutStyle = computed<CSSProperties>(() => {
  const config = parseLayoutConfig(props.component.componentConfig);
  const gap = config.gap != null ? (typeof config.gap === 'number' ? `${config.gap}px` : config.gap) : undefined;
  const isRoot = !props.component.parentKey;
  const fill = config.fill ?? isRoot;
  return {
    display: 'flex',
    flexDirection: config.direction === 'horizontal' ? 'row' : 'column',
    gap,
    alignItems: config.align,
    justifyContent: config.justify,
    width: toCssSize(config.width) || '100%',
    height: toCssSize(config.height) || (fill ? '100%' : undefined),
    flex: config.flex as CSSProperties['flex']
  } as CSSProperties;
});
</script>

<template>
  <div class="meta-layout" :class="layoutClass" :style="layoutStyle">
    <MetaPageRendererV3 :components="component.children || []" :runtime="runtime" />
  </div>
</template>

<style scoped>
.meta-layout {
  width: 100%;
}
</style>
