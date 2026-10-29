/**
 * 人员管理（旧系统元数据页 `user-manage`，表 CostUser）：账号列表、表格内新增和修改、保存、停用和启用、改密码。
 *
 * - 旧页面的列：ID、用户名、姓名、部门、状态；邮箱、电话在新系统没有（identity 没有这两列，cmx 中在用账号全为空）。
 *   新增"角色"列只显示，分配和解除在"角色人员"里做（与旧系统角色管理页的"人员列表"相同）。
 * - 旧页面的"删除"在新系统用"停用"代替（identity contract-gaps 第 5 条）；停用前确认并提示立即下线（FM-02）。
 * - 旧页面的"初始化密码"把密码重置为固定的 `Abc123..`（旧后端 `UserService.DEFAULT_PASSWORD`）；
 *   新系统改密码接口要求给出密码，界面预填这个值，管理员可以改。新增账号的初始密码同样预填它。
 * - 账号名建好后不能改：C09 的 `AccountUpdate` 没有 `username`（contract-gaps 第 3 条）。
 */
import { reactive } from 'vue';
import type { AdminDeps, Department, RoleItem } from './shared';
import { type Account, loadAll, loadRoles, messageOf } from './shared';

/** 旧系统"初始化密码"的固定密码（旧后端 `auth/service/UserService.java` 的 `DEFAULT_PASSWORD`） */
export const INITIAL_PASSWORD = 'Abc123..';

export type AccountField = 'username' | 'displayName' | 'departmentId' | 'password';

export interface AccountRow {
  /** 表格行标识：已保存的为账号编号，新增的为 `new-<序号>` */
  id: string;
  userId: string | null;
  username: string;
  displayName: string;
  departmentId: string | null;
  enabled: boolean;
  roleCodes: string[];
  /** 新增行的初始密码；已保存的行为 null */
  password: string | null;
  /** 后端的当前值；新增的行为 null */
  saved: Account | null;
  isNew: boolean;
  changed: boolean;
}

function rowOf(account: Account): AccountRow {
  return {
    id: account.userId,
    userId: account.userId,
    username: account.username,
    displayName: account.displayName,
    departmentId: account.departmentId,
    enabled: account.enabled,
    roleCodes: [...account.roleCodes],
    password: null,
    saved: account,
    isNew: false,
    changed: false
  };
}

export class AccountsModel {
  readonly state = reactive({
    rows: [] as AccountRow[],
    departments: [] as Department[],
    roles: [] as RoleItem[],
    keyword: '',
    loading: false,
    saving: false,
    error: null as string | null
  });

  private seq = 0;

  constructor(private readonly deps: AdminDeps) {}

  get dirtyCount() {
    return this.state.rows.filter(r => r.isNew || r.changed).length;
  }

  row(id: string) {
    return this.state.rows.find(r => r.id === id);
  }

  departmentName(departmentId: string | null) {
    if (departmentId === null) return '';
    return this.state.departments.find(d => d.departmentId === departmentId)?.name ?? departmentId;
  }

  roleNames(codes: string[]) {
    return codes.map(code => this.state.roles.find(r => r.code === code)?.name ?? code).join('、');
  }

  /** 打开页面：账号、部门、角色一起读取 */
  async load() {
    this.state.loading = true;
    this.state.error = null;
    try {
      const [rows, departments, roles] = await Promise.all([
        this.fetchAccounts(),
        this.deps.api.departments(),
        loadRoles(this.deps.api)
      ]);
      this.state.rows = rows;
      this.state.departments = departments.items;
      this.state.roles = roles;
    } catch (error) {
      this.state.error = messageOf(error);
    } finally {
      this.state.loading = false;
    }
  }

  /**
   * 重新读取部门和角色，表格中的行和未保存的修改不变。切回人员管理时调用：刚在部门管理新建的部门、
   * 在配置的角色权限里新建的角色，不刷新页面就能选到、显示出名称。
   */
  async refreshChoices() {
    try {
      const [departments, roles] = await Promise.all([this.deps.api.departments(), loadRoles(this.deps.api)]);
      this.state.departments = departments.items;
      this.state.roles = roles;
    } catch (error) {
      this.state.error = messageOf(error);
    }
  }

  /** 按账号名或姓名查询（C09 的 `keyword`）；未保存的修改不保留 */
  async search(keyword: string) {
    this.state.keyword = keyword.trim();
    await this.reload();
  }

