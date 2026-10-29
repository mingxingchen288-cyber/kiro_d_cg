import type { Router } from 'vue-router';
import { useTitle } from '@vueuse/core';
import { useRouteStore } from '@/store/modules/route';
import { $t } from '@/locales';

/** 浏览器标题：菜单项的标题（例如"成本核算"），没有对应菜单时用路由标题 */
export function createDocumentTitleGuard(router: Router) {
  router.afterEach(to => {
    const { i18nKey, title } = to.meta;

    const menuTitle = useRouteStore().menuTitleOfPath(to.path);
    const documentTitle = menuTitle || (i18nKey ? $t(i18nKey) : title);

    useTitle(documentTitle);
  });
}
