/** 部门管理的正向流程（旧系统 dept-manage）：列出部门、表格里新建和修改，点"保存"提交 */
import { describe, expect, it } from 'vitest';
import { DepartmentsModel } from '../../src/modules/admin/departments';
import { openAdmin } from './support';

async function openDepartments() {
  const ctx = openAdmin();
  const model = new DepartmentsModel(ctx.deps);
  await model.load();
  return { ...ctx, model };
}

describe('部门管理', () => {
  it('列出部门', async () => {
    const { model } = await openDepartments();
    expect(model.state.rows.map(r => [r.departmentId, r.name])).toEqual([
      ['175', '采购部'],
      ['581', '市场部'],
      ['1069', '技术中心']
    ]);
  });

  it('新建和修改一起保存：新建调 POST，修改调 PUT，上级部门原样提交，保存后重新读取', async () => {
    const { model, http, messages } = await openDepartments();
    const id = model.addRow();
    model.edit(id, '质量部');
    model.edit('175', '采购中心');
    expect(model.dirtyCount).toBe(2);

    expect(await model.save()).toBe(true);
    expect(http.callsTo('POST', '/api/admin/departments').map(c => c.body)).toEqual([
      { name: '质量部', parentId: null }
    ]);
    expect(http.callsTo('PUT', '/api/admin/departments/:departmentId').map(c => [c.params.departmentId, c.body])).toEqual([
      ['175', { name: '采购中心', parentId: null }]
    ]);
    expect(messages).toContainEqual({ kind: 'success', text: '保存成功' });
    expect(model.dirtyCount).toBe(0);
    expect(model.state.rows.map(r => [r.departmentId, r.name])).toEqual([
      ['175', '采购中心'],
      ['581', '市场部'],
      ['1069', '技术中心'],
      ['1101', '质量部']
    ]);
  });
});
