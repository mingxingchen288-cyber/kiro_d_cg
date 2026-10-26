import { request } from '../request';

// ==================== TypeScript 接口 ====================

export interface WizardColumn {
  /** 视图列名 */
  columnName: string;
  /** 写入目标列名 */
  targetColumn: string;
  /** 列标题 */
  headerText: string;
  /** 数据类型: text | number | date */
  dataType: string;
  /** 排序号 */
  displayOrder: number;
  /** 0=真实列, 1=虚拟列 */
  isVirtual: number;
  /** 是否显示 */
  visible: boolean;
  /** 是否可编辑 */
  editable: boolean;
  /** 是否可筛选 */
  filterable: boolean;
  /** 控件类型 */
  widgetType: string;
}

export interface WizardTable {
  /** 查询视图名 */
  queryView: string;
  /** 目标表名 */
  targetTable: string;
  /** 表代码 */
  tableCode: string;
  /** 表中文名 */
  tableName: string;
  /** 主键列名 */
  pkColumn: string;
  /** 序列名 */
  sequenceName: string;
  /** 从表关联字段（仅从表） */
  parentFkColumn: string;
  /** 列配置 */
  columns: WizardColumn[];
}

export interface WizardPayload {
  /** 父级资源 ID */
  parentId: number;
  /** 目录名称 */
  resourceName: string;
  /** 目录编码 */
  resourceCode: string;
  /** 图标 */
  icon: string;
  /** 页面模式 */
  mode: 'single' | 'master-detail';
  /** 页面编码 */
  pageCode: string;
  /** 主表配置 */
  masterTable: WizardTable;
  /** 从表列表 */
  detailTables: WizardTable[];
}

export interface WizardResult {
  /** 生成的页面编码 */
  pageCode: string;
  /** 创建的实体总数 */
  createdCount: number;
}

// ==================== API 函数 ====================

/** 向导：一键生成页面（自行处理错误，不触发全局 toast） */
export async function generateWizard(payload: WizardPayload) {
  const { data, error } = await request<any>({
    url: '/meta-config/wizard/generate',
    method: 'POST',
    data: payload
  });
  // 正常成功
  if (!error && data) {
    return data as WizardResult;
  }
  // 后端返回了错误（业务错误或数据库错误）
  const responseData = (error as any)?.response?.data || (error as any)?.data;
  const msg = responseData?.msg || (error as any)?.message || '生成失败';
  const detail = responseData?.data || null; // { message, oraCode, sql, rootCause }
  const err: any = new Error(msg);
  err.detail = detail;
  err.silent = true; // 标记为静默错误，不弹全局 toast
  throw err;
}

/** 向导：查询表主键列 */
export async function fetchPkColumn(tableName: string, owner = 'CMX') {
  const { data, error } = await request<string>({
    url: '/meta-config/wizard/pk-column',
    params: { tableName, owner }
  });
  if (error) throw error;
  return data || '';
}

/** 向导：级联删除页面及相关元数据 */
export async function cascadeDeletePage(pageCode: string) {
  const { error } = await request<void>({
    url: `/meta-config/wizard/cascade/${encodeURIComponent(pageCode)}`,
    method: 'DELETE'
  });
  if (error) throw error;
}
