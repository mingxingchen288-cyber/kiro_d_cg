import { request } from '../request';

/** get constant routes - 返回错误让框架使用静态路由 */
export function fetchGetConstantRoutes() {
  return Promise.resolve({ data: null, error: 'use static routes' });
}

/** get user routes */
export function fetchGetUserRoutes() {
  return request<Api.Route.UserRoute>({ url: '/route/getUserRoutes' });
}

/**
 * whether the route is exist
 *
 * @param routeName route name
 */
export function fetchIsRouteExist(routeName: string) {
  return request<boolean>({ url: '/route/isRouteExist', params: { routeName } });
}
