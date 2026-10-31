/**
 * 默认值"当前部门名称"（`currentDeptName`，盘点 B10）：新增行时取当前用户的部门名称（C09 v15 `CurrentUser.departmentName`），
 * 同旧系统 useWorkingSetStore.ts 第 552–553 行 `userInfo.departmentName`。例：成本部的张三新增一行成本单，
 * 配了"当前部门名称"的"部门"列填好"成本部"；没有部门的人为空。
 */
import { describe, expect, it } from 'vitest';
import { newRowValues } from '../../src/modules/page/fields';
import { costView } from './support';

const NOW = new Date(2026, 9, 31, 10, 0, 0);

function master() {
  const region = costView().master;
  const like = region.fields.find(f => f.name === 'MEMO')!;
  return {
    ...region,
    fields: [
      ...region.fields,
      { ...like, name: 'DEPT_NAME', label: '部门', default: { type: 'builtin', value: 'currentDeptName' } }
    ]
  } as typeof region;
}

const user = { userId: '1', username: 'zhangsan', displayName: '张三', departmentId: '10', departmentName: '成本部' };

describe('默认值"当前部门名称"', () => {
  it('新增行填当前用户的部门名称', () => {
    const values = newRowValues(master(), { user, role: null, now: NOW });
    expect(values).toMatchObject({ DEPT_NAME: '成本部', CREATE_BY: '张三' });
  });

  it('没有部门时为空', () => {
    const values = newRowValues(master(), {
      user: { ...user, departmentId: null, departmentName: null },
      role: null,
      now: NOW
    });
    expect(values.DEPT_NAME).toBeNull();
  });
});
