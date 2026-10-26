import LayoutRenderer from '@/v3/components/meta-v3/renderers/LayoutRenderer.vue';
import { registerComponentRenderer } from '@/v3/composables/meta-v3/component-renderer-registry';

export function register(): void {
  registerComponentRenderer({
    key: 'layout-default',
    componentType: 'LAYOUT',
    order: 100,
    renderer: LayoutRenderer
  });
}
