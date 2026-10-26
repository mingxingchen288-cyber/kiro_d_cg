/** Preserve the server's business error instead of replacing it with an HTTP client message. */
export function approvalErrorMessage(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const details = error as { response?: { data?: { msg?: unknown } }; message?: unknown };
    if (details.response?.data?.msg) return String(details.response.data.msg);
    if (details.message) return String(details.message);
  }
  return '请求失败，请检查后端返回的错误';
}
