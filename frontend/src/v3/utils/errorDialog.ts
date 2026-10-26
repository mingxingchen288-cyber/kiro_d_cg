import { h } from 'vue';

/**
 * 统一错误弹窗：以 Dialog 形式展示错误信息
 * 短消息直接展示；长消息或数据库错误提供"查看详情"展开
 * 内置去重：同一消息 3 秒内不重复弹出
 */

const recentMessages = new Set<string>();

function isDuplicate(msg: string): boolean {
  if (recentMessages.has(msg)) return true;
  recentMessages.add(msg);
  setTimeout(() => recentMessages.delete(msg), 3000);
  return false;
}

export function showErrorDialog(msg: string) {
  if (!msg || isDuplicate(msg)) return;

  const dialog = window.$dialog;
  if (!dialog) {
    window.$message?.error(msg);
    return;
  }

  // 判断是否包含数据库错误特征
  const hasOra = /ORA-\d+/.test(msg);
  const isLong = msg.length > 100 || msg.includes('\n');

  if (!hasOra && !isLong) {
    // 短错误消息，普通弹窗
    dialog.error({
      title: '操作失败',
      content: msg,
      positiveText: '确定'
    });
    return;
  }

  // 提取摘要和 ORA 码
  const lines = msg.split('\n');
  const summary = lines[0].length > 100 ? lines[0].substring(0, 100) + '...' : lines[0];
  const oraMatch = msg.match(/ORA-\d+/);
  const oraCode = oraMatch ? oraMatch[0] : '';

  dialog.error({
    title: '操作失败' + (oraCode ? ` (${oraCode})` : ''),
    content: () =>
      h('div', {}, [
        h('p', { style: 'margin: 0 0 8px; font-size: 14px;' }, summary),
        h('details', { style: 'margin-top: 8px;' }, [
          h('summary', { style: 'cursor: pointer; color: #2080f0; font-size: 13px;' }, '查看详情'),
          h('pre', {
            style:
              'margin-top: 8px; padding: 8px; background: #f5f5f5; border-radius: 4px; font-size: 12px; white-space: pre-wrap; word-break: break-all; max-height: 300px; overflow-y: auto;'
          }, msg)
        ])
      ]),
    positiveText: '确定',
    style: { width: '560px' }
  });
}
