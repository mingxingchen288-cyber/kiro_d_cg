/**
 * 配置项的读取、校验、保存、删除（FC-02、C09 第 3 节）。每个配置项只有当前版本，保存即生效；
 * 保存前先调用 `POST /api/config/validate`，有错误时不保存，把错误交给界面定位；保存时后端仍会校验，
 * 422 的明细同样定位。保存成功后返回新的版本号，界面显示"已保存，版本 N"。
 */
import type { PlatformApi } from '../../../contracts/api';
import type { ConfigItem } from '../../../contracts/http';
import type { JsonValue } from '../../../contracts/schema';
import { type ConfigProblem, problemsOf, toProblem } from './errors';
import type { ConfigType, ContentByType } from './types';

export interface ConfigSummary {
  type: ConfigType;
  key: string;
  name: string;
  version: number;
  updatedBy: string;
  updatedAt: string;
}

export interface TypedItem<T extends ConfigType> {
  type: T;
  key: string;
  name: string;
  version: number | null;
  content: ContentByType[T];
}

export type SaveResult = { ok: true; version: number } | { ok: false; problems: ConfigProblem[] };

/** 深拷贝成纯 JSON（去掉 Vue 代理和 undefined），保存和比较都用它 */
export function plain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export class ConfigStore {
  constructor(private readonly api: PlatformApi) {}

  async list(type?: ConfigType): Promise<ConfigSummary[]> {
    const { items } = await this.api.configItems(type);
    return items as ConfigSummary[];
  }

  async load<T extends ConfigType>(type: T, key: string): Promise<TypedItem<T>> {
    const item: ConfigItem = await this.api.configItem(type, key);
    return { type, key: item.key, name: item.name, version: item.version, content: item.content as unknown as ContentByType[T] };
  }

  /** 读取，不存在（404）时返回 null */
  async tryLoad<T extends ConfigType>(type: T, key: string): Promise<TypedItem<T> | null> {
    try {
      return await this.load(type, key);
    } catch (error) {
      if ((error as { status?: number }).status === 404) return null;
      throw error;
    }
  }

  /** 读取某一类的全部配置项（列表 + 逐项读取） */
  async loadAll<T extends ConfigType>(type: T): Promise<Array<TypedItem<T>>> {
    const summaries = await this.list(type);
    return Promise.all(summaries.map(s => this.load(type, s.key)));
  }

  /** 只校验，不保存 */
  async validate(items: Array<{ type: ConfigType; key: string; name: string; content: unknown }>): Promise<ConfigProblem[]> {
    const response = await this.api.validateConfig({
      items: items.map(item => ({ type: item.type, key: item.key, name: item.name, content: plain(item.content) as Record<string, JsonValue> }))
    });
    return response.ok ? [] : response.errors.map(toProblem);
  }

  /** 先校验，再保存；校验不通过时不发保存请求 */
  async save(type: ConfigType, key: string, name: string, content: unknown): Promise<SaveResult> {
    const body = plain(content) as Record<string, JsonValue>;
    const problems = await this.validate([{ type, key, name, content: body }]);
    if (problems.length) return { ok: false, problems };
    try {
      const saved = await this.api.saveConfigItem(type, key, { name, content: body });
      return { ok: true, version: saved.version };
    } catch (error) {
      const found = problemsOf(error);
      if (found) return { ok: false, problems: found };
      throw error;
    }
  }

  /** 删除；仍被引用时后端返回 422，明细同样定位 */
  async remove(type: ConfigType, key: string): Promise<SaveResult> {
    try {
      await this.api.deleteConfigItem(type, key);
      return { ok: true, version: 0 };
    } catch (error) {
      const found = problemsOf(error);
      if (found) return { ok: false, problems: found };
      throw error;
    }
  }
}
