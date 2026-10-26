import MetaButtonV3 from '@/v3/components/meta-v3/renderers/MetaButtonV3.vue';
import { registerComponentRenderer } from '@/v3/composables/meta-v3/component-renderer-registry';

export function register(): void {
  registerComponentRenderer({
    key: 'button-default',
    componentType: 'BUTTON',
    order: 100,
    renderer: MetaButtonV3
  });
}
