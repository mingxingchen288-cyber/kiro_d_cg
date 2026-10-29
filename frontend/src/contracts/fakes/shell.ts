/**
 * ShellApi 的模拟实现（C11）：http、calc、realtime 用本目录的模拟实现，页签和提示记录调用。
 * 当前用户、角色默认取 C09 `/api/me` 的样例（杨娜、成本会计），可以在创建时替换。
 */
import { ref } from 'vue';
import type { CurrentUser, RoleRef } from '../http';
import type { ShellApi } from '../shell';
import { createFakeCalc } from './calc';
import { createFakeHttp } from './http';
import { createFakeRealtime } from './realtime';
import { meResponseSample } from './samples';

export interface FakeShellOptions {
  user?: CurrentUser | null;
  role?: RoleRef | null;
  configVersion?: number;
}

export function createFakeShell(options: FakeShellOptions = {}) {
  const http = createFakeHttp();
  const calc = createFakeCalc();
  const realtime = createFakeRealtime();
  const messages: Array<{ kind: 'success' | 'warning' | 'error'; text: string }> = [];
  const opened: Array<{ path: string; title: string }> = [];
  const closed: string[] = [];
  const dirty = new Map<string, boolean>();
  const shell = {
    http,
    calc,
    realtime,
    session: {
      user: ref(options.user === undefined ? structuredClone(meResponseSample.user) : options.user),
      role: ref(options.role === undefined ? structuredClone(meResponseSample.role) : options.role),
      configVersion: ref(options.configVersion ?? meResponseSample.configVersion)
    },
    tabs: {
      open: (path: string, title: string) => opened.push({ path, title }),
      close: (path: string) => closed.push(path),
      setDirty: (path: string, value: boolean) => dirty.set(path, value)
    },
    message: {
      success: (text: string) => messages.push({ kind: 'success', text }),
      warning: (text: string) => messages.push({ kind: 'warning', text }),
      error: (text: string) => messages.push({ kind: 'error', text })
    }
  } satisfies ShellApi;
  return { shell: shell as ShellApi, http, calc, realtime, messages, opened, closed, dirty };
}
