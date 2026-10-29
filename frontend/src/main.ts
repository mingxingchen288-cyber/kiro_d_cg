import { createApp } from 'vue';
import './plugins/assets';
import { setupAppVersionNotification, setupDayjs, setupIconifyOffline, setupLoading, setupNProgress } from './plugins';
import { setupAgGrid } from './plugins/ag-grid';
import { setupStore } from './store';
import { setupRouter } from './router';
import { setupI18n } from './locales';
import { installModules } from './modules/shell/app';
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

  // 外壳创建 ShellApi，把 src/modules/ 下的前端模块注册进来（C11），路由在登录后挂到主布局下
  installModules();

  await setupRouter(app);

  setupI18n(app);

  setupAppVersionNotification();

  app.mount('#app');
}

setupApp();
