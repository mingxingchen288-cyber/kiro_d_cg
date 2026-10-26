import MasterDetailRendererV3 from '@/v3/components/meta-v3/renderers/MasterDetailRendererV3.vue';
import { registerComponentRenderer } from '@/v3/composables/meta-v3/component-renderer-registry';

export function register(): void {
  registerComponentRenderer({
    key: 'master-detail-default',
    componentType: 'MASTER_DETAIL',
    order: 100,
    renderer: MasterDetailRendererV3
  });
}
