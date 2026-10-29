/** 模块内的事件：审批详情中通过、驳回、撤回成功后通知待办列表刷新（FA 第 5 节"按结果刷新列表"）。 */

type Listener = (approvalId: string) => void;

const listeners = new Set<Listener>();

export function onApprovalProcessed(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function notifyApprovalProcessed(approvalId: string) {
  for (const listener of [...listeners]) listener(approvalId);
}
