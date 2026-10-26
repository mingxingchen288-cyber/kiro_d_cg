import type { Component } from 'vue';

const renderersByKey = new Map<string, Component>();

export function registerFormRenderer(key: string, renderer: Component): void {
  if (!key || !renderer) return;
  renderersByKey.set(key, renderer);
}

export function resolveFormRenderer(key?: string | null): Component | null {
  if (!key) return null;
  return renderersByKey.get(key) || null;
}
