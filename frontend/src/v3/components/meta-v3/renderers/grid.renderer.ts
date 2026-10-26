import MetaGridV3 from '@/v3/components/meta-v3/renderers/MetaGridV3.vue';
import { registerComponentRenderer } from '@/v3/composables/meta-v3/component-renderer-registry';

export function register(): void {
  registerComponentRenderer({
    key: 'grid-default',
    componentType: 'GRID',
    order: 100,
    renderer: MetaGridV3
  });
}