  async reload() {
    this.state.loading = true;
    this.state.error = null;
    try {
      this.state.rows = await this.fetchAccounts();
    } catch (error) {
      this.state.error = messageOf(error);
    } finally {
      this.state.loading = false;
    }
  }

  /** 新增：在最上面加一行，初始密码预填旧系统的固定密码 */
  addRow() {
    this.seq += 1;
    const row: AccountRow = {
      id: `new-${this.seq}`,
      userId: null,
      username: '',
      displayName: '',
      departmentId: null,
      enabled: true,
      roleCodes: [],
      password: INITIAL_PASSWORD,
      saved: null,
      isNew: true,
      changed: false
    };
    this.state.rows = [row, ...this.state.rows];
    return row.id;
  }

  /** 表格内修改一格；账号名和初始密码只有新增的行能改 */
  edit(id: string, field: AccountField, value: string | null) {
    const row = this.row(id);
    if (!row) return;
    if ((field === 'username' || field === 'password') && !row.isNew) return;
    const next = { ...row, changed: !row.isNew };
    if (field === 'departmentId') next.departmentId = value || null;
    else next[field] = value ?? '';
    this.replace(id, next);
  }

  /** 保存：新增的行逐个新建，修改的行逐个修改；全部成功后重新读取列表 */
  async save() {
    const pending = this.state.rows.filter(r => r.isNew || r.changed);
    if (!pending.length) return true;
    this.state.saving = true;
    try {
      for (const row of pending) {
        const result = row.isNew
          ? await this.deps.api.createAccount({
              username: row.username.trim(),
              displayName: row.displayName.trim(),
              departmentId: row.departmentId,
              password: row.password ?? '',
              roleCodes: [...row.roleCodes]
            })
          : await this.deps.api.updateAccount(row.userId!, {
              displayName: row.displayName.trim(),
              departmentId: row.departmentId,
              roleCodes: [...row.roleCodes],
              enabled: row.enabled
            });
        // 已成功的行先换成后端的值，后面的行失败时不会重复提交
        this.replace(row.id, rowOf(result));
      }
    } catch (error) {
      this.deps.message.error(`保存失败：${messageOf(error)}`);
      return false;
    } finally {
      this.state.saving = false;
    }
    this.deps.message.success('保存成功');
    await this.reload();
    return true;
  }

  /**
   * 停用或启用（FM-02）：停用前确认，提示该账号会被立即下线。只改状态，姓名、部门按后端的当前值提交，
   * 这一行没保存的修改留在表格里。返回是否已提交。
   */
  async setEnabled(id: string, enabled: boolean) {
    const row = this.row(id);
    const saved = row?.saved;
    if (!row || !saved || saved.enabled === enabled) return false;
    if (!enabled) {
      const ok = await this.deps.confirm({
        title: '停用账号',
        content: `停用后，${saved.displayName || saved.username}（${saved.username}）会被立即下线，不能再登录。确定停用吗？`,
        positiveText: '停用'
      });
      if (!ok) return false;
    }
    let updated: Account;
    try {
      updated = await this.deps.api.updateAccount(saved.userId, {
        displayName: saved.displayName,
        departmentId: saved.departmentId,
        roleCodes: [...saved.roleCodes],
        enabled
      });
    } catch (error) {
      this.deps.message.error(`${enabled ? '启用' : '停用'}失败：${messageOf(error)}`);
      return false;
    }
    const current = this.row(id) ?? row;
    this.replace(id, current.changed ? { ...current, enabled: updated.enabled, saved: updated } : rowOf(updated));
    this.deps.message.success(enabled ? '已启用' : '已停用');
    return true;
  }

  /** 改密码（旧系统"初始化密码"） */
  async changePassword(id: string, password: string) {
    const row = this.row(id);
    if (!row?.userId) return false;
    try {
      await this.deps.api.changePassword(row.userId, password);
    } catch (error) {
      this.deps.message.error(`修改密码失败：${messageOf(error)}`);
      return false;
    }
    this.deps.message.success(`已修改 ${row.username} 的密码`);
    return true;
  }

  private async fetchAccounts() {
    const keyword = this.state.keyword || undefined;
    const rows = await loadAll((startRow, endRow) => this.deps.api.listAccounts({ keyword, startRow, endRow }));
    return rows.map(rowOf);
  }

  private replace(id: string, next: AccountRow) {
    this.state.rows = this.state.rows.map(r => (r.id === id ? next : r));
  }
}
