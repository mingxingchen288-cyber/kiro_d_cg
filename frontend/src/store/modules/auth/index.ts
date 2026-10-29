/**
 * 登录状态（外壳的会话 `ShellSession` 的界面一侧）：登录、选角色、注销、改密码，以及会话变化时的页签、路由和跳转。
 * 会话的规则见 src/modules/shell/session.ts（FS-02）。
 */
import { computed } from 'vue';
import { defineStore } from 'pinia';
import { useLoading } from '@sa/hooks';
import { router } from '@/router';
import { useRouterPush } from '@/hooks/common/router';
import { localStg } from '@/utils/storage';
import { shellRuntime } from '@/modules/shell/app';
import { SetupStoreId } from '@/enum';
import { $t } from '@/locales';
import { useRouteStore } from '../route';
import { useTabStore } from '../tab';

export const useAuthStore = defineStore(SetupStoreId.Auth, () => {
  const routeStore = useRouteStore();
  const tabStore = useTabStore();
  const { redirectFromLogin } = useRouterPush(false);
  const { loading: loginLoading, startLoading, endLoading } = useLoading();
  const { session, dirtyTabs } = shellRuntime();

  /** 顶栏显示的用户信息 */
  const userInfo = computed(() => ({
    userId: session.user.value?.userId ?? '',
    userName: session.user.value?.username ?? '',
    realName: session.user.value?.displayName ?? ''
  }));
  const status = computed(() => session.status.value);
  const isLogin = computed(() => session.status.value === 'ready');
  const roles = computed(() => session.roles.value);

  function showError(error: unknown) {
    window.$message?.error(error instanceof Error ? error.message : String(error));
  }

  async function login(userName: string, password: string) {
    startLoading();
    try {
      await session.login(userName, password);
    } catch (error) {
      showError(error);
    } finally {
      endLoading();
    }
  }

  async function selectRole(roleCode: string) {
    startLoading();
    try {
      await session.selectRole(roleCode);
    } catch (error) {
      showError(error);
    } finally {
      endLoading();
    }
  }

  async function logout() {
    try {
      await session.logout();
    } catch (error) {
      showError(error);
    }
  }

  function changePassword(password: string) {
    return session.changePassword(password);
  }

  /** 去登录页之前清掉路由和页签（页签按旧系统缓存到本地，同一账号再登录时恢复） */
  async function resetToLogin(keepRedirect: boolean) {
    const current = router.currentRoute.value;
    tabStore.cacheTabs();
    tabStore.$reset();
    dirtyTabs.clear();
    await routeStore.resetStore();
    if (current.name !== 'login') {
      const query = keepRedirect && !current.meta.constant ? { redirect: current.fullPath } : {};
      await router.push({ name: 'login', query });
    }
  }

  /** 去选角色之前清掉上一个角色的路由和页签 */
  async function resetToRoleSelect() {
    const current = router.currentRoute.value;
    tabStore.$reset();
    dirtyTabs.clear();
    await routeStore.resetStore();
    if (current.name !== 'login') {
      await router.push({ name: 'login', query: current.meta.constant ? {} : { redirect: current.fullPath } });
    }
  }

  /**
   * 登录、选角色完成：换了账号时清掉缓存的页签、回首页（旧系统 `checkTabClear`），否则回到登录前要去的页面。
   */
  async function afterEnter() {
    const userId = userInfo.value.userId;
    const lastLoginUserId = localStg.get('lastLoginUserId');
    const changedUser = lastLoginUserId !== userId;
    if (changedUser) {
      localStg.remove('globalTabs');
      await tabStore.clearTabs();
    }
    localStg.set('lastLoginUserId', userId);
    await redirectFromLogin(!changedUser);
    window.$notification?.success({
      title: $t('page.login.common.loginSuccess'),
      content: $t('page.login.common.welcomeBack', { userName: userInfo.value.realName || userInfo.value.userName }),
      duration: 4500
    });
  }

  return {
    userInfo,
    status,
    isLogin,
    roles,
    loginLoading,
    login,
    selectRole,
    logout,
    changePassword,
    resetToLogin,
    resetToRoleSelect,
    afterEnter
  };
});
