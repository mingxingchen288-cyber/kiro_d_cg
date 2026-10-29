/**
 * 投递记录（C09 第 7 节，delivery 的 DL-04）：按状态筛选、分页查看，已放弃的记录可以重新排队（FM-03）。
 * 旧系统没有这个功能，按 C09 做最简单的列表。
 */
import { reactive } from 'vue';
import type { DeliveryList } from '../../contracts/http';
import type { AdminDeps } from './shared';
import { messageOf } from './shared';

export type DeliveryRow = DeliveryList['rows'][number];
export type DeliveryStatus = DeliveryRow['status'];

/** 状态的中文名（delivery DL-01～DL-03） */
export const DELIVERY_STATUS: Record<DeliveryStatus, string> = {
  pending: '待发送',
  sent: '已发送',
  failed: '发送失败，等待重试',
  abandoned: '已放弃'
};

export const DELIVERY_PAGE_SIZE = 50;

/** FM-03：只有已放弃的记录可以重新排队 */
export function canRequeue(row: DeliveryRow) {
  return row.status === 'abandoned';
}

export class DeliveriesModel {
  readonly state = reactive({
    /** 为 null 时列出全部状态 */
    status: null as DeliveryStatus | null,
    /** 第几页，从 1 开始 */
    page: 1,
    rows: [] as DeliveryRow[],
    total: 0,
    loading: false,
    requeuing: null as string | null,
    error: null as string | null
  });

  constructor(private readonly deps: AdminDeps) {}

  async load() {
    this.state.loading = true;
    this.state.error = null;
    const startRow = (this.state.page - 1) * DELIVERY_PAGE_SIZE;
    try {
      const list = await this.deps.api.deliveries({
        status: this.state.status ?? undefined,
        startRow,
        endRow: startRow + DELIVERY_PAGE_SIZE
      });
      this.state.rows = list.rows;
      this.state.total = list.total;
    } catch (error) {
      this.state.error = messageOf(error);
    } finally {
      this.state.loading = false;
    }
  }

  async setStatus(status: DeliveryStatus | null) {
    this.state.status = status;
    this.state.page = 1;
    await this.load();
  }

  async setPage(page: number) {
    this.state.page = page;
    await this.load();
  }

  /** 重新排队后重新读取当前页 */
  async requeue(row: DeliveryRow) {
    if (!canRequeue(row)) return false;
    this.state.requeuing = row.deliveryId;
    try {
      await this.deps.api.requeueDelivery(row.deliveryId);
    } catch (error) {
      this.deps.message.error(`重新排队失败：${messageOf(error)}`);
      return false;
    } finally {
      this.state.requeuing = null;
    }
    this.deps.message.success('已重新排队');
    await this.load();
    return true;
  }
}
