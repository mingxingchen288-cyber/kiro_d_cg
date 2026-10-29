/**
 * 部门管理（旧系统元数据页 `dept-manage`，表 CostDepartment）：部门列表、表格内新增和修改、删除、保存。
 *
 * - 旧页面的列：ID、部门编码、部门名称，上级部门ID、排序两列隐藏。新系统没有部门编码和排序（identity contract-gaps
 *   第 3 条：cmx 中编码就是 `DEPT_<ID>`，排序全为 0），上级部门与旧页面一样不显示，修改时原样提交。
 * - 与旧页面相同：新增、删除先记在表格里，点"保存"时一起提交（新建、修改、删除各调一次接口）。
 * - 新建、修改、删除是 C09 之外的接口（contract-gaps 第 1 条）；部门列表是 C09 的 `GET /api/admin/departments`，
 *   没有查询条件，旧页面的"高级查询"没有做。
 */
import { reactive } from 'vue';
import type { AdminDeps, Department } from './shared';
import { messageOf } from './shared';

export interface DepartmentRow {
  /** 表格行标识：已保存的为部门编号，新增的为 `new-<序号>` */
  id: string;
  departmentId: string | null;
  name: string;
  parentId: string | null;
  isNew: boolean;
  changed: boolean;
}

function rowOf(department: Department): DepartmentRow {
  return {
    id: department.departmentId,
    departmentId: department.departmentId,
    name: department.name,
    parentId: department.parentId,
    isNew: false,
    changed: false
  };
}

export class DepartmentsModel {
  readonly state = reactive({
    rows: [] as DepartmentRow[],
    /** 已从表格删除、等保存时提交的部门 */
    deleted: [] as DepartmentRow[],
    loading: false,
    saving: false,
    error: null as string | null
  });

  private seq = 0;

  constructor(private readonly deps: AdminDeps) {}

  get dirtyCount() {
    return this.state.rows.filter(r => r.isNew || r.changed).length + this.state.deleted.length;
  }

  row(id: string) {
    return this.state.rows.find(r => r.id === id);
  }

  async load() {
    this.state.loading = true;
    this.state.error = null;
    try {
      const list = await this.deps.api.departments();
      this.state.rows = list.items.map(rowOf);
      this.state.deleted = [];
    } catch (error) {
      this.state.error = messageOf(error);
    } finally {
      this.state.loading = false;
    }
  }

  addRow() {
    this.seq += 1;
    const row: DepartmentRow = {
      id: `new-${this.seq}`,
      departmentId: null,
      name: '',
      parentId: null,
      isNew: true,
      changed: false
    };
    this.state.rows = [row, ...this.state.rows];
    return row.id;
  }

  edit(id: string, name: string) {
    this.state.rows = this.state.rows.map(r => (r.id === id ? { ...r, name, changed: !r.isNew } : r));
  }

  /** 删除选中的行：新增还没保存的直接去掉，已保存的等保存时删除 */
  remove(ids: string[]) {
    const removed = this.state.rows.filter(r => ids.includes(r.id));
    this.state.rows = this.state.rows.filter(r => !ids.includes(r.id));
    this.state.deleted = [...this.state.deleted, ...removed.filter(r => !r.isNew)];
  }

  /** 保存：先删除，再新建、修改；全部成功后重新读取列表 */
  async save() {
    if (this.dirtyCount === 0) return true;
    this.state.saving = true;
    try {
      for (const row of [...this.state.deleted]) {
        await this.deps.extra.deleteDepartment(row.departmentId!);
        this.state.deleted = this.state.deleted.filter(r => r.id !== row.id);
      }
      for (const row of this.state.rows.filter(r => r.isNew || r.changed)) {
        const body = { name: row.name.trim(), parentId: row.parentId };
        const result = row.isNew
          ? await this.deps.extra.createDepartment(body)
          : await this.deps.extra.updateDepartment(row.departmentId!, body);
        // 已成功的行先换成后端的值，后面的行失败时不会重复提交
        this.state.rows = this.state.rows.map(r => (r.id === row.id ? rowOf(result) : r));
      }
    } catch (error) {
      this.deps.message.error(`保存失败：${messageOf(error)}`);
      return false;
    } finally {
      this.state.saving = false;
    }
    this.deps.message.success('保存成功');
    await this.load();
    return true;
  }
}
