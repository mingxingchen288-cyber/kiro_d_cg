/**
 * 一类配置项的通用编辑状态（T-FC-1）：列表 → 打开 → 编辑 → 校验 → 保存 → 显示新版本号（模块说明第 5 节）。
 * 字典、Lookup、导出、角色、菜单、操作、实体、页面的编辑界面都用它；内容的表单由各界面自己绑定 `state.current.content`。
 */
import { reactive } from 'vue';
import { newContent, withRequired } from './defaults';
import { type ConfigProblem, errorText } from './errors';
import type { ConfigStore, ConfigSummary } from './store';
import type { ConfigType, ContentByType } from './types';

export interface Draft<T extends ConfigType> {
  type: T;
  key: string;
  name: string;
  /** 已保存的版本；新建未保存时为 null */
  version: number | null;
  content: ContentByType[T];
}

export interface ItemNotifier {
  success(text: string): void;
  error(text: string): void;
}

export interface ItemState<T extends ConfigType> {
  loading: boolean;
  busy: boolean;
  items: ConfigSummary[];
  current: Draft<T> | null;
  dirty: boolean;
  problems: ConfigProblem[];
  status: string;
}

export class ItemEditor<T extends ConfigType> {
  readonly state: ItemState<T> = reactive({
    loading: false,
    busy: false,
    items: [],
    current: null,
    dirty: false,
    problems: [],
    status: ''
  }) as unknown as ItemState<T>;

  constructor(
    private readonly store: ConfigStore,
    readonly type: T,
    private readonly notify: ItemNotifier
  ) {}

  /** 打开列表 */
  async loadList() {
    this.state.loading = true;
    try {
      this.state.items = await this.store.list(this.type);
    } catch (error) {
      this.notify.error(errorText(error));
    } finally {
      this.state.loading = false;
    }
  }

  /** 打开一个配置项 */
  async open(key: string) {
    this.state.loading = true;
    try {
      const item = await this.store.load(this.type, key);
      this.state.current = { type: this.type, key: item.key, name: item.name, version: item.version, content: item.content } as Draft<T>;
      this.state.dirty = false;
      this.state.problems = [];
      this.state.status = `版本 ${item.version}`;
    } catch (error) {
      this.notify.error(errorText(error));
    } finally {
      this.state.loading = false;
    }
  }

  /** 新建：必须写的字段由界面预填（FC-02） */
  create(key: string, name: string, content?: ContentByType[T]) {
    this.state.current = {
      type: this.type,
      key,
      name,
      version: null,
      content: content ?? newContent(this.type, key, name)
    } as Draft<T>;
    this.state.dirty = true;
    this.state.problems = [];
    this.state.status = '新建，尚未保存';
  }

  markDirty() {
    this.state.dirty = true;
  }

  /** 只校验，不保存 */
  async validate() {
    const current = this.state.current;
    if (!current) return false;
    this.state.busy = true;
    try {
      this.state.problems = await this.store.validate([
        { type: this.type, key: current.key, name: current.name, content: withRequired(this.type, current.content as ContentByType[T]) }
      ]);
      if (!this.state.problems.length) this.notify.success('配置校验通过；尚未保存');
      return this.state.problems.length === 0;
    } catch (error) {
      this.notify.error(errorText(error));
      return false;
    } finally {
      this.state.busy = false;
    }
  }

  /** 保存即生效：先校验，校验不通过或后端 422 时显示明细，当前版本不变 */
  async save() {
    const current = this.state.current;
    if (!current) return null;
    this.state.busy = true;
    try {
      const content = withRequired(this.type, current.content as ContentByType[T]);
      const result = await this.store.save(this.type, current.key, current.name, content);
      if (!result.ok) {
        this.state.problems = result.problems;
        this.state.status = `保存被拒绝：${result.problems.length} 处配置需要修改`;
        return null;
      }
      current.version = result.version;
      current.content = content as Draft<T>['content'];
      this.state.dirty = false;
      this.state.problems = [];
      this.state.status = `已保存，版本 ${result.version}`;
      this.notify.success(`${current.name} 已保存，版本 ${result.version}`);
      await this.loadList();
      return result.version;
    } catch (error) {
      this.notify.error(errorText(error));
      return null;
    } finally {
      this.state.busy = false;
    }
  }

  async remove() {
    const current = this.state.current;
    if (!current) return false;
    if (current.version === null) {
      this.state.current = null;
      return true;
    }
    this.state.busy = true;
    try {
      const result = await this.store.remove(this.type, current.key);
      if (!result.ok) {
        this.state.problems = result.problems;
        return false;
      }
      this.state.current = null;
      this.notify.success(`${current.name} 已删除`);
      await this.loadList();
      return true;
    } catch (error) {
      this.notify.error(errorText(error));
      return false;
    } finally {
      this.state.busy = false;
    }
  }
}
