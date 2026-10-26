import type { Component } from 'vue';
import type { PageComponentWithRules } from '@/v3/composables/meta-v3/types';

export type ComponentRendererContext = {
  component: PageComponentWithRules;
  runtime: any;
};

export type ComponentRendererDefinition = {
  key: string;
  componentType: string;
  order?: number;
  match?: (context: ComponentRendererContext) => boolean;
  renderer: Component;
};

const renderersByType = new Map<string, ComponentRendererDefinition[]>();

export function registerComponentRenderer(definition: ComponentRendererDefinition): void {
  const list = renderersByType.get(definition.componentType) || [];
  list.push(definition);
  list.sort((a, b) => {
    const orderDiff = (a.order ?? 0) - (b.order ?? 0);
    if (orderDiff !== 0) return orderDiff;
    return a.key.localeCompare(b.key);
  });
  renderersByType.set(definition.componentType, list);
}

export function resolveComponentRenderer(context: ComponentRendererContext): Component | null {
  const type = context.component.componentType;
  const list = renderersByType.get(type) || [];
  for (const renderer of list) {
    if (!renderer.match || renderer.match(context)) return renderer.renderer;
  }
  return null;
}
