/**
 * 外壳的运行时（单例）：创建 ShellApi 依赖的 HTTP 客户端、实时连接、计算客户端，以及会话、通知、页签标记和模块注册。
 * main.ts 在创建 Pinia 之后、加载路由之前调用 `installModules`，把 `src/modules/` 下的模块注册到外壳（C11）。
 */
import { router } from '@/router';
import { createPlatformHttp, serviceBaseURL } from '@/service/platform';
import { type ShellRealtimeClient, createRealtimeClient } from '@/service/realtime';
import { createLazyCalc } from '@/service/calc';
import { useAuthStore } from '@/store/modules/auth';
import { useTabStore } from '@/store/modules/tab';
import type { FrontendModule, ShellApi } from '@/contracts/shell';
import { createPlatformApi } from '@/contracts/api';
import { discoverModules } from './discover';
import { sessionProblemOf, withSessionHandling } from './http';
import { Inbox } from './inbox';
import { ModuleRegistry } from './registry';
import { type SessionStore, ShellSession, type StoredSession } from './session';
import { createShellApi } from './shell-api';
import { DirtyTabs } from './tabs';

const STORAGE_KEY = `${import.meta.env.VITE_STORAGE_PREFIX ?? ''}shell-session`;

/** 浏览器会话存储：CSRF 令牌和登录时返回的角色列表，关闭浏览器标签页后清除 */
const browserStore: SessionStore = {
  read() {
    const text = window.sessionStorage.getItem(STORAGE_KEY);
    return text ? (JSON.parse(text) as StoredSession) : null;
  },
  write(value) {
    if (value) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else window.sessionStorage.removeItem(STORAGE_KEY);
  }
};

function wsUrl() {
  const base = new URL(serviceBaseURL, window.location.href);
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  base.pathname = `${base.pathname.replace(/\/$/, '')}/ws`;
  return base.href;
}

export interface ShellRuntime {
  session: ShellSession;
  inbox: Inbox;
  realtime: ShellRealtimeClient;
  dirtyTabs: DirtyTabs;
  registry: ModuleRegistry;
  /** 交给各模块的 ShellApi */
  api: ShellApi;
}

let runtime: ShellRuntime | null = null;

export function shellRuntime(): ShellRuntime {
  if (runtime) return runtime;
  // 会话在下面创建；HTTP 客户端和实时连接只在请求、断开时才用到它
  // eslint-disable-next-line prefer-const
  let session: ShellSession;
  const baseHttp = createPlatformHttp(() => session.csrfToken);
  const http = withSessionHandling(baseHttp, problem => session.onProblem(problem));
  const realtime = createRealtimeClient(wsUrl(), {
    onSessionEnded: () => {
      session.verify();
    }
  });
  const inbox = new Inbox({ api: createPlatformApi(http), realtime, navigate: link => router.push(link) });
  const dirtyTabs = new DirtyTabs();
  session = new ShellSession({
    http: baseHttp,
    store: browserStore,
    nav: {
      toLogin: keepRedirect => useAuthStore().resetToLogin(keepRedirect),
      toRoleSelect: () => useAuthStore().resetToRoleSelect(),
      entered: () => useAuthStore().afterEnter()
    },
    hooks: {
      onReady() {
        realtime.start();
        inbox.start().catch((error: unknown) => {
          if (!sessionProblemOf(error)) window.$message?.error(error instanceof Error ? error.message : String(error));
        });
      },
      onEnded() {
        realtime.stop();
        inbox.stop();
      }
    }
  });
  realtime.onEvent('session.revoked', () => {
    session.verify();
  });
  realtime.onEvent('config.changed', payload => session.noteConfigVersion(payload.version));

  const api = createShellApi({
    http,
    realtime,
    calc: createLazyCalc(),
    session,
    tabs: {
      open(path, title) {
        useTabStore().setTabTitle(path, title);
        router.push(path);
      },
      close(path) {
        useTabStore().removeTab(path);
      },
      setDirty(path, dirty) {
        dirtyTabs.set(path, dirty);
      }
    },
    message: {
      success: text => window.$message?.success(text),
      warning: text => window.$message?.warning(text),
      error: text => window.$message?.error(text)
    }
  });
  runtime = { session, inbox, realtime, dirtyTabs, registry: new ModuleRegistry(), api };
  return runtime;
}

/** 注册前端模块（C11）：默认注册 `src/modules/` 下找到的全部模块 */
export function installModules(modules: FrontendModule[] = discoverModules()) {
  const shell = shellRuntime();
  shell.registry.register(modules, shell.api);
}
