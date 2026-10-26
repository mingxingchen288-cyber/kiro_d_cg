declare namespace Api {
  namespace Metadata {
    /** 表元数据 */
    interface TableMetadata {
      id: number;
      tableCode: string;
      tableName: string;
      queryView: string;
      targetTable: string;
      pkColumn: string;
      sequenceName: string;
      parentTableCode?: string;
      parentFkColumn?: string;
      columns: ColumnMetadata[];
    }

    /** 列元数据 */
    interface ColumnMetadata {
      id: number;
      columnName: string;
      queryColumn?: string;
      targetColumn?: string;
      headerText: string;
      dataType: 'text' | 'number' | 'date' | 'datetime' | 'select' | 'lookup' | 'checkbox';
      displayOrder: number;
      editable: boolean;
      required: boolean;
      searchable: boolean;
      sortable?: boolean;
      filterable?: boolean;
      visible?: boolean;
      pinned?: 'left' | 'right' | null;
      width?: number;
      dictType?: string;
      lookupCode?: string;
      defaultValue?: any;
      rulesConfig?: string;
      /** 是否虚拟列：不存不取，只有公式计算 */
      isVirtual?: boolean;
    }

    /** 页面组件 */
    interface PageComponent {
      id: number;
      pageCode: string;
      componentKey: string;
      componentType:
        | 'LAYOUT'
        | 'GRID'
        | 'FORM'
        | 'BUTTON'
        | 'TABS'
        | 'DETAIL_GRID'
        | 'MASTER_DETAIL'
        | 'LOGIC_AGG'
        | 'LOGIC_BROADCAST'
        | 'LOGIC_FIELD'
        | 'LOGIC_MAPPING';
      parentKey?: string;
      refTableCode?: string;
      componentConfig?: string;
      sortOrder: number;
      rules?: PageRule[];
      children?: PageComponent[];
    }

    /** 页面规则 */
    interface PageRule {
      id: number;
      pageCode: string;
      componentKey: string;
      ruleType: string;
      rules: string;
      sortOrder: number;
      description?: string;
    }

    /** 字典项 */
    interface DictItem {
      value: string;
      label: string;
      sortOrder: number;
    }

    /** 弹窗选择器配置 */
    interface LookupConfig {
      lookupCode: string;
      lookupName: string;
      dataSource: string;
      displayColumns: LookupDisplayColumn[];
      searchColumns: string[];
    }

    /** 弹窗选择器显示列 */
    interface LookupDisplayColumn {
      field: string;
      header: string;
      width?: number;
    }
  }
}
