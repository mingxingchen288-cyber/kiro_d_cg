import { computed, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { defineStore } from 'pinia';
import { useLoading } from '@sa/hooks';
import { type CurrentUser, login as platformLogin, me as platformMe } from '@/service/platform';
import { useRouterPush } from '@/hooks/common/router';
import { localStg } from '@/utils/storage';
import { SetupStoreId } from '@/enum';
import { $t } from '@/locales';
import { useRouteStore } from '../route';
import { useTabStore } from '../tab';
import { beginAuthShutdown, clearAuthStorage, getToken, markAuthActivity, setAuthTokens } from './shared';

export const useAuthStore = defineStore(SetupStoreId.Auth, () => {
  const route = useRoute();
  const authStore = useAuthStore();
  const routeStore = useRouteStore();
  const tabStore = useTabStore();
  const { toLogin, redirectFromLogin } = useRouterPush(false);
  const { loading: loginLoading, startLoading, endLoading } = useLoading();

  const token = ref(getToken());

  const userInfo: Api.Auth.UserInfo = reactive({
    userId: '',
    userName: '',
    realName: '',
    departmentId: '',
    departmentName: '',
    roles: []
  });

  /** is super role in static route */
  const isStaticSuper = computed(() => {
    const { VITE_AUTH_ROUTE_MODE, VITE_STATIC_SUPER_ROLE } = import.meta.env;

    return VITE_AUTH_ROUTE_MODE === 'static' && userInfo.roles.includes(VITE_STATIC_SUPER_ROLE);
  });

  /** Is login */
  const isLogin = computed(() => Boolean(token.value));

  /** Reset auth store */
  async function resetStore(options?: { preserveRedirect?: boolean }) {
    const { preserveRedirect = true } = options || {};
    const shouldRedirectToLogin = !route.meta.constant;

    beginAuthShutdown();
    recordUserId();

    clearAuthStorage();

    authStore.$reset();

    tabStore.cacheTabs();
    tabStore.$reset();
    await routeStore.resetStore();

    if (shouldRedirectToLogin) {
      await toLogin(undefined, preserveRedirect ? undefined : null);
    }
  }

  /** Record the user ID of the previous login session Used to compare with the current user ID on next login */
  function recordUserId() {
    if (!userInfo.userId) {
      return;
    }

    // Store current user ID locally for next login comparison
    localStg.set('lastLoginUserId', userInfo.userId);
  }

  /**
   * Check if current login user is different from previous login user If different, clear all tabs
   *
   * @returns {boolean} Whether to clear all tabs
   */
  function checkTabClear(): boolean {
    if (!userInfo.userId) {
      return false;
    }

    const lastLoginUserId = localStg.get('lastLoginUserId');

    // Clear all tabs if current user is different from previous user
    if (!lastLoginUserId || lastLoginUserId !== userInfo.userId) {
      localStg.remove('globalTabs');
      tabStore.clearTabs();

      localStg.remove('lastLoginUserId');
      return true;
    }

    localStg.remove('lastLoginUserId');
    return false;
  }

  /**
   * Login
   *
   * @param userName User name
   * @param password Password
   * @param [redirect=true] Whether to redirect after login. Default is `true`
   */
  async function login(userName: string, password: string, redirect = true) {
    startLoading();

    try {
      // C09 第 2 节：会话放在 HttpOnly Cookie 中，csrfToken 存进会话存储，旧外壳用它判断是否已登录
      const result = await platformLogin(userName, password);
      setSession(result.csrfToken, result.user, result.selectedRole ? [result.selectedRole.code] : []);

      // Check if the tab needs to be cleared
      const isClear = checkTabClear();
      let needRedirect = redirect;

      if (isClear) {
        // If the tab needs to be cleared,it means we don't need to redirect.
        needRedirect = false;
      }
      await redirectFromLogin(needRedirect);

      window.$notification?.success({
        title: $t('page.login.common.loginSuccess'),
        content: $t('page.login.common.welcomeBack', { userName: userInfo.realName || userInfo.userName }),
        duration: 4500
      });
    } catch (error) {
      window.$message?.error(error instanceof Error ? error.message : String(error));
      resetStore();
    }

    endLoading();
  }

  function setSession(csrfToken: string, user: CurrentUser, roles: string[]) {
    setAuthTokens(csrfToken, '');
    token.value = csrfToken;
    Object.assign(userInfo, {
      userId: user.userId,
      userName: user.username,
      realName: user.displayName,
      departmentId: user.departmentId || '',
      roles
    });
  }

  async function getUserInfo() {
    try {
      const info = await platformMe();
      setSession(info.csrfToken, info.user, info.role ? [info.role.code] : []);
      return true;
    } catch {
      return false;
    }
  }

  async function initUserInfo() {
    const hasToken = getToken();

    if (hasToken) {
      markAuthActivity(true);
      const pass = await getUserInfo();

      if (!pass) {
        resetStore();
        return false;
      }

      return true;
    }

    return false;
  }

  return {
    token,
    userInfo,
    isStaticSuper,
    isLogin,
    loginLoading,
    resetStore,
    login,
    initUserInfo
  };
});
