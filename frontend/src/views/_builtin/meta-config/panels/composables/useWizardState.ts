import { reactive, computed } from 'vue';
import type { WizardColumn, WizardPayload, WizardTable } from '@/service/api/wizard';

// ==================== State Interfaces ====================

export interface WizardColumnState {
  columnName: string;
  targetColumn: string;
  headerText: string;
  dataType: string;
  displayOrder: number;
  isVirtual: number;
  visible: boolean;
  editable: boolean;
  filterable: boolean;
  widgetType: string;
}

export interface WizardTableState {
  queryView: string;
  targetTable: string;
  tableCode: string;
  tableName: string;
  pkColumn: string;
  sequenceName: string;
  parentFkColumn: string;
  columns: WizardColumnState[];
  columnsLoaded: boolean;
}

export interface WizardStep1State {
  parentId: number | null;
  parentName: string;
  resourceName: string;
  resourceCode: string;
  icon: string;
}

export interface WizardStep2State {
  mode: 'single' | 'master-detail';
  pageCode: string;
  masterTable: WizardTableState;
  detailTables: WizardTableState[];
}

export interface WizardState {
  currentStep: number;
  step1: WizardStep1State;
  step2: WizardStep2State;
}

// ==================== Helper Functions ====================

/** 生成目录编码：中文/英文名 → UPPER_SNAKE_CASE */
export function generateResourceCode(name: string): string {
  if (!name) return '';
  // Remove non-alphanumeric/non-Chinese characters, convert to underscore-separated
  const cleaned = name
    .replace(/[^\w\u4e00-\u9fff]/g, '_')
    .replace(/([a-z])([A-Z])/g, '$1_$2')
    .toUpperCase()
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '');
  // Truncate to 64 characters
  return cleaned.slice(0, 64);
}

/** 从视图名推导 pageCode (kebab-case) */
export function derivePageCode(viewName: string, resourceCode: string): string {
  let base = viewName || resourceCode;
  if (!base) return '';
  // Strip V_ prefix
  base = base.replace(/^V_/i, '');
  // Convert UPPER_SNAKE_CASE to kebab-case
  return base.toLowerCase().replace(/_/g, '-');
}

