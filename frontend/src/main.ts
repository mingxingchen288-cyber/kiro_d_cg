import { createApp } from 'vue';
import './plugins/assets';
import { setupAppVersionNotification, setupDayjs, setupIconifyOffline, setupLoading, setupNProgress } from './plugins';
import { setupAgGrid } from './plugins/ag-grid';
import { setupStore } from './store';
import { setupRouter } from './router';
import { setupI18n } from './locales';
import { useAuthStore } from './store/modules/auth';
import { AUTH_IDLE_TIMEOUT_EVENT, setupAuthActivityTracking } from './store/modules/auth/shared';
import App from './App.vue';

async function setupApp() {
  setupLoading();

  setupNProgress();

  setupIconifyOffline();

  setupDayjs();

  // AG Grid 模块注册（企业版检测）
  await setupAgGrid();

  const app = createApp(App);

  setupStore(app);
  setupAuthActivityTracking();
  window.addEventListener(AUTH_IDLE_TIMEOUT_EVENT, () => {
    const authStore = useAuthStore();
    authStore.resetStore();
  });

  await setupRouter(app);

  setupI18n(app);

  setupAppVersionNotification();

  app.mount('#app');
}

setupApp();
