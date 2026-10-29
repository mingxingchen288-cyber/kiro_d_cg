/**
 * 页签的未保存标记（C11 `ShellApi.tabs.setDirty`，FS-03）：标记了未保存修改的页签，关闭前先确认。
 * 页签按路径区分（与页签 store 的页签 id 相同，例如 `/page/COST_PINGGU`）。
 */
export interface ClosingTab {
  id: string;
  label: string;
}

/** 弹出确认框；用户确认关闭时返回 true */
export type ConfirmClose = (labels: string[]) => Promise<boolean>;

export class DirtyTabs {
  private readonly dirty = new Set<string>();

  set(path: string, dirty: boolean) {
    if (dirty) this.dirty.add(path);
    else this.dirty.delete(path);
  }

  isDirty(path: string) {
    return this.dirty.has(path);
  }

  /**
   * 要关闭的页签中有未保存修改的，先确认；没有时直接返回 true。确认后清掉这些页签的标记。
   * 一次关闭多个页签（关闭其他、关闭全部等）时只确认一次，列出有修改的页签。
   */
  async confirmClose(tabs: ClosingTab[], confirm: ConfirmClose): Promise<boolean> {
    const dirty = tabs.filter(tab => this.dirty.has(tab.id));
    if (!dirty.length) return true;
    const ok = await confirm(dirty.map(tab => tab.label));
    if (ok) for (const tab of dirty) this.dirty.delete(tab.id);
    return ok;
  }

  clear() {
    this.dirty.clear();
  }
}

/** 确认框的文字 */
export function closeConfirmText(labels: string[]) {
  const names = labels.map(label => `"${label}"`).join('、');
  return `页签${names}有未保存的修改，关闭后这些修改会丢失。确定关闭吗？`;
}
