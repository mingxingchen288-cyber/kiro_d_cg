/**
 * 配置界面共用的上下文：外壳（C11 ShellApi）、按 C09 调用后端的 api、配置项存储，以及提示。
 * 只依赖 ShellApi（install 时注册的那一个），不导入其他模块。
 */
import { createPlatformApi } from '../../../contracts/api';
import type { PlatformApi } from '../../../contracts/api';
import type { ShellApi } from '../../../contracts/shell';
import { useConfigShell } from '../index';
import { ConfigStore } from './store';

export interface ConfigContext {
  shell: ShellApi;
  api: PlatformApi;
  store: ConfigStore;
  notify: { success(text: string): void; error(text: string): void; warning(text: string): void };
}

const contexts = new WeakMap<ShellApi, ConfigContext>();

export function useConfigContext(): ConfigContext {
  const shell = useConfigShell();
  let context = contexts.get(shell);
  if (!context) {
    const api = createPlatformApi(shell.http);
    context = {
      shell,
      api,
      store: new ConfigStore(api),
      notify: {
        success: text => shell.message.success(text),
        error: text => shell.message.error(text),
        warning: text => shell.message.warning(text)
      }
    };
    contexts.set(shell, context);
  }
  return context;
}
