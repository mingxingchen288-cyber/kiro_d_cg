/**
 * 命令审查（C09 第 7a 节，write-pipeline 的 WP-17）：开关、记录列表、按用户和结果筛选、展开查看每条 SQL（FM-04）。
 * 关闭前确认，提示会清除全部记录。旧系统没有这个页面，按 C09 做最简单的列表。
 */
import { reactive } from 'vue';
import type { CommandReviewList } from '../../contracts/http';
import type { AdminDeps } from './shared';
import { messageOf } from './shared';

export type CommandLog = CommandReviewList['rows'][number];
export type CommandOutcome = CommandLog['result'];

/** 结果的中文名（write-pipeline `review.py` 的 `_outcome`） */
export const COMMAND_RESULT: Record<CommandOutcome, string> = {
  saved: '成功',
  rejected: '被拒绝',
  failed: '出错'
};

export const REVIEW_PAGE_SIZE = 50;

export class CommandReviewModel {
  readonly state = reactive({
    enabled: false,
    rows: [] as CommandLog[],
    total: 0,
    /** 筛选：账号名，为空时不筛选 */
    user: '',
    result: null as CommandOutcome | null,
    page: 1,
    loading: false,
    toggling: false,
    error: null as string | null
  });

  constructor(private readonly deps: AdminDeps) {}

  async load() {
    this.state.loading = true;
    this.state.error = null;
    const startRow = (this.state.page - 1) * REVIEW_PAGE_SIZE;
    try {
      const list = await this.deps.api.commandReview({
        startRow,
        endRow: startRow + REVIEW_PAGE_SIZE,
        user: this.state.user.trim() || undefined,
        result: this.state.result ?? undefined
      });
      this.state.enabled = list.enabled;
      this.state.rows = list.rows;
      this.state.total = list.total;
    } catch (error) {
      this.state.error = messageOf(error);
    } finally {
      this.state.loading = false;
    }
  }

  /** 按用户和结果筛选，回到第 1 页 */
  async filter(user: string, result: CommandOutcome | null) {
    this.state.user = user;
    this.state.result = result;
    this.state.page = 1;
    await this.load();
  }

  async setPage(page: number) {
    this.state.page = page;
    await this.load();
  }

  /** 开关：关闭前确认，关闭会清除全部已记录的内容（C09 第 7a 节）。返回是否已提交 */
  async setEnabled(enabled: boolean) {
    if (enabled === this.state.enabled) return false;
    if (!enabled) {
      const ok = await this.deps.confirm({
        title: '关闭命令审查',
        content: '关闭后会清除全部已记录的命令和 SQL，不能恢复。确定关闭吗？',
        positiveText: '关闭'
      });
      if (!ok) return false;
    }
    this.state.toggling = true;
    try {
      await this.deps.api.setCommandReview(enabled);
    } catch (error) {
      this.deps.message.error(`${enabled ? '开启' : '关闭'}命令审查失败：${messageOf(error)}`);
      return false;
    } finally {
      this.state.toggling = false;
    }
    this.deps.message.success(enabled ? '已开启命令审查' : '已关闭命令审查，记录已清除');
    this.state.page = 1;
    await this.load();
    return true;
  }
}
