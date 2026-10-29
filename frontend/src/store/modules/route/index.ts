/**
 * 路由和菜单：
 * - 路由：elegant 按 src/views 生成的静态路由（登录、403/404/500、首页），加上各前端模块的路由（C11，挂在主布局下）；
 *   模块提供了同名路由的（`page`），用模块的路由。
 * - 菜单：首页、外壳的固定入口"待办"，以及 `GET /api/me` 返回的菜单（modules/shell/menus.ts）。
 */
import { nextTick, ref, shallowRef, watch } from 'vue';
import type { RouteRecordRaw } from 'vue-router';
import { defineStore } from 'pinia';
import { useBoolean } from '@sa/hooks';
import type { ElegantConstRoute, LastLevelRouteKey, RouteKey, RouteMap } from '@elegant-router/types';
import { router } from '@/router';
import { useSvgIcon } from '@/hooks/common/icon';
import { SetupStoreId } from '@/enum';
import { createStaticRoutes, getAuthVueRoutes } from '@/router/routes';
import { layouts } from '@/router/elegant/imports';
import { getRouteName } from '@/router/elegant/transform';
import { shellRuntime } from '@/modules/shell/app';
import { type ShellMenu, buildMenus, menuOfKey, menuOfPath, todoMenu } from '@/modules/shell/menus';
import { useTabStore } from '../tab';
import {
  getCacheRouteNames,
  getGlobalMenusByAuthRoutes,
  getSelectedMenuKeyPathByKey,
  isRouteExistByRouteName,
  sortRoutesByOrder,
  updateLocaleOfGlobalMenus
} from './shared';

