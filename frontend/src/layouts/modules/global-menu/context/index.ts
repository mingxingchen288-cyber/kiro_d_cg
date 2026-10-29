/**
 * 菜单的选中和跳转。菜单来自 `/api/me`（modules/shell/menus.ts），菜单 key 不再是路由名称：
 * 选中项按当前路径找菜单（`routeStore.menuKeyOfPath`），一级、二级菜单按菜单的 key 路径找，点击按菜单的路径跳转（`routeStore.openMenu`）。
 * 所有通用页面共用 `/page/:pageCode` 一个路由，所以跟随路径变化，不跟随路由名称变化。
 */
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useContext } from '@sa/hooks';
import type { RouteKey } from '@elegant-router/types';
import { useRouteStore } from '@/store/modules/route';
import { useThemeStore } from '@/store/modules/theme';

export const [provideMixMenuContext, useMixMenuContext] = useContext('MixMenu', useMixMenu);

function useMixMenu() {
  const route = useRoute();
  const routeStore = useRouteStore();
  const themeStore = useThemeStore();
  const { selectedKey } = useMenu();

  const allMenus = computed<App.Global.Menu[]>(() => routeStore.menus);

  const firstLevelMenus = computed<App.Global.Menu[]>(() =>
    routeStore.menus.map(menu => {
      const { children: _, ...rest } = menu;

      return rest;
    })
  );

  const selectedKeyPath = computed(() => routeStore.getSelectedMenuKeyPath(selectedKey.value));

  const activeFirstLevelMenuKey = ref('');

  function setActiveFirstLevelMenuKey(key: string) {
    activeFirstLevelMenuKey.value = key;
  }

  function getActiveFirstLevelMenuKey() {
    setActiveFirstLevelMenuKey(selectedKeyPath.value[0] ?? selectedKey.value);
  }

  const isActiveFirstLevelMenuHasChildren = computed(() => {
    if (!activeFirstLevelMenuKey.value) {
      return false;
    }

    const findItem = allMenus.value.find(item => item.key === activeFirstLevelMenuKey.value);

    return Boolean(findItem?.children?.length);
  });

  function handleSelectFirstLevelMenu(key: RouteKey) {
    setActiveFirstLevelMenuKey(key);

    if (!isActiveFirstLevelMenuHasChildren.value) {
      routeStore.openMenu(key);
    }
  }

  const secondLevelMenus = computed<App.Global.Menu[]>(
    () => allMenus.value.find(menu => menu.key === activeFirstLevelMenuKey.value)?.children || []
  );

  const activeSecondLevelMenuKey = ref('');

  function setActiveSecondLevelMenuKey(key: string) {
    activeSecondLevelMenuKey.value = key;
  }

  function getActiveSecondLevelMenuKey() {
    setActiveSecondLevelMenuKey(selectedKeyPath.value[1] ?? '');
  }

  const isActiveSecondLevelMenuHasChildren = computed(() => {
    if (!activeSecondLevelMenuKey.value) {
      return false;
    }

    const findItem = secondLevelMenus.value.find(item => item.key === activeSecondLevelMenuKey.value);

    return Boolean(findItem?.children?.length);
  });

  function handleSelectSecondLevelMenu(key: RouteKey) {
    setActiveSecondLevelMenuKey(key);

    if (!isActiveSecondLevelMenuHasChildren.value) {
      routeStore.openMenu(key);
    }
  }

  const childLevelMenus = computed<App.Global.Menu[]>(
    () => secondLevelMenus.value.find(menu => menu.key === activeSecondLevelMenuKey.value)?.children || []
  );

  const hasChildLevelMenus = computed(() => childLevelMenus.value.length > 0);

  function getDeepestLevelMenuKey(): RouteKey | null {
    if (!secondLevelMenus.value.length || !themeStore.sider.autoSelectFirstMenu) {
      return null;
    }

    const secondLevelFirstMenu = secondLevelMenus.value[0];

    if (!secondLevelFirstMenu) {
      return null;
    }

    function findDeepest(menu: App.Global.Menu): RouteKey {
      if (!menu.children?.length) {
        return menu.routeKey;
      }

      return findDeepest(menu.children[0]);
    }

    return findDeepest(secondLevelFirstMenu);
  }

  function activeDeepestLevelMenuKey() {
    const deepestLevelMenuKey = getDeepestLevelMenuKey();
    if (!deepestLevelMenuKey) return;

    // select the deepest second level menu
    handleSelectSecondLevelMenu(deepestLevelMenuKey);
  }

  watch(
    () => route.path,
    () => {
      getActiveFirstLevelMenuKey();
      // if there are child level menus, get the active second level menu key
      if (hasChildLevelMenus.value) {
        getActiveSecondLevelMenuKey();
      }
    },
    { immediate: true }
  );

  return {
    firstLevelMenus,
    activeFirstLevelMenuKey,
    setActiveFirstLevelMenuKey,
    isActiveFirstLevelMenuHasChildren,
    handleSelectFirstLevelMenu,
    getActiveFirstLevelMenuKey,
    secondLevelMenus,
    activeSecondLevelMenuKey,
    setActiveSecondLevelMenuKey,
    isActiveSecondLevelMenuHasChildren,
    handleSelectSecondLevelMenu,
    getActiveSecondLevelMenuKey,
    childLevelMenus,
    hasChildLevelMenus,
    getDeepestLevelMenuKey,
    activeDeepestLevelMenuKey
  };
}

export function useMenu() {
  const route = useRoute();
  const routeStore = useRouteStore();

  const selectedKey = computed(() => {
    const menuKey = routeStore.menuKeyOfPath(route.path);
    if (menuKey) return menuKey;

    const { hideInMenu, activeMenu } = route.meta;
    const name = route.name as string;

    return (hideInMenu ? activeMenu : name) || name;
  });

  return {
    selectedKey
  };
}
