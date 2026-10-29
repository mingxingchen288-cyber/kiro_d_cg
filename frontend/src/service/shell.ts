/**
 * 过渡的 ShellApi（C11）：外壳的 ShellApi（T-FS-2）和 assembly 的模块注册（T-AS-3）完成前，供通用页面使用。
 * assembly 接入后由 main.ts 创建正式的 ShellApi 并注册各模块，本文件随之删除。
 *
 * - http：platform.ts（C09、C03）。
 * - realtime：realtime.ts，连接 `${服务地址}/ws`。开发代理还没转发 WebSocket，连不上时后台重试（见 realtime.ts）。
 * - calc：rules-core 交付的 `createCalcWorkerClient`（rules-core/dist/web/，C07 第 5 节），第一次预览时才创建 Worker。
 *   rules-core 说明页面要带 COOP、COEP 响应头，由 assembly 配置开发服务器和生产环境（AS-06）；
 *   dist/web 是构建产物、不入库，由 assembly 按 rules-core 模块说明第 6 节放进前端工程后改这里的路径。
 * - session：当前用户取自外壳的登录状态，角色和配置版本取自 GET /api/me。
 * - tabs：用外壳的页签 store 设置标题、关闭页签；setDirty 只记录，关闭前确认属于外壳的 FS-03（T-FS-2）。
 */
import { ref } from 'vue';
import { router } from '@/router';
import { useAuthStore } from '@/store/modules/auth';
import { useTabStore } from '@/store/modules/tab';
import type { CurrentUser, RoleRef } from '@/contracts/http';
import type { CalcWorkerClient } from '@/contracts/rules';
import type { ShellApi } from '@/contracts/shell';
import { createCalcWorkerClient } from '../../../rules-core/dist/web/client.js';
import { me, platformHttp, serviceBaseURL } from './platform';
import { createRealtimeClient } from './realtime';

const WASM_URL = new URL('../../../rules-core/dist/web/rules_core.wasm', import.meta.url).href;

function lazyCalc(): CalcWorkerClient {
  let client: CalcWorkerClient | null = null;
  const get = () => {
    client ??= createCalcWorkerClient(WASM_URL);
    return client;
  };
  return {
    load: pack => get().load(pack),
    evaluate: (handle, request) => get().evaluate(handle, request),
    dispose: handle => client?.dispose(handle),
    terminate: () => client?.terminate()
  };
}

function wsUrl() {
  const base = new URL(serviceBaseURL, window.location.href);
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  base.pathname = `${base.pathname.replace(/\/$/, '')}/ws`;
  return base.href;
}

let shell: ShellApi | null = null;

export function interimShell(): ShellApi {
  if (shell) return shell;
  const authStore = useAuthStore();
  const tabStore = useTabStore();
  const info = authStore.userInfo;
  const user = ref<CurrentUser | null>(
    info.userId
      ? {
          userId: info.userId,
          username: info.userName,
          displayName: info.realName || info.userName,
          departmentId: info.departmentId || null
        }
      : null
  );
  const role = ref<RoleRef | null>(info.roles[0] ? { code: info.roles[0], name: info.roles[0], admin: false } : null);
  const configVersion = ref(0);
  me()
    .then(current => {
      user.value = current.user;
      role.value = current.role;
      configVersion.value = current.configVersion;
    })
    .catch(() => {
      // 会话失效由外壳的请求处理（FS-02）
    });
  const dirty = new Map<string, boolean>();
  shell = {
    http: platformHttp,
    realtime: createRealtimeClient(wsUrl()),
    calc: lazyCalc(),
    session: { user, role, configVersion },
    tabs: {
      open(path, title) {
        const exists = tabStore.tabs.some(tab => tab.id === path);
        if (exists) tabStore.setTabLabel(title, path);
        else void router.push(path).then(() => tabStore.setTabLabel(title, path));
      },
      close(path) {
        void tabStore.removeTab(path);
      },
      setDirty(path, value) {
        dirty.set(path, value);
      }
    },
    message: {
      success: text => window.$message?.success(text),
      warning: text => window.$message?.warning(text),
      error: text => window.$message?.error(text)
    }
  };
  return shell;
}
