import type { useDialog } from 'naive-ui';

export type ToolbarItem = {
  action?: string;
  label?: string;
  type?: string;
  disabled?: boolean;
  confirm?: string;
  requiresRow?: boolean;
  refreshMode?: 'all' | 'row' | 'detail' | 'none';
};

export type ExecuteActionFn = (
  actionCode: string,
  options?: {
    data?: Record<string, any>;
    selectedRow?: Record<string, any> | null;
    refreshMode?: 'all' | 'row' | 'detail' | 'none';
  }
) => Promise<void>;

export type ToolbarActionContext = {
  getSelectedRow: () => Record<string, any> | null;
  executeAction: ExecuteActionFn;
  dialog: ReturnType<typeof useDialog>;
};

export async function handleToolbarAction(item: ToolbarItem, ctx: ToolbarActionContext): Promise<void> {
  if (!item.action) return;

  const { getSelectedRow, executeAction, dialog } = ctx;
  const row = getSelectedRow();
  const defaultRefreshMode = item.requiresRow ? 'row' : 'all';
  const refreshMode = item.refreshMode ?? defaultRefreshMode;

  const doExecute = async () => {
    await executeAction(item.action!, {
      data: row || {},
      selectedRow: row,
      refreshMode
    });
  };

  if (item.confirm) {
    dialog.warning({
      title: '确认',
      content: item.confirm,
      positiveText: '确定',
      negativeText: '取消',
      onPositiveClick: doExecute
    });
    return;
  }

  await doExecute();
}

export function resolveRefreshMode(item: {
  requiresRow?: boolean;
  refreshMode?: 'all' | 'row' | 'detail' | 'none';
}): 'all' | 'row' | 'detail' | 'none' {
  const defaultRefreshMode = item.requiresRow ? 'row' : 'all';
  return item.refreshMode ?? defaultRefreshMode;
}