export const useRouteStore = defineStore(SetupStoreId.Route, () => {
  const tabStore = useTabStore();
  const { session, registry } = shellRuntime();
  const { SvgIconVNode } = useSvgIcon();
  const { bool: isInitConstantRoute, setBool: setIsInitConstantRoute } = useBoolean();
  const { bool: isInitAuthRoute, setBool: setIsInitAuthRoute } = useBoolean();

  /** Home route key */
  const routeHome = ref<LastLevelRouteKey>(import.meta.env.VITE_ROUTE_HOME);

  /** constant routes */
  const constantRoutes = shallowRef<ElegantConstRoute[]>([]);

  /** auth routes */
  const authRoutes = shallowRef<ElegantConstRoute[]>([]);

  const removeRouteFns: (() => void)[] = [];

  /** Global menus（NMenu 用） */
  const menus = ref<App.Global.Menu[]>([]);

  /** 菜单和打开的路径（按 key、按路径查找用） */
  const menuIndex = shallowRef<ShellMenu[]>([]);

  /** Update global menus by locale */
  function updateGlobalMenusByLocale() {
    menus.value = updateLocaleOfGlobalMenus(menus.value);
  }

  /** Cache routes */
  const cacheRoutes = ref<RouteKey[]>([]);

  /**
   * Exclude cache routes
   *
   * for reset route cache
   */
  const excludeCacheRoutes = ref<RouteKey[]>([]);

  /**
   * Reset route cache
   *
   * @default router.currentRoute.value.name current route name
   * @param routeKey
   */
  async function resetRouteCache(routeKey?: RouteKey) {
    const routeName = routeKey || (router.currentRoute.value.name as RouteKey);
    excludeCacheRoutes.value.push(routeName);
    await nextTick();
    excludeCacheRoutes.value = [];
  }

  /** Reset store */
  async function resetStore() {
    const routeStore = useRouteStore();
    routeStore.$reset();
    resetVueRoutes();
    menuIndex.value = [];
    // after reset store, need to re-init constant route
    await initConstantRoute();
  }

  /** Reset vue routes */
  function resetVueRoutes() {
    removeRouteFns.forEach(fn => fn());
    removeRouteFns.length = 0;
  }

  /** init constant route */
  async function initConstantRoute() {
    if (isInitConstantRoute.value) return;
    constantRoutes.value = createStaticRoutes().constantRoutes;
    handleConstantAndAuthRoutes(false);
    setIsInitConstantRoute(true);
    tabStore.initHomeTab();
  }

  /** 会话就绪后：加上需要登录的路由（elegant 的首页、各模块的路由）和菜单 */
  async function initAuthRoute() {
    const overridden = new Set(registry.routeNames());
    authRoutes.value = createStaticRoutes().authRoutes.filter(route => !overridden.has(route.name));
    handleConstantAndAuthRoutes(true);
    setIsInitAuthRoute(true);
    tabStore.initHomeTab();
  }

  /** handle constant and auth routes */
  function handleConstantAndAuthRoutes(withModules: boolean) {
    const allRoutes = [...constantRoutes.value, ...authRoutes.value];
    const sortRoutes = sortRoutesByOrder(allRoutes);
    const vueRoutes = getAuthVueRoutes(sortRoutes);
    const moduleRoutes = withModules ? registry.layoutRoutes(layouts.base) : [];
    resetVueRoutes();
    addRoutesToVueRouter([...vueRoutes, ...moduleRoutes]);
    buildGlobalMenus(sortRoutes, withModules);
    cacheRoutes.value = getCacheRouteNames([...vueRoutes, ...moduleRoutes]);
  }

  function toGlobalMenu(menu: ShellMenu): App.Global.Menu {
    return {
      key: menu.key,
      label: menu.title,
      routeKey: menu.key as RouteKey,
      routePath: (menu.path ?? '') as RouteMap[RouteKey],
      icon: SvgIconVNode({ icon: menu.icon || import.meta.env.VITE_MENU_ICON, fontSize: 20 }),
      ...(menu.children?.length ? { children: menu.children.map(toGlobalMenu) } : {})
    };
  }

  /** 首页（elegant 路由）、"待办"、`/api/me` 的菜单 */
  function buildGlobalMenus(sortRoutes: ElegantConstRoute[], withModules: boolean) {
    const elegantMenus = getGlobalMenusByAuthRoutes(sortRoutes);
    const shellMenus: ShellMenu[] = [];
    if (withModules) {
      const todo = todoMenu(registry.modules);
      if (todo) shellMenus.push(todo);
      shellMenus.push(...buildMenus(session.menus.value, registry.modules));
    }
    menus.value = [...elegantMenus, ...shellMenus.map(toGlobalMenu)];
    menuIndex.value = [
      ...elegantMenus.map(menu => ({ key: menu.key, title: menu.label, path: menu.routePath as string })),
      ...shellMenus
    ];
  }

  // `/api/me` 的菜单变化时（核对会话后重新读取）更新菜单
  watch(
    () => session.menus.value,
    () => {
      if (isInitAuthRoute.value)
        buildGlobalMenus(sortRoutesByOrder([...constantRoutes.value, ...authRoutes.value]), true);
    }
  );

  /**
   * Add routes to vue router
   *
   * @param routes Vue routes
   */
  function addRoutesToVueRouter(routes: RouteRecordRaw[]) {
    routes.forEach(route => {
      removeRouteFns.push(router.addRoute(route));
    });
  }

  /**
   * Get is auth route exist
   *
   * @param routePath Route path
   */
  async function getIsAuthRouteExist(routePath: RouteMap[RouteKey]) {
    const routeName = getRouteName(routePath);
    if (!routeName) {
      return false;
    }
    const { authRoutes: staticAuthRoutes } = createStaticRoutes();
    return isRouteExistByRouteName(routeName, staticAuthRoutes);
  }

  /**
   * Get selected menu key path
   *
   * @param selectedKey Selected menu key
   */
  function getSelectedMenuKeyPath(selectedKey: string) {
    return getSelectedMenuKeyPathByKey(selectedKey, menus.value);
  }

  /** 点击菜单：打开菜单项的路径 */
  async function openMenu(key: string) {
    const path = menuOfKey(menuIndex.value, key)?.path;
    if (path) await router.push(path);
  }

  /** 当前路径对应的菜单 key（菜单高亮用） */
  function menuKeyOfPath(path: string) {
    return menuOfPath(menuIndex.value, path)?.key ?? null;
  }

  /** 路径正好是某个菜单项时，该菜单项的标题（页签、浏览器标题用） */
  function menuTitleOfPath(path: string) {
    const menu = menuOfPath(menuIndex.value, path);
    return menu?.path === path ? menu.title : null;
  }

  return {
    resetStore,
    routeHome,
    menus,
    updateGlobalMenusByLocale,
    cacheRoutes,
    excludeCacheRoutes,
    resetRouteCache,
    initConstantRoute,
    isInitConstantRoute,
    initAuthRoute,
    isInitAuthRoute,
    setIsInitAuthRoute,
    getIsAuthRouteExist,
    getSelectedMenuKeyPath,
    openMenu,
    menuKeyOfPath,
    menuTitleOfPath
  };
});
