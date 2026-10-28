/**
 * 编辑缓冲（FP-04 的最小部分）：按（实体、行主键）记录未保存的修改，并记下行所属的单据（主单主键）。
 * 保存时按单据生成命令的 documents（C02 第 1 节）：主表有修改为 modify，否则为 none；明细为 modify。
 * 新增、删除、撤销重做还没有开放。
 */
import type { DocumentPatch, FieldValue } from '@/service/platform';

export interface RowRef {
  entity: string;
  rowKey: string;
  /** 行所属单据的主单主键；主表行就是它自己的主键 */
  recordKey: string;
}

interface PendingRow {
  ref: RowRef;
  changes: Record<string, FieldValue>;
}

function keyOf(entity: string, rowKey: string) {
  return `${entity}\u0000${rowKey}`;
}

export class EditBuffer {
  private readonly rows = new Map<string, PendingRow>();

  constructor(private readonly masterEntity: string) {}

  /** 有未保存修改的行数 */
  get size() {
    return this.rows.size;
  }

  set(ref: RowRef, field: string, value: FieldValue) {
    const key = keyOf(ref.entity, ref.rowKey);
    const row = this.rows.get(key) ?? { ref, changes: {} };
    row.changes[field] = value;
    this.rows.set(key, row);
  }

  isChanged(entity: string, rowKey: string, field: string) {
    const row = this.rows.get(keyOf(entity, rowKey));
    return Boolean(row && field in row.changes);
  }

  /** 从后端重新读到的行叠加上未保存的修改 */
  overlay(entity: string, rowKey: string, values: Record<string, FieldValue>) {
    const row = this.rows.get(keyOf(entity, rowKey));
    return row ? { ...values, ...row.changes } : values;
  }

  documents(): DocumentPatch[] {
    const byRecord = new Map<string, DocumentPatch>();
    for (const { ref, changes } of this.rows.values()) {
      const document = byRecord.get(ref.recordKey) ?? {
        entity: this.masterEntity,
        master: { op: 'none', rowKey: ref.recordKey },
        details: []
      };
      if (ref.entity === this.masterEntity) {
        document.master = { op: 'modify', rowKey: ref.rowKey, changes: { ...changes } };
      } else {
        document.details.push({ entity: ref.entity, op: 'modify', rowKey: ref.rowKey, changes: { ...changes } });
      }
      byRecord.set(ref.recordKey, document);
    }
    return [...byRecord.values()];
  }

  clear() {
    this.rows.clear();
  }
}
