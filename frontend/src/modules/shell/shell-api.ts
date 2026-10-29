/**
 * 正式的 ShellApi（C11）：把外壳的 HTTP 客户端、实时连接、计算客户端、会话、页签和提示交给各模块。
 * 模块只经它调用外壳，不直接修改外壳的状态；会话的三个值对模块只读。
 */
import { computed } from 'vue';
import type { RealtimeClient } from '../../contracts/realtime';
import type { CalcWorkerClient } from '../../contracts/rules';
import type { HttpClient, ShellApi } from '../../contracts/shell';
import type { ShellSession } from './session';

export interface ShellApiParts {
  http: HttpClient;
  realtime: RealtimeClient;
  calc: CalcWorkerClient;
  session: Pick<ShellSession, 'user' | 'role' | 'configVersion'>;
  tabs: ShellApi['tabs'];
  message: ShellApi['message'];
}

export function createShellApi(parts: ShellApiParts): ShellApi {
  const { session } = parts;
  return {
    http: parts.http,
    realtime: parts.realtime,
    calc: parts.calc,
    session: {
      user: computed(() => session.user.value),
      role: computed(() => session.role.value),
      configVersion: computed(() => session.configVersion.value)
    },
    tabs: parts.tabs,
    message: parts.message
  };
}
