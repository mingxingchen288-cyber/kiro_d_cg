/**
 * 角色人员的正向流程（旧系统角色管理页的"人员列表"）：选角色看人员、分配人员（分配角色）、解除（撤销角色，FM-02 先确认）。
 */
import { describe, expect, it } from 'vitest';
import { RoleMembersModel } from '../../src/modules/admin/role-members';
import { openAdmin } from './support';

async function openRoleMembers() {
  const ctx = openAdmin();
  const model = new RoleMembersModel(ctx.deps);
  await model.load();
  return { ...ctx, model };
}

describe('角色人员', () => {
  it('角色来自 role 配置项，默认选中第一个并列出它的人员', async () => {
    const { model, http } = await openRoleMembers();
    expect(model.state.roles.map(r => r.name)).toEqual(['系统管理员', '技术中心', '采购']);
    expect(model.state.selected).toBe('ADMIN');
    expect(model.state.members.map(m => m.displayName)).toEqual(['程苏慧']);
    expect(http.callsTo('GET', '/api/admin/accounts')[0].options?.query).toEqual({
      roleCode: 'ADMIN',
      startRow: 0,
      endRow: 500
    });
  });

  it('分配角色：从不在该角色的账号中选一个，在原有角色上加上这个角色', async () => {
    const { model, http, backend, messages } = await openRoleMembers();
    await model.select('008');
    expect(model.state.members.map(m => m.displayName)).toEqual(['汪春龙']);
    await model.loadAccounts();
    expect(model.candidates.map(c => c.label)).toEqual([
      '程苏慧 (HY260404)',
      '朱文俊 (HY190510)',
      '韩群 (HY221020)'
    ]);

    expect(await model.assign('381')).toBe(true);
    expect(http.callsTo('PUT', '/api/admin/accounts/:userId').map(c => [c.params.userId, c.body])).toEqual([
      ['381', { displayName: '朱文俊', departmentId: '1069', roleCodes: ['技术中心', '008'], enabled: true }]
    ]);
    expect(backend.accounts.find(a => a.userId === '381')!.roleCodes).toEqual(['技术中心', '008']);
    expect(model.state.members.map(m => m.displayName)).toEqual(['汪春龙', '朱文俊']);
    expect(messages).toContainEqual({ kind: 'success', text: '添加成功' });
  });

  it('撤销角色（FM-02）：先确认并提示立即下线，确认后去掉这个角色', async () => {
    const { model, http, confirms } = await openRoleMembers();
    await model.select('008');

    expect(await model.revoke('343')).toBe(true);
    expect(confirms).toHaveLength(1);
    expect(confirms[0].title).toBe('解除角色');
    expect(confirms[0].content).toContain('解除"采购"后，汪春龙（HY090702）会被立即下线');
    expect(http.callsTo('PUT', '/api/admin/accounts/:userId').map(c => [c.params.userId, c.body])).toEqual([
      ['343', { displayName: '汪春龙', departmentId: '175', roleCodes: [], enabled: true }]
    ]);
    expect(model.state.members).toEqual([]);
  });

  it('切回角色人员：配置里刚新建的"成本会计"出现在左边，原来选中的角色不变，再给它分配人员', async () => {
    const { model, backend } = await openRoleMembers();
    await model.select('008');
    backend.roles.push({ code: 'COST_ACCOUNTANT', name: '成本会计' });

    await model.refreshRoles();
    expect(model.state.roles.map(r => r.name)).toEqual(['系统管理员', '技术中心', '采购', '成本会计']);
    expect(model.state.selected).toBe('008');

    await model.select('COST_ACCOUNTANT');
    expect(model.state.members).toEqual([]);
    await model.loadAccounts();
    expect(await model.assign('383')).toBe(true);
    expect(model.state.members.map(m => m.displayName)).toEqual(['韩群']);
    expect(backend.accounts.find(a => a.userId === '383')!.roleCodes).toEqual(['技术中心', 'COST_ACCOUNTANT']);
  });
});
