/** 确认框（FM-02、FM-04）：naive-ui 的警告对话框，点"确定"为 true，取消、关闭或点遮罩为 false */
import { useDialog } from 'naive-ui';
import type { Confirm } from '../shared';

export function useConfirm(): Confirm {
  const dialog = useDialog();
  return ({ title, content, positiveText = '确定' }) =>
    new Promise<boolean>(resolve => {
      let answered = false;
      const answer = (value: boolean) => {
        if (answered) return;
        answered = true;
        resolve(value);
      };
      dialog.warning({
        title,
        content,
        positiveText,
        negativeText: '取消',
        onPositiveClick: () => answer(true),
        onNegativeClick: () => answer(false),
        onAfterLeave: () => answer(false)
      });
    });
}
