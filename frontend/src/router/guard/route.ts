/**
 * 路由守卫：按外壳的会话状态（modules/shell/session.ts）决定去向。
 * - 没有登录：只能打开登录、403/404/500，其他页面转到登录页并带回跳地址；
 * - 已登录、还没选角色：登录页显示选角色一步，其他页面转到登录页；
 * - 已选定角色：登录页转到首页；第一次进入时加上需要登录的路由和菜单（首页、各模块的路由、`/api/me` 的菜单）。
 * 刷新页面后第一次导航时，用 `/api/me` 恢复会话。
 */
import type {
  LocationQueryRaw,
  NavigationGuardNext,
  RouteLocationNormalized,
  RouteLocationRaw,
  Router
} from 'vue-router';
import type { RouteKey, RoutePath } from '@elegant-router/types';
import { useRouteStore } from '@/store/modules/route';
import { shellRuntime } from '@/modules/shell/app';
import { getRouteName } from '@/router/elegant/transform';

let restored = false;

/**
 * create route guard
 *
 * @param router router instance
 */
export function createRouteGuard(router: Router) {
  router.beforeEach(async (to, from, next) => {
    const location = await initRoute(to);

    if (location) {
      next(location);
      return;
    }

    const rootRoute: RouteKey = 'root';
    const loginRoute: RouteKey = 'login';
    const status = shellRuntime().session.status.value;

    // 登录页：已选定角色时转到首页；没有登录时显示密码登录，还没选角色时显示选角色
    if (to.name === loginRoute) {
      if (status === 'ready') next({ name: rootRoute });
      else next();
      return;
    }

    // if the route does not need login, then it is allowed to access directly
    if (to.meta.constant) {
      handleRouteSwitch(to, from, next);
      return;
    }

    if (status !== 'ready') {
      next({ name: loginRoute, query: { redirect: to.fullPath } });
      return;
    }

    // switch route normally
    handleRouteSwitch(to, from, next);
  });
}

/**
 * initialize route
 *
 * @param to to route
 */
async function initRoute(to: RouteLocationNormalized): Promise<RouteLocationRaw | null> {
  const routeStore = useRouteStore();

  const notFoundRoute: RouteKey = 'not-found';
  const isNotFoundRoute = to.name === notFoundRoute;

  // if the constant route is not initialized, then initialize the constant route
  if (!routeStore.isInitConstantRoute) {
    await routeStore.initConstantRoute();

    // the route is captured by the "not-found" route because the constant route is not initialized
    // after the constant route is initialized, redirect to the original route
    const path = to.fullPath;
    const location: RouteLocationRaw = {
      path,
      replace: true,
      query: to.query,
      hash: to.hash
    };

    return location;
  }

  const { session } = shellRuntime();
  if (!restored) {
    restored = true;
    await session.restore();
  }

  if (session.status.value !== 'ready') {
    // 没有登录或还没选角色：登录页、403/404/500 可以打开，其他转到登录页
    if (to.meta.constant && !isNotFoundRoute) {
      return null;
    }

    const loginRoute: RouteKey = 'login';
    const query = getRouteQueryOfLoginRoute(to, routeStore.routeHome);

    const location: RouteLocationRaw = {
      name: loginRoute,
      query
    };

    return location;
  }

  if (!routeStore.isInitAuthRoute) {
    // initialize the auth route
    await routeStore.initAuthRoute();

    // the route is captured by the "not-found" route because the auth route is not initialized
    // after the auth route is initialized, redirect to the original route
    if (isNotFoundRoute) {
      const rootRoute: RouteKey = 'root';
      const path = to.redirectedFrom?.name === rootRoute ? '/' : to.fullPath;

      const location: RouteLocationRaw = {
        path,
        replace: true,
        query: to.query,
        hash: to.hash
      };

      return location;
    }
  }

  // the auth route is initialized
  // it is not the "not-found" route, then it is allowed to access
  if (!isNotFoundRoute) {
    return null;
  }

  // it is captured by the "not-found" route, then check whether the route exists
  const exist = await routeStore.getIsAuthRouteExist(to.path as RoutePath);
  const noPermissionRoute: RouteKey = '403';

  if (exist) {
    const location: RouteLocationRaw = {
      name: noPermissionRoute
    };

    return location;
  }

  return null;
}

function handleRouteSwitch(to: RouteLocationNormalized, from: RouteLocationNormalized, next: NavigationGuardNext) {
  // route with href
  if (to.meta.href) {
    window.open(to.meta.href, '_blank');

    next({ path: from.fullPath, replace: true, query: from.query, hash: to.hash });

    return;
  }

  next();
}

function getRouteQueryOfLoginRoute(to: RouteLocationNormalized, routeHome: RouteKey) {
  const loginRoute: RouteKey = 'login';
  const redirect = to.fullPath;
  const [redirectPath, redirectQuery] = redirect.split('?');
  const redirectName = getRouteName(redirectPath as RoutePath);

  const isRedirectHome = routeHome === redirectName;

  const query: LocationQueryRaw = to.name !== loginRoute && !isRedirectHome ? { redirect } : {};

  if (isRedirectHome && redirectQuery) {
    query.redirect = `/?${redirectQuery}`;
  }

  return query;
}
