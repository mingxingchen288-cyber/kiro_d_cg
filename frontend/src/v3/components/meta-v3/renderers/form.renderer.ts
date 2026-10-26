import MetaFormV3 from '@/v3/components/meta-v3/renderers/MetaFormV3.vue';
import { registerComponentRenderer } from '@/v3/composables/meta-v3/component-renderer-registry';

export function register(): void {
  registerComponentRenderer({
    key: 'form-default',
    componentType: 'FORM',
    order: 100,
    renderer: MetaFormV3
  });
}
