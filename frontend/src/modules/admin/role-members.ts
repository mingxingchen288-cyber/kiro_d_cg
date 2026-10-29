/**
 * 角色人员（旧系统角色管理页 `views/_builtin/permission/index.vue` 的"人员列表"）：左边角色列表，右边该角色的人员，
 * "分配人员"从全部账号中选一个加进来，"解除"把账号从角色中去掉。
 *
 * - 角色本身（编码、名称、页面权限）是 config 的 `role` 配置项，在 frontend-config 里编辑；这里只读取列表。
 * - 某个角色的人员用 `GET /api/admin/accounts?roleCode=`（C09 之外，contract-gaps 第 2 条）。
 * - 分配和解除都用 C09 的 `PUT /api/admin/accounts/{userId}`，在账号原有角色上加上或去掉这个角色，其他字段原样提交。
 * - 解除前确认，提示该账号会被立即下线（FM-02）；旧系统的"解除"没有确认。
 */
import { reactive } from 'vue';
import type { Account, AdminDeps, RoleItem } from './shared';
import { loadAll, loadRoles, messageOf } from './shared';

export interface CandidateOption {
  /** 旧系统的写法：`姓名 (用户名)` */
  label: string;
  value: string;
}

export class RoleMembersModel {
  readonly state = reactive({
    roles: [] as RoleItem[],
    selected: null as string | null,
    members: [] as Account[],
    /** 全部账号，打开"分配人员"时读取 */
    accounts: [] as Account[],
    loading: false,
    loadingMembers: false,
    working: false,
    error: null as string | null
  });

  constructor(private readonly deps: AdminDeps) {}

  get selectedRole() {
    return this.state.roles.find(r => r.code === this.state.selected) ?? null;
  }

  /** 可以分配的账号：不在这个角色中的 */
  get candidates(): CandidateOption[] {
    const existing = new Set(this.state.members.map(m => m.userId));
    return this.state.accounts
      .filter(a => !existing.has(a.userId))
      .map(a => ({ label: `${a.displayName || a.username} (${a.username})`, value: a.userId }));
  }

  /** 打开页面：读取角色，默认选中第一个 */
  async load() {
    this.state.loading = true;
    this.state.error = null;
    try {
      this.state.roles = await loadRoles(this.deps.api);
    } catch (error) {
      this.state.error = messageOf(error);
      return;
    } finally {
      this.state.loading = false;
    }
    const keep = this.state.roles.some(r => r.code === this.state.selected);
    const first = keep ? this.state.selected : (this.state.roles[0]?.code ?? null);
    if (first) await this.select(first);
  }

  async select(roleCode: string) {
    this.state.selected = roleCode;
    await this.loadMembers();
  }

  async loadMembers() {
    const roleCode = this.state.selected;
    if (!roleCode) return;
    this.state.loadingMembers = true;
    try {
      const members = await loadAll((start, end) => this.deps.extra.accountsOfRole(roleCode, start, end));
      // 读取期间换了角色时丢弃
      if (this.state.selected === roleCode) this.state.members = members;
    } catch (error) {
      this.state.members = [];
      this.deps.message.error(`读取角色人员失败：${messageOf(error)}`);
    } finally {
      this.state.loadingMembers = false;
    }
  }

  /** 打开"分配人员"：读取全部账号 */
  async loadAccounts() {
    try {
      this.state.accounts = await loadAll((startRow, endRow) => this.deps.api.listAccounts({ startRow, endRow }));
    } catch (error) {
      this.deps.message.error(`读取账号失败：${messageOf(error)}`);
    }
  }

  /** 分配人员：把账号加进当前角色 */
  async assign(userId: string) {
    const role = this.selectedRole;
    const account = this.state.accounts.find(a => a.userId === userId);
    if (!role || !account) return false;
    const ok = await this.update(account, [...account.roleCodes, role.code], '分配人员');
    if (ok) this.deps.message.success('添加成功');
    return ok;
  }

  /** 解除（FM-02）：先确认，提示该账号会被立即下线 */
  async revoke(userId: string) {
    const role = this.selectedRole;
    const account = this.state.members.find(m => m.userId === userId);
    if (!role || !account) return false;
    const confirmed = await this.deps.confirm({
      title: '解除角色',
      content: `解除"${role.name}"后，${account.displayName || account.username}（${account.username}）会被立即下线，需要重新登录。确定解除吗？`,
      positiveText: '解除'
    });
    if (!confirmed) return false;
    const ok = await this.update(
      account,
      account.roleCodes.filter(code => code !== role.code),
      '解除'
    );
    if (ok) this.deps.message.success('解除成功');
    return ok;
  }

  private async update(account: Account, roleCodes: string[], action: string) {
    this.state.working = true;
    try {
      const updated = await this.deps.api.updateAccount(account.userId, {
        displayName: account.displayName,
        departmentId: account.departmentId,
        roleCodes,
        enabled: account.enabled
      });
      this.state.accounts = this.state.accounts.map(a => (a.userId === updated.userId ? updated : a));
    } catch (error) {
      this.deps.message.error(`${action}失败：${messageOf(error)}`);
      return false;
    } finally {
      this.state.working = false;
    }
    await this.loadMembers();
    return true;
  }
}