/** 从目标表名推导 tableCode (PascalCase) */
export function deriveTableCode(targetTable: string): string {
  if (!targetTable) return '';
  // T_COST_PINGGU → CostPinggu
  const stripped = targetTable.replace(/^T_/i, '');
  return stripped
    .split('_')
    .map(part => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join('');
}

/** 列分类：视图列名 vs 目标表列名直接匹配 */
export function classifyColumns(
  viewColumns: Array<{ columnName: string; dataType?: string; comment?: string }>,
  targetColumns: string[]
): WizardColumnState[] {
  const targetSet = new Set(targetColumns.map(c => c.toUpperCase()));

  return viewColumns.map((vc, idx) => {
    const colUpper = vc.columnName.toUpperCase();
    const isReal = targetSet.has(colUpper);

    return {
      columnName: vc.columnName,
      targetColumn: isReal ? colUpper : '',
      headerText: vc.comment || vc.columnName,
      dataType: mapOracleDataType(vc.dataType || 'VARCHAR2'),
      displayOrder: idx + 1,
      isVirtual: isReal ? 0 : 1,
      visible: true,
      editable: isReal,
      filterable: false,
      widgetType: mapOracleDataType(vc.dataType || 'VARCHAR2')
    };
  });
}

/** Oracle DATA_TYPE → 前端数据类型 */
export function mapOracleDataType(oracleType: string): string {
  const upper = (oracleType || '').toUpperCase();
  if (upper.includes('NUMBER') || upper.includes('FLOAT') || upper.includes('DECIMAL') || upper.includes('INTEGER')) {
    return 'number';
  }
  if (upper.includes('DATE') || upper.includes('TIMESTAMP')) {
    return 'date';
  }
  return 'text';
}

/** 校验表/视图名格式 */
export function isValidTableName(name: string): boolean {
  if (!name) return false;
  return /^[A-Za-z0-9_]+$/.test(name) && name.length <= 64;
}

/** 校验目录编码格式 */
export function isValidResourceCode(code: string): boolean {
  if (!code) return false;
  return /^[A-Z0-9_]+$/.test(code) && code.length <= 64;
}

// ==================== Validation ====================

export interface ValidationError {
  field: string;
  message: string;
}

export function validateStep1(step1: WizardStep1State): ValidationError[] {
  const errors: ValidationError[] = [];
  if (!step1.parentId) {
    errors.push({ field: 'parentId', message: '请选择父级菜单' });
  }
  if (!step1.resourceName || !step1.resourceName.trim()) {
    errors.push({ field: 'resourceName', message: '页面名称必填' });
  }
  if (step1.resourceName && step1.resourceName.length > 128) {
    errors.push({ field: 'resourceName', message: '页面名称不能超过128个字符' });
  }
  if (!step1.resourceCode || !step1.resourceCode.trim()) {
    errors.push({ field: 'resourceCode', message: '页面编码必填' });
  }
  if (step1.resourceCode && !isValidResourceCode(step1.resourceCode)) {
    errors.push({ field: 'resourceCode', message: '编码只允许大写字母、数字、下划线，最长64字符' });
  }
  return errors;
}

export function validateStep2(step2: WizardStep2State): ValidationError[] {
  const errors: ValidationError[] = [];
  const master = step2.masterTable;

  if (!master.queryView) {
    errors.push({ field: 'masterTable.queryView', message: '主表视图名必填' });
  } else if (!isValidTableName(master.queryView)) {
    errors.push({ field: 'masterTable.queryView', message: '视图名只允许字母、数字、下划线' });
  }
  if (!master.targetTable) {
    errors.push({ field: 'masterTable.targetTable', message: '主表目标表名必填' });
  } else if (!isValidTableName(master.targetTable)) {
    errors.push({ field: 'masterTable.targetTable', message: '目标表名只允许字母、数字、下划线' });
  }
  if (!master.pkColumn) {
    errors.push({ field: 'masterTable.pkColumn', message: '主表主键列未获取，请检查目标表是否有主键约束' });
  }
  if (!master.columns || master.columns.length === 0) {
    errors.push({ field: 'masterTable.columns', message: '主表列配置不能为空' });
  }

  // Check duplicate displayOrder in master columns
  if (master.columns && master.columns.length > 0) {
    const orderSet = new Set<number>();
    for (const col of master.columns) {
      if (orderSet.has(col.displayOrder)) {
        errors.push({ field: 'masterTable.columns', message: `主表排序号 ${col.displayOrder} 重复` });
        break;
      }
      orderSet.add(col.displayOrder);
    }
  }

  if (step2.mode === 'master-detail') {
    for (let i = 0; i < step2.detailTables.length; i++) {
      const detail = step2.detailTables[i];
      const prefix = `detailTables[${i}]`;
      if (!detail.queryView) {
        errors.push({ field: `${prefix}.queryView`, message: `从表${i + 1}视图名必填` });
      } else if (!isValidTableName(detail.queryView)) {
        errors.push({ field: `${prefix}.queryView`, message: `从表${i + 1}视图名格式错误` });
      }
      if (!detail.targetTable) {
        errors.push({ field: `${prefix}.targetTable`, message: `从表${i + 1}目标表名必填` });
      } else if (!isValidTableName(detail.targetTable)) {
        errors.push({ field: `${prefix}.targetTable`, message: `从表${i + 1}目标表名格式错误` });
      }
      if (!detail.pkColumn) {
        errors.push({ field: `${prefix}.pkColumn`, message: `从表${i + 1}主键列未获取` });
      }
      if (!detail.parentFkColumn) {
        errors.push({ field: `${prefix}.parentFkColumn`, message: `从表${i + 1}关联字段必须选择` });
      }
      if (!detail.columns || detail.columns.length === 0) {
        errors.push({ field: `${prefix}.columns`, message: `从表${i + 1}列配置不能为空` });
      }
    }
  }

  return errors;
}

// ==================== Composable ====================

function createEmptyTableState(): WizardTableState {
  return {
    queryView: '',
    targetTable: '',
    tableCode: '',
    tableName: '',
    pkColumn: '',
    sequenceName: '',
    parentFkColumn: '',
    columns: [],
    columnsLoaded: false
  };
}

export function useWizardState() {
  const state = reactive<WizardState>({
    currentStep: 1,
    step1: {
      parentId: null,
      parentName: '',
      resourceName: '',
      resourceCode: '',
      icon: 'folder'
    },
    step2: {
      mode: 'single',
      pageCode: '',
      masterTable: createEmptyTableState(),
      detailTables: [createEmptyTableState()]
    }
  });

  const canGoNext = computed(() => {
    if (state.currentStep === 1) {
      return validateStep1(state.step1).length === 0;
    }
    if (state.currentStep === 2) {
      return validateStep2(state.step2).length === 0;
    }
    return true;
  });

  function goNext() {
    if (state.currentStep < 3 && canGoNext.value) {
      state.currentStep++;
    }
  }

  function goPrev() {
    if (state.currentStep > 1) {
      state.currentStep--;
    }
  }

  function addDetailTable() {
    if (state.step2.detailTables.length < 5) {
      state.step2.detailTables.push(createEmptyTableState());
    }
  }

  function removeDetailTable(index: number) {
    if (state.step2.detailTables.length > 1) {
      state.step2.detailTables.splice(index, 1);
    }
  }

  function resetStep2OnModeChange() {
    state.step2.masterTable = createEmptyTableState();
    state.step2.detailTables = [createEmptyTableState()];
    state.step2.pageCode = '';
  }

  /** 组装提交载荷 */
  function buildPayload(): WizardPayload {
    const master = state.step2.masterTable;
    const masterTable: WizardTable = {
      queryView: master.queryView,
      targetTable: master.targetTable,
      tableCode: master.tableCode || deriveTableCode(master.targetTable),
      tableName: master.tableName || state.step1.resourceName,
      pkColumn: master.pkColumn,
      sequenceName: master.sequenceName || `SEQ_${master.targetTable}`,
      parentFkColumn: '',
      columns: master.columns.map(toWizardColumn)
    };

    const detailTables: WizardTable[] =
      state.step2.mode === 'master-detail'
        ? state.step2.detailTables.map(dt => ({
            queryView: dt.queryView,
            targetTable: dt.targetTable,
            tableCode: dt.tableCode || deriveTableCode(dt.targetTable),
            tableName: dt.tableName || dt.queryView,
            pkColumn: dt.pkColumn,
            sequenceName: dt.sequenceName || `SEQ_${dt.targetTable}`,
            parentFkColumn: dt.parentFkColumn,
            columns: dt.columns.map(toWizardColumn)
          }))
        : [];

    return {
      parentId: state.step1.parentId === -1 ? null as any : state.step1.parentId!,
      resourceName: state.step1.resourceName,
      resourceCode: state.step1.resourceCode,
      icon: state.step1.icon || 'folder',
      mode: state.step2.mode,
      pageCode: state.step2.pageCode || derivePageCode(master.queryView, state.step1.resourceCode),
      masterTable,
      detailTables
    };
  }

  return {
    state,
    canGoNext,
    goNext,
    goPrev,
    addDetailTable,
    removeDetailTable,
    resetStep2OnModeChange,
    buildPayload
  };
}

function toWizardColumn(col: WizardColumnState): WizardColumn {
  const trimmedTarget = (col.targetColumn || '').trim();
  // 如果虚拟列已指定了 TARGET_COLUMN（非空），视为已转成真实列
  const effectiveIsVirtual = col.isVirtual === 1 && !trimmedTarget ? 1 : 0;

  return {
    columnName: col.columnName,
    targetColumn: trimmedTarget,
    headerText: col.headerText,
    dataType: col.dataType,
    displayOrder: col.displayOrder,
    isVirtual: effectiveIsVirtual,
    visible: col.visible,
    editable: effectiveIsVirtual === 1 ? false : col.editable,
    filterable: col.filterable,
    widgetType: col.widgetType
  };
}
