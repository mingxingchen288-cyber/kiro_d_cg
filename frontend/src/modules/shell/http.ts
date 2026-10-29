/**
 * 外壳交给各模块的 HTTP 客户端（C11 `ShellApi.http`）：在 C09 的客户端外面加一层会话处理（FS-02）。
 * 请求返回会话问题时先通知外壳（回登录页或选角色），再照常把错误抛给调用方。
 */
import { PlatformError } from '../../contracts/errors';
import type { HttpClient } from '../../contracts/shell';

/**
 * 会话问题（C03 第 2 节）：
 * - `login`：401 SESSION_REQUIRED，或其他 401（登录失败 LOGIN_FAILED 除外），回登录页；
 * - `roleRevoked`：401 SESSION_ROLE_REVOKED，会话选定的角色被撤销，还有别的角色时去选角色；
 * - `roleRequired`：403 ROLE_SELECTION_REQUIRED，还没有选定角色。
 */
export type SessionProblem = 'login' | 'roleRevoked' | 'roleRequired';

export function sessionProblemOf(error: unknown): SessionProblem | null {
  if (!(error instanceof PlatformError)) return null;
  if (error.code === 'LOGIN_FAILED') return null;
  if (error.code === 'SESSION_ROLE_REVOKED') return 'roleRevoked';
  if (error.code === 'ROLE_SELECTION_REQUIRED') return 'roleRequired';
  return error.status === 401 ? 'login' : null;
}

export function withSessionHandling(http: HttpClient, onProblem: (problem: SessionProblem) => void): HttpClient {
  async function guard<T>(request: () => Promise<T>): Promise<T> {
    try {
      return await request();
    } catch (error) {
      const problem = sessionProblemOf(error);
      if (problem) onProblem(problem);
      throw error;
    }
  }
  return {
    get: (path, options) => guard(() => http.get(path, options)),
    post: (path, body, options) => guard(() => http.post(path, body, options)),
    put: (path, body, options) => guard(() => http.put(path, body, options)),
    delete: (path, options) => guard(() => http.delete(path, options)),
    download: (path, body, options) => guard(() => http.download(path, body, options))
  };
}
