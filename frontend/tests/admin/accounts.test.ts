/**
 * 人员管理的正向流程：列出账号、查询、新建账号、修改、停用（FM-02 先确认）、启用、改密码。
 * 每一步检查发给后端的请求就是用户在表格里填的内容，以及重新读取后的列表。
 */
import { describe, expect, it } from 'vitest';
import { AccountsModel, INITIAL_PASSWORD } from '../../src/modules/admin/accounts';
import { openAdmin } from './support';

async function openAccounts() {
  const ctx = openAdmin();
  const model = new AccountsModel(ctx.deps);
  await model.load();
  return { ...ctx, model };
}

describe('人员管理', () => {
  it('列出账号：显示部门名称和角色名称', async () => {
    const { model, http } = await openAccounts();
    expect(model.state.error).toBeNull();
    expect(model.state.rows.map(r => [r.userId, r.username, r.displayName])).toEqual([
      ['241', 'HY260404', '程苏慧'],
      ['343', 'HY090702', '汪春龙'],
      ['381', 'HY190510', '朱文俊'],
      ['383', 'HY221020', '韩群']
    ]);
    const wang = model.row('343')!;
    expect(model.departmentName(wang.departmentId)).toBe('采购部');
    expect(model.roleNames(wang.roleCodes)).toBe('采购');
    expect(wang.enabled).toBe(true);
    expect(http.callsTo('GET', '/api/admin/accounts')[0].options?.query).toEqual({
      keyword: undefined,
      startRow: 0,
      endRow: 500
    });
    expect(http.callsTo('GET', '/api/config/items')[0].options?.query).toEqual({ type: 'role' });
  });

  it('按账号名或姓名查询', async () => {
    const { model, http } = await openAccounts();
    await model.search(' 汪春龙 ');
    expect(http.callsTo('GET', '/api/admin/accounts').at(-1)?.options?.query?.keyword).toBe('汪春龙');
    expect(model.state.rows.map(r => r.displayName)).toEqual(['汪春龙']);
  });

  it('新建账号：表格里填用户名、姓名、部门，初始密码为旧系统的 Abc123..，保存后列表里出现', async () => {
    const { model, http, backend, messages } = await openAccounts();
    const id = model.addRow();
    expect(model.state.rows[0]).toMatchObject({ id, isNew: true, password: INITIAL_PASSWORD });
    model.edit(id, 'username', 'HY230101');
    model.edit(id, 'displayName', '张三');
    model.edit(id, 'departmentId', '1069');
    expect(model.dirtyCount).toBe(1);

    expect(await model.save()).toBe(true);
    expect(http.callsTo('POST', '/api/admin/accounts').map(c => c.body)).toEqual([
      { username: 'HY230101', displayName: '张三', departmentId: '1069', password: 'Abc123..', roleCodes: [] }
    ]);
    expect(backend.passwords.get('401')).toBe('Abc123..');
    expect(messages).toContainEqual({ kind: 'success', text: '保存成功' });
    expect(model.dirtyCount).toBe(0);
    const created = model.state.rows.find(r => r.username === 'HY230101')!;
    expect(created).toMatchObject({ userId: '401', displayName: '张三', departmentId: '1069', enabled: true, isNew: false });
    expect(model.departmentName(created.departmentId)).toBe('技术中心');
  });

  it('切回人员管理：部门管理刚新建的"成本部"能选，正在新增的行不丢', async () => {
    const { model, backend } = await openAccounts();
    const id = model.addRow();
    model.edit(id, 'username', 'chengben01');
    backend.departments.push({ departmentId: '14', name: '成本部', parentId: null });
    backend.roles.push({ code: 'COST_ACCOUNTANT', name: '成本会计' });
    expect(model.state.departments.map(d => d.name)).not.toContain('成本部');

    await model.refreshChoices();
    expect(model.state.departments.map(d => d.name)).toEqual(['采购部', '市场部', '技术中心', '成本部']);
    expect(model.roleNames(['COST_ACCOUNTANT'])).toBe('成本会计');
    model.edit(id, 'departmentId', '14');
    expect(model.row(id)).toMatchObject({ username: 'chengben01', departmentId: '14', isNew: true });
    expect(model.departmentName('14')).toBe('成本部');
  });

  it('修改姓名和部门：保存时角色、状态原样提交', async () => {
    const { model, http } = await openAccounts();
    model.edit('383', 'displayName', '韩群（技术）');
    model.edit('383', 'departmentId', '581');
    expect(await model.save()).toBe(true);
    expect(http.callsTo('PUT', '/api/admin/accounts/:userId').map(c => [c.params.userId, c.body])).toEqual([
      ['383', { displayName: '韩群（技术）', departmentId: '581', roleCodes: ['技术中心'], enabled: true }]
    ]);
    expect(model.row('383')).toMatchObject({ displayName: '韩群（技术）', departmentId: '581', changed: false });
  });

  it('停用（FM-02）：先确认并提示立即下线，确认后提交 enabled=false；取消时不提交', async () => {
    const { model, http, confirms, answers } = await openAccounts();

    answers.next = false;
    expect(await model.setEnabled('343', false)).toBe(false);
    expect(confirms).toHaveLength(1);
    expect(http.callsTo('PUT', '/api/admin/accounts/:userId')).toHaveLength(0);
    expect(model.row('343')!.enabled).toBe(true);

    answers.next = true;
    expect(await model.setEnabled('343', false)).toBe(true);
    expect(confirms[1].title).toBe('停用账号');
    expect(confirms[1].content).toContain('汪春龙（HY090702）会被立即下线');
    expect(http.callsTo('PUT', '/api/admin/accounts/:userId').map(c => [c.params.userId, c.body])).toEqual([
      ['343', { displayName: '汪春龙', departmentId: '175', roleCodes: ['008'], enabled: false }]
    ]);
    expect(model.row('343')!.enabled).toBe(false);
  });

  it('启用停用的账号：不需要确认', async () => {
    const { model, http, confirms, backend } = await openAccounts();
    backend.accounts.find(a => a.userId === '381')!.enabled = false;
    await model.reload();
    expect(await model.setEnabled('381', true)).toBe(true);
    expect(confirms).toHaveLength(0);
    expect(http.callsTo('PUT', '/api/admin/accounts/:userId').at(-1)?.body).toMatchObject({ enabled: true });
    expect(model.row('381')!.enabled).toBe(true);
  });

  it('改密码（旧系统"初始化密码"）：把输入的密码提交给这个账号', async () => {
    const { model, http, backend, messages } = await openAccounts();
    expect(await model.changePassword('343', INITIAL_PASSWORD)).toBe(true);
    expect(http.callsTo('POST', '/api/admin/accounts/:userId/password').map(c => [c.params.userId, c.body])).toEqual([
      ['343', { password: 'Abc123..' }]
    ]);
    expect(backend.passwords.get('343')).toBe('Abc123..');
    expect(messages).toContainEqual({ kind: 'success', text: '已修改 HY090702 的密码' });
  });
});
