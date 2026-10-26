<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import {
  NButton,
  NEmpty,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage
} from 'naive-ui';
import {
  fetchAllPageComponents,
  fetchColumnsByTableId,
  fetchTablesByPageCode,
  savePageRule
} from '@/service/api/meta-config';
import { extractFieldRefsFromExpression, isValidIdentifier } from '@/v3/logic/calc-engine';

const props = defineProps<{
  show: boolean;
  rulesJson: string;
  ruleType: 'CALC' | 'AGGREGATE' | 'VALIDATION';
  pageCode: string;
  componentKey: string;
  ruleRow?: any;
}>();
const emit = defineEmits<{
  (e: 'update:show', value: boolean): void;
  (e: 'save', json: string): void;
}>();
const message = useMessage();

// ==================== 类型 ====================
type FormulaMatchType = 'equals' | 'regex' | 'contains' | 'notContains';
type FormulaItem = { key: string; expression: string; matchType: FormulaMatchType };
type CalcItem = {
  field: string;
  expression: string;
  condition?: string;
  order?: number;
  isMultiFormula: boolean;
  formulaField?: string;
  formulas: FormulaItem[];
};
type AggItem = {
  sourceField?: string;
  targetField: string;
  algorithm?: string;
  filter?: string;
  expression?: string;
  sourceTab?: string;
  isExpression: boolean;
};
type ValidationItem = { field: string; rule: string; message: string; value?: any };
type FieldInfo = { columnName: string; headerText: string };
type TableFieldGroup = { tableCode: string; label: string; isMaster: boolean; isCurrent: boolean; fields: FieldInfo[] };
type FieldChoice = {
  tableCode: string;
  tableLabel: string;
  columnName: string;
  headerText: string;
  displayName: string;
  rawRef: string;
  displayRef: string;
};
type ExpressionPreviewToken = {
  type: 'text' | 'field' | 'ambiguous';
  text: string;
  tableLabel?: string;
  matchKey?: string;
};
type ExpressionAmbiguity = {
  matchKey: string;
  text: string;
  options: FieldChoice[];
};
type ExpressionEditorState = {
  text: string;
  storedDisplay: string;
  previewTokens: ExpressionPreviewToken[];
  ambiguities: ExpressionAmbiguity[];
  selections: Record<string, string>;
};

// ==================== 状态 ====================
const calcItems = ref<CalcItem[]>([]);
const aggItems = ref<AggItem[]>([]);
const validationItems = ref<ValidationItem[]>([]);
const availableFields = ref<{ label: string; value: string }[]>([]);
const fieldGroups = ref<TableFieldGroup[]>([]);
const saving = ref(false);
const sidebarFilter = ref('');
const currentTableCode = ref('');
const dialogReady = ref(false);
const editingExpressionKey = ref<string | null>(null);
const expressionEditors = ref<Record<string, ExpressionEditorState>>({});

// ==================== 字段插入联动 ====================
// 记录当前聚焦的输入框信息，点击侧边栏字段时追加到该输入框
type ActiveInput = {
  getValue: () => string;
  setValue: (v: string) => void;
  el: HTMLInputElement | HTMLTextAreaElement | null;
  formatField?: (choice: FieldChoice) => string;
};
const activeInput = ref<ActiveInput | null>(null);
type TrackFocusOptions = {
  event: FocusEvent;
  formatField?: (choice: FieldChoice) => string;
};

function trackFocus(getValue: () => string, setValue: (v: string) => void, options: TrackFocusOptions) {
  activeInput.value = {
    getValue,
    setValue,
    el: options.event.target as HTMLInputElement | HTMLTextAreaElement,
    formatField: options.formatField
  };
}

const singleLineAutosize = { minRows: 1, maxRows: 1 };
const expressionAutosize = { minRows: 1, maxRows: 3 };

function insertField(choice: FieldChoice) {
  const ai = activeInput.value;
  if (!ai) {
    message.info('请先点击一个输入框');
    return;
  }
  const el = ai.el;
  const current = ai.getValue();
  const fieldRef = ai.formatField ? ai.formatField(choice) : choice.displayRef;
  if (el) {
    // 在光标位置插入
    const start = el.selectionStart ?? current.length;
    const end = el.selectionEnd ?? current.length;
    const newVal = current.slice(0, start) + fieldRef + current.slice(end);
    ai.setValue(newVal);
    // 恢复焦点和光标位置
    nextTick(() => {
      el.focus();
      el.setSelectionRange(start + fieldRef.length, start + fieldRef.length);
    });
  } else {
    ai.setValue(current + fieldRef);
  }
}

function formatFieldRef(tableCode: string, columnName: string): string {
  if (isValidIdentifier(tableCode)) {
    return `${tableCode}.${columnName}`;
  }
  return columnName;
}

function formatDisplayFieldRef(tableCode: string, field: FieldInfo): string {
  const displayName = field.headerText || field.columnName;
  if (isValidIdentifier(tableCode)) {
    return `${tableCode}.【${displayName}】`;
  }
  return `【${displayName}】`;
}

type FieldRefPair = { raw: string; display: string };

const qualifiedDisplayPairs = computed<FieldRefPair[]>(() =>
  fieldGroups.value
    .flatMap(group =>
      group.fields.map(field => ({
        raw: formatFieldRef(group.tableCode, field.columnName),
        display: formatDisplayFieldRef(group.tableCode, field)
      }))
    )
    .sort((a, b) => b.raw.length - a.raw.length)
);

const currentBareDisplayPairs = computed<FieldRefPair[]>(() => {
  const currentGroup = fieldGroups.value.find(group => group.tableCode === currentTableCode.value);
  if (!currentGroup) return [];
  return currentGroup.fields
    .map(field => ({
      raw: field.columnName,
      display: `【${field.headerText || field.columnName}】`
    }))
    .sort((a, b) => b.raw.length - a.raw.length);
});

const tableLabelMap = computed(() =>
  Object.fromEntries(fieldGroups.value.map(group => [group.tableCode, group.label]))
);

const allFieldChoices = computed<FieldChoice[]>(() =>
  fieldGroups.value.flatMap(group =>
    group.fields.map(field => {
      const displayName = field.headerText || field.columnName;
      return {
        tableCode: group.tableCode,
        tableLabel: group.label,
        columnName: field.columnName,
        headerText: field.headerText || '',
        displayName,
        rawRef: formatFieldRef(group.tableCode, field.columnName),
        displayRef: formatDisplayFieldRef(group.tableCode, field)
      };
    })
  )
);

const matchableFieldChoices = computed(() => {
  const map = new Map<string, FieldChoice[]>();
  for (const choice of allFieldChoices.value) {
    const names = new Set([choice.displayName, choice.columnName]);
    for (const name of names) {
      if (name) {
        const list = map.get(name) || [];
        if (!list.some(item => item.rawRef === choice.rawRef)) list.push(choice);
        map.set(name, list);
      }
    }
  }
  return map;
});

const matchableNames = computed(() =>
  Array.from(matchableFieldChoices.value.keys()).sort((a, b) => b.length - a.length)
);

function normalizePreviewText(text: string): string {
  return text.replace(/\s*([+\-*/(),])\s*/g, '$1');
}

function getCurrentTableLabel() {
  return tableLabelMap.value[currentTableCode.value] || currentTableCode.value || '当前表';
}

function buildExpressionPreviewTokens(text?: string): ExpressionPreviewToken[] {
  if (!text) return [];
  const tokens: ExpressionPreviewToken[] = [];
  const pattern = /([A-Za-z_]\w*)\.\u3010([^】]+)\u3011|\u3010([^】]+)\u3011/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      const segment = normalizePreviewText(text.slice(lastIndex, match.index));
      if (segment) tokens.push({ type: 'text', text: segment });
    }
    if (match[1] && match[2]) {
      tokens.push({
        type: 'field',
        text: match[2],
        tableLabel: tableLabelMap.value[match[1]] || match[1]
      });
    } else if (match[3]) {
      tokens.push({
        type: 'field',
        text: match[3],
        tableLabel: getCurrentTableLabel()
      });
    }
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < text.length) {
    const segment = normalizePreviewText(text.slice(lastIndex));
    if (segment) tokens.push({ type: 'text', text: segment });
  }
  return tokens;
}

function buildFieldChoice(tableCode: string, field: FieldInfo): FieldChoice {
  const displayName = field.headerText || field.columnName;
  return {
    tableCode,
    tableLabel: tableLabelMap.value[tableCode] || tableCode,
    columnName: field.columnName,
    headerText: field.headerText || '',
    displayName,
    rawRef: formatFieldRef(tableCode, field.columnName),
    displayRef: formatDisplayFieldRef(tableCode, field)
  };
}

function buildMatchKey(text: string, occurrence: number) {
  return `${text}@@${occurrence}`;
}

function isExpressionBoundary(char?: string) {
  return !char || /[\s+\-*/(),?:<>=!&|[\]{}]/.test(char);
}

function buildExpressionEditorStateFromStored(text?: string): ExpressionEditorState {
  const source = text || '';
  const tokens: ExpressionPreviewToken[] = [];
  const selections: Record<string, string> = {};
  const occurrences: Record<string, number> = {};
  const pattern = /([A-Za-z_]\w*)\.\u3010([^】]+)\u3011|\u3010([^】]+)\u3011/g;
  let prettyText = '';
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  while ((match = pattern.exec(source)) !== null) {
    if (match.index > lastIndex) {
      const segment = normalizePreviewText(source.slice(lastIndex, match.index));
      if (segment) {
        tokens.push({ type: 'text', text: segment });
        prettyText += segment;
      }
    }

    const tableCode = match[1] || currentTableCode.value;
    const displayName = match[2] || match[3] || '';
    const choice = allFieldChoices.value.find(item => item.tableCode === tableCode && item.displayName === displayName);
    const tokenText = choice?.displayName || displayName;
    const occurrence = occurrences[tokenText] || 0;
    const matchKey = buildMatchKey(tokenText, occurrence);
    occurrences[tokenText] = occurrence + 1;

    if (choice) {
      selections[matchKey] = choice.rawRef;
      tokens.push({ type: 'field', text: tokenText, tableLabel: choice.tableLabel, matchKey });
    } else {
      tokens.push({ type: 'text', text: tokenText });
    }
    prettyText += tokenText;
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < source.length) {
    const segment = normalizePreviewText(source.slice(lastIndex));
    if (segment) {
      tokens.push({ type: 'text', text: segment });
      prettyText += segment;
    }
  }

  return {
    text: prettyText,
    storedDisplay: source,
    previewTokens: tokens,
    ambiguities: [],
    selections
  };
}

function parseExpressionEditorText(text: string, selections: Record<string, string>): ExpressionEditorState {
  const previewTokens: ExpressionPreviewToken[] = [];
  const ambiguities: ExpressionAmbiguity[] = [];
  const occurrences: Record<string, number> = {};
  let normalizedText = '';
  let storedDisplay = '';
  let i = 0;

  while (i < text.length) {
    let matchedName = '';
    let matchedOptions: FieldChoice[] = [];

    for (const name of matchableNames.value) {
      if (text.startsWith(name, i)) {
        const prev = i > 0 ? text[i - 1] : undefined;
        const next = i + name.length < text.length ? text[i + name.length] : undefined;
        if (isExpressionBoundary(prev) && isExpressionBoundary(next)) {
          matchedName = name;
          matchedOptions = matchableFieldChoices.value.get(name) || [];
          break;
        }
      }
    }

    if (!matchedName) {
      const char = text[i];
      const lastToken = previewTokens[previewTokens.length - 1];
      if (lastToken?.type === 'text') lastToken.text += char;
      else previewTokens.push({ type: 'text', text: char });
      normalizedText += char;
      storedDisplay += char;
      i += 1;
    } else {
      const occurrence = occurrences[matchedName] || 0;
      const matchKey = buildMatchKey(matchedName, occurrence);
      occurrences[matchedName] = occurrence + 1;
      const selectedRaw = selections[matchKey];
      const selectedChoice = matchedOptions.find(item => item.rawRef === selectedRaw);

      if (matchedOptions.length === 1 || selectedChoice) {
        const choice = selectedChoice || matchedOptions[0];
        normalizedText += choice.displayName;
        storedDisplay += choice.displayRef;
        previewTokens.push({
          type: 'field',
          text: choice.displayName,
          tableLabel: choice.tableLabel,
          matchKey
        });
      } else {
        normalizedText += matchedName;
        storedDisplay += matchedName;
        previewTokens.push({
          type: 'ambiguous',
          text: matchedName,
          matchKey
        });
        ambiguities.push({
          matchKey,
          text: matchedName,
          options: matchedOptions
        });
      }
      i += matchedName.length;
    }
  }

  return {
    text: normalizedText,
    storedDisplay,
    previewTokens,
    ambiguities,
    selections: { ...selections }
  };
}

function getExpressionEditorState(key: string, currentValue?: string) {
  const existing = expressionEditors.value[key];
  if (existing) return existing;
  const state = buildExpressionEditorStateFromStored(currentValue);
  expressionEditors.value = { ...expressionEditors.value, [key]: state };
  return state;
}

function updateExpressionEditorState(key: string, text: string, applyValue: (value: string) => void) {
  const current = getExpressionEditorState(key);
  const next = parseExpressionEditorText(text, current.selections);
  expressionEditors.value = { ...expressionEditors.value, [key]: next };
  applyValue(next.storedDisplay);
}

function beginExpressionEdit(key: string, currentValue: string | undefined, applyValue: (value: string) => void) {
  if (editingExpressionKey.value && editingExpressionKey.value !== key) {
    const currentState = expressionEditors.value[editingExpressionKey.value];
    if (currentState?.ambiguities.length) {
      message.warning('请先选择重复字段所属表');
      return;
    }
  }
  const state = buildExpressionEditorStateFromStored(currentValue);
  expressionEditors.value = { ...expressionEditors.value, [key]: state };
  applyValue(state.storedDisplay);
  editingExpressionKey.value = key;
  nextTick(() => {
    const textarea = document.querySelector<HTMLTextAreaElement>(`[data-expression-key="${key}"] textarea`);
    textarea?.focus();
    const len = textarea?.value.length ?? 0;
    textarea?.setSelectionRange(len, len);
  });
}

function endExpressionEdit(key: string, applyValue: (value: string) => void) {
  const state = expressionEditors.value[key];
  if (!state) {
    if (editingExpressionKey.value === key) editingExpressionKey.value = null;
    return;
  }
  if (state.ambiguities.length) {
    message.warning('存在重名字段，请先选择字段所属表');
    return;
  }
  applyValue(state.storedDisplay);
  if (editingExpressionKey.value === key) editingExpressionKey.value = null;
}

type ResolveExpressionAmbiguityPayload = {
  key: string;
  matchKey: string;
  rawRef: string;
  applyValue: (value: string) => void;
};

function resolveExpressionAmbiguity(payload: ResolveExpressionAmbiguityPayload) {
  const { key, matchKey, rawRef, applyValue } = payload;
  const state = getExpressionEditorState(key);
  state.selections[matchKey] = rawRef;
  updateExpressionEditorState(key, state.text, applyValue);
}

function replaceQualifiedRefsWithDisplay(text: string): string {
  return text.replace(/\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b/g, (full, tableCode: string, columnName: string) => {
    const pair = qualifiedDisplayPairs.value.find(item => item.raw === `${tableCode}.${columnName}`);
    return pair?.display || full;
  });
}

function replaceBareRefsWithDisplay(text: string): string {
  return text.replace(/\b([A-Za-z_]\w*)\b/g, (full, identifier: string) => {
    const pair = currentBareDisplayPairs.value.find(item => item.raw === identifier);
    return pair?.display || full;
  });
}

function toDisplayExpression(text?: string): string {
  if (!text) return '';
  return replaceBareRefsWithDisplay(replaceQualifiedRefsWithDisplay(text));
}

function replaceAll(value: string, from: string, to: string): string {
  if (!from || from === to) return value;
  return value.split(from).join(to);
}

function toStoredExpression(text?: string): string {
  if (!text) return '';
  let value = text;
  for (const pair of qualifiedDisplayPairs.value) {
    value = replaceAll(value, pair.display, pair.raw);
  }
  for (const pair of currentBareDisplayPairs.value) {
    value = replaceAll(value, pair.display, pair.raw);
  }
  return value;
}

const titleMap: Record<string, string> = { CALC: '行级计算规则', AGGREGATE: '聚合规则', VALIDATION: '校验规则' };
const dialogTitle = computed(() => `${titleMap[props.ruleType]} - ${props.componentKey}`);
const algorithmOptions = [
  { label: 'SUM (求和)', value: 'SUM' },
  { label: 'AVG (平均)', value: 'AVG' },
  { label: 'COUNT (计数)', value: 'COUNT' },
  { label: 'MAX (最大)', value: 'MAX' },
  { label: 'MIN (最小)', value: 'MIN' }
];
const formulaMatchTypeOptions = [
  { label: '等值', value: 'equals' },
  { label: '包含', value: 'contains' },
  { label: '不包含', value: 'notContains' },
  { label: '正则', value: 'regex' }
];

function resetDialogState(options?: { clearRules?: boolean }) {
  activeInput.value = null;
  editingExpressionKey.value = null;
  expressionEditors.value = {};
  sidebarFilter.value = '';
  currentTableCode.value = '';
  availableFields.value = [];
  fieldGroups.value = [];
  dialogReady.value = false;
  if (options?.clearRules) {
    calcItems.value = [];
    aggItems.value = [];
    validationItems.value = [];
  }
}

function createFieldList(columns: any[]): FieldInfo[] {
  return columns
    .filter((column: any) => column.columnName)
    .map((column: any) => ({
      columnName: column.columnName,
      headerText: column.headerText || ''
    }));
}

function buildFieldOptions(fields: FieldInfo[]) {
  return fields.map(field => ({
    label: field.headerText || field.columnName,
    value: field.columnName
  }));
}

async function loadFieldGroup(
  table: any,
  options: { tableCode: string; isMaster: boolean; isCurrent: boolean; fallbackLabel: string }
): Promise<TableFieldGroup | null> {
  if (!table?.id || !options.tableCode) return null;
  const columns = await fetchColumnsByTableId(table.id);
  return {
    tableCode: options.tableCode,
    label: table.tableName || options.fallbackLabel,
    isMaster: options.isMaster,
    isCurrent: options.isCurrent,
    fields: createFieldList(columns)
  };
}

function findTableByCode(tables: any[], tableCode?: string) {
  return tableCode ? tables.find((table: any) => table.tableCode === tableCode) : null;
}

function shouldLoadSiblingDetailGroups(currentRef?: string, masterRef?: string) {
  const isMasterCalc = props.ruleType === 'CALC' && Boolean(currentRef && currentRef === masterRef);
  return props.ruleType === 'VALIDATION' || props.ruleType === 'AGGREGATE' || isMasterCalc;
}

function getSiblingDetailComponents(allComps: any[], currentRef?: string, masterRef?: string) {
  return allComps.filter(
    (component: any) =>
      component.pageCode === props.pageCode &&
      component.componentType === 'DETAIL_GRID' &&
      component.refTableCode &&
      component.refTableCode !== currentRef &&
      component.refTableCode !== masterRef
  );
}

function mergeFieldGroups(
  currentGroup: TableFieldGroup | null,
  masterGroup: TableFieldGroup | null,
  detailGroups: TableFieldGroup[]
) {
  const groups: TableFieldGroup[] = [];
  if (masterGroup) groups.push(masterGroup);
  if (currentGroup) groups.push(currentGroup);
  groups.push(...detailGroups);
  return groups;
}
const validationRuleOptions = [
  { label: '必填', value: 'required' },
  { label: '最小值', value: 'min' },
  { label: '最大值', value: 'max' },
  { label: '最小长度', value: 'minLength' },
  { label: '最大长度', value: 'maxLength' },
  { label: '正则匹配', value: 'pattern' },
  { label: '自定义', value: 'custom' }
];

function normalizeFormulaMatchType(value: unknown): FormulaMatchType {
  return value === 'regex' || value === 'contains' || value === 'notContains' ? value : 'equals';
}

function getFormulaKeyLabel(matchType: FormulaMatchType): string {
  if (matchType === 'regex') return '正则模式';
  if (matchType === 'contains' || matchType === 'notContains') return '关键词';
  return '分支值';
}

function getFormulaKeyPlaceholder(matchType: FormulaMatchType): string {
  if (matchType === 'regex') return '如: 桶|说明书|小盒';
  if (matchType === 'contains' || matchType === 'notContains') return '如: 胶囊';
  return '如: A';
}

// 侧边栏：根据规则类型过滤显示的字段组
const visibleFieldGroups = computed(() => {
  const groups: TableFieldGroup[] = fieldGroups.value;
  const kw = sidebarFilter.value.trim().toLowerCase();
  if (!kw) return groups;
  return groups
    .map(g => ({
      ...g,
      fields: g.fields.filter(f => f.columnName.toLowerCase().includes(kw) || f.headerText.toLowerCase().includes(kw))
    }))
    .filter(g => g.fields.length > 0);
});

watch(
  () => props.show,
  async val => {
    if (!val) {
      resetDialogState({ clearRules: true });
      return;
    }
    resetDialogState({ clearRules: true });
    await loadAvailableFields();
    parseRulesJson();
    dialogReady.value = true;
  },
  { immediate: true }
);

// ==================== 解析 ====================
function parseRulesJson() {
  try {
    const arr = props.rulesJson ? JSON.parse(props.rulesJson) : [];
    const list = Array.isArray(arr) ? arr : [];
    if (props.ruleType === 'CALC') {
      calcItems.value = list.map((r: any) => {
        const isMulti = Boolean(r.formulaField && r.formulas);
        const formulas: FormulaItem[] = [];
        if (isMulti && r.formulas) {
          for (const [mapKey, f] of Object.entries(r.formulas as Record<string, any>)) {
            formulas.push({
              key: f.key || mapKey,
              expression: toDisplayExpression(f.expression || ''),
              matchType: normalizeFormulaMatchType(f.matchType)
            });
          }
        }
        return {
          field: r.field || '',
          expression: isMulti ? '' : toDisplayExpression(r.expression || ''),
          condition: toDisplayExpression(r.condition || ''),
          order: r.order,
          isMultiFormula: isMulti,
          formulaField: r.formulaField || '',
          formulas
        };
      });
    } else if (props.ruleType === 'AGGREGATE') {
      aggItems.value = list.map((r: any) => ({
        sourceField: r.sourceField || '',
        targetField: r.targetField || '',
        algorithm: r.algorithm || 'SUM',
        filter: toDisplayExpression(r.filter || ''),
        expression: toDisplayExpression(r.expression || ''),
        sourceTab: r.sourceTab || '',
        isExpression: Boolean(r.expression && !r.algorithm)
      }));
    } else {
      validationItems.value = list.map((r: any) => ({
        field: r.field || '',
        rule: r.rule || 'required',
        message: r.message || '',
        value: r.value
      }));
    }
  } catch {
    calcItems.value = [];
    aggItems.value = [];
    validationItems.value = [];
  }
}

// ==================== 字段加载（多表） ====================
async function loadAvailableFields() {
  resetDialogState();
  try {
    const [tables, allComps] = await Promise.all([fetchTablesByPageCode(props.pageCode), fetchAllPageComponents()]);
    if (!tables.length) return;
    const currentComp = allComps?.find(
      (c: any) => c.pageCode === props.pageCode && c.componentKey === props.componentKey
    );
    const masterComp = allComps?.find((c: any) => c.pageCode === props.pageCode && c.componentType === 'GRID');
    const currentRef = currentComp?.refTableCode;
    const masterRef = masterComp?.refTableCode;
    currentTableCode.value = currentRef || '';

    const currentTable = findTableByCode(tables, currentRef);
    const isMaster = Boolean(currentRef && currentRef === masterRef);
    const currentGroup = await loadFieldGroup(currentTable, {
      tableCode: currentRef || '',
      isMaster,
      isCurrent: true,
      fallbackLabel: isMaster ? '主表' : '当前表'
    });

    if (currentGroup) {
      availableFields.value = buildFieldOptions(currentGroup.fields);
    }

    let masterGroup: TableFieldGroup | null = null;
    if (masterRef && masterRef !== currentRef) {
      const masterTable = findTableByCode(tables, masterRef);
      masterGroup = await loadFieldGroup(masterTable, {
        tableCode: masterRef,
        isMaster: true,
        isCurrent: false,
        fallbackLabel: '主表'
      });
    }

    let detailGroups: TableFieldGroup[] = [];
    if (shouldLoadSiblingDetailGroups(currentRef, masterRef)) {
      const siblingComponents = getSiblingDetailComponents(allComps || [], currentRef, masterRef);
      const loadedGroups = await Promise.all(
        siblingComponents.map(async (component: any) => {
          const table = findTableByCode(tables, component.refTableCode);
          return loadFieldGroup(table, {
            tableCode: component.refTableCode,
            isMaster: false,
            isCurrent: false,
            fallbackLabel: '关联表'
          });
        })
      );
      detailGroups = loadedGroups.filter((group): group is TableFieldGroup => Boolean(group));
    }
    fieldGroups.value = mergeFieldGroups(currentGroup, masterGroup, detailGroups);
  } catch {
    /* ignore */
  }
}

// ==================== 操作 ====================
function addItem() {
  if (props.ruleType === 'CALC') {
    calcItems.value.push({
      field: '',
      expression: '',
      condition: '',
      order: calcItems.value.length,
      isMultiFormula: false,
      formulaField: '',
      formulas: []
    });
  } else if (props.ruleType === 'AGGREGATE') {
    aggItems.value.push({
      sourceField: '',
      targetField: '',
      algorithm: 'SUM',
      filter: '',
      expression: '',
      sourceTab: '',
      isExpression: false
    });
  } else {
    validationItems.value.push({ field: '', rule: 'required', message: '', value: undefined });
  }
}

function extractIdentifiers(expression: string): string[] {
  return Array.from(
    extractFieldRefsFromExpression(toStoredExpression(expression), currentTableCode.value || undefined)
  );
}

function buildJson(): string {
  if (props.ruleType === 'CALC') {
    return JSON.stringify(
      calcItems.value.map(item => {
        if (item.isMultiFormula) {
          const formulas: Record<string, any> = {};
          for (const [branchIndex, f] of item.formulas.entries()) {
            if (f.key) {
              formulas[`__branch_${branchIndex}`] = {
                key: f.key,
                expression: toStoredExpression(f.expression),
                triggerFields: extractIdentifiers(f.expression),
                matchType: normalizeFormulaMatchType(f.matchType)
              };
            }
          }
          const r: any = { field: item.field, formulaField: item.formulaField, formulas };
          if (item.condition) r.condition = toStoredExpression(item.condition);
          if (item.order !== null && item.order !== undefined) r.order = item.order;
          return r;
        }
        const r: any = {
          field: item.field,
          expression: toStoredExpression(item.expression),
          triggerFields: extractIdentifiers(item.expression)
        };
        if (item.condition) r.condition = toStoredExpression(item.condition);
        if (item.order !== null && item.order !== undefined) r.order = item.order;
        return r;
      })
    );
  }
  if (props.ruleType === 'AGGREGATE') {
    return JSON.stringify(
      aggItems.value.map(item => {
        if (item.isExpression)
          return { targetField: item.targetField, expression: toStoredExpression(item.expression) };
        const r: any = { sourceField: item.sourceField, targetField: item.targetField, algorithm: item.algorithm };
        if (item.filter) r.filter = toStoredExpression(item.filter);
        if (item.sourceTab) r.sourceTab = item.sourceTab;
        return r;
      })
    );
  }
  return JSON.stringify(
    validationItems.value.map(item => {
      const r: any = { field: item.field, rule: item.rule, message: item.message };
      if (item.value !== undefined && item.value !== '') r.value = item.value;
      return r;
    })
  );
}

function hasUnresolvedExpressionAmbiguity() {
  return Object.values(expressionEditors.value).some(item => item.ambiguities.length > 0);
}

function validateFormulaBranch(item: CalcItem, formula: FormulaItem) {
  if (!formula.key) {
    message.warning(`${item.field}: 分支值不能为空`);
    return false;
  }
  if (formula.matchType === 'regex') {
    try {
      // 仅校验语法合法性
      // eslint-disable-next-line no-new
      new RegExp(formula.key);
    } catch {
      message.warning(`${item.field}.${formula.key || '(空)'}: 正则表达式无效`);
      return false;
    }
  }
  if (!formula.expression) {
    message.warning(`${item.field}.${formula.key}: 表达式不能为空`);
    return false;
  }
  return true;
}

function validateCalcItem(item: CalcItem) {
  if (!item.field) {
    message.warning('目标字段不能为空');
    return false;
  }
  if (!item.isMultiFormula) {
    if (!item.expression) {
      message.warning(`${item.field}: 表达式不能为空`);
      return false;
    }
    return true;
  }
  if (!item.formulaField) {
    message.warning(`${item.field}: 分支字段不能为空`);
    return false;
  }
  if (item.formulas.length === 0) {
    message.warning(`${item.field}: 至少需要一个分支`);
    return false;
  }
  return item.formulas.every(formula => validateFormulaBranch(item, formula));
}

function validateCalcRules() {
  return calcItems.value.every(item => validateCalcItem(item));
}

function validateAggregateRules() {
  return aggItems.value.every(item => {
    if (!item.targetField) {
      message.warning('目标字段不能为空');
      return false;
    }
    if (!item.isExpression && !item.sourceField) {
      message.warning(`${item.targetField}: 源字段不能为空`);
      return false;
    }
    if (item.isExpression && !item.expression) {
      message.warning(`${item.targetField}: 表达式不能为空`);
      return false;
    }
    return true;
  });
}

function validateValidationRules() {
  return validationItems.value.every(item => {
    if (!item.field) {
      message.warning('字段不能为空');
      return false;
    }
    return true;
  });
}

function validate(): boolean {
  if (hasUnresolvedExpressionAmbiguity()) {
    message.warning('存在重名字段未确认所属表');
    return false;
  }
  if (props.ruleType === 'CALC') return validateCalcRules();
  if (props.ruleType === 'AGGREGATE') return validateAggregateRules();
  return validateValidationRules();
}

async function handleSave() {
  if (!validate()) return;
  const json = buildJson();
  if (props.ruleRow) {
    saving.value = true;
    try {
      await savePageRule({ ...props.ruleRow, rules: json });
      message.success('规则已保存');
      emit('save', json);
      emit('update:show', false);
    } catch {
      message.error('保存失败');
    } finally {
      saving.value = false;
    }
  } else {
    emit('save', json);
    emit('update:show', false);
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="dialogTitle"
    style="width: 1060px; max-height: 85vh"
    :mask-closable="true"
    :segmented="{ content: true, footer: true }"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div v-if="dialogReady" class="dialog-body">
      <!-- 左侧：规则编辑区 -->
      <div class="rules-area">
        <!-- CALC -->
        <template v-if="ruleType === 'CALC'">
          <NEmpty v-if="calcItems.length === 0" description="暂无计算规则" />
          <div v-for="(item, idx) in calcItems" :key="idx" class="rule-card">
            <div class="rule-header">
              <NTag size="small" :type="item.isMultiFormula ? 'warning' : 'info'">
                {{ item.isMultiFormula ? '多公式' : '单公式' }}
              </NTag>
              <span class="rule-index">#{{ idx + 1 }}</span>
              <div class="spacer" />
              <NSwitch v-model:value="item.isMultiFormula" size="small">
                <template #checked>多公式</template>
                <template #unchecked>单公式</template>
              </NSwitch>
              <NPopconfirm @positive-click="calcItems.splice(idx, 1)">
                <template #trigger><NButton size="tiny" quaternary type="error">删除</NButton></template>
                确定删除？
              </NPopconfirm>
            </div>
            <div class="rule-row">
              <div class="rule-field">
                <span class="field-label">目标字段</span>
                <NSelect
                  v-model:value="item.field"
                  :options="availableFields"
                  size="small"
                  filterable
                  tag
                  placeholder="输入或选择"
                  class="w-200"
                />
              </div>
              <div class="rule-field">
                <span class="field-label">排序</span>
                <NInputNumber v-model:value="item.order" size="small" class="w-80" />
              </div>
              <div class="rule-field field-grow">
                <span class="field-label">条件 (可选)</span>
                <NInput
                  v-model:value="item.condition"
                  type="textarea"
                  :autosize="singleLineAutosize"
                  size="small"
                  placeholder="如: 【生产属性】 !== '包材'"
                  @focus="
                    (e: FocusEvent) =>
                      trackFocus(
                        () => item.condition || '',
                        v => (item.condition = v),
                        { event: e }
                      )
                  "
                />
              </div>
            </div>
            <template v-if="!item.isMultiFormula">
              <div class="rule-row">
                <div class="rule-field field-grow">
                  <span class="field-label">表达式</span>
                  <template v-if="editingExpressionKey === `calc-expression-${idx}`">
                    <NInput
                      :data-expression-key="`calc-expression-${idx}`"
                      :value="getExpressionEditorState(`calc-expression-${idx}`, item.expression).text"
                      type="textarea"
                      :autosize="expressionAutosize"
                      class="expression-input"
                      size="small"
                      placeholder="如: 每批数量*单价"
                      @update:value="
                        v => updateExpressionEditorState(`calc-expression-${idx}`, v, next => (item.expression = next))
                      "
                      @focus="
                        (e: FocusEvent) =>
                          trackFocus(
                            () => getExpressionEditorState(`calc-expression-${idx}`, item.expression).text,
                            v =>
                              updateExpressionEditorState(
                                `calc-expression-${idx}`,
                                v,
                                next => (item.expression = next)
                              ),
                            { event: e, formatField: choice => choice.displayName }
                          )
                      "
                      @blur="endExpressionEdit(`calc-expression-${idx}`, v => (item.expression = v))"
                    />
                  </template>
                  <template v-else>
                    <div
                      class="expression-preview-block"
                      @click="
                        beginExpressionEdit(`calc-expression-${idx}`, item.expression, v => (item.expression = v))
                      "
                    >
                      <template v-if="item.expression">
                        <template
                          v-for="(token, tokenIdx) in buildExpressionPreviewTokens(item.expression)"
                          :key="tokenIdx"
                        >
                          <span v-if="token.type === 'field'" class="expression-token" :title="token.tableLabel">
                            {{ token.text }}
                          </span>
                          <span v-else>{{ token.text }}</span>
                        </template>
                      </template>
                      <span v-else class="expression-placeholder">点击编辑表达式</span>
                    </div>
                  </template>
                  <div
                    v-if="getExpressionEditorState(`calc-expression-${idx}`, item.expression).ambiguities.length"
                    class="expression-ambiguity-list"
                  >
                    <div
                      v-for="amb in getExpressionEditorState(`calc-expression-${idx}`, item.expression).ambiguities"
                      :key="amb.matchKey"
                      class="expression-ambiguity-item"
                    >
                      <span class="expression-ambiguity-label">“{{ amb.text }}” 属于</span>
                      <NSelect
                        size="small"
                        class="w-220"
                        :value="
                          getExpressionEditorState(`calc-expression-${idx}`, item.expression).selections[
                            amb.matchKey
                          ] || null
                        "
                        :options="amb.options.map(option => ({ label: option.tableLabel, value: option.rawRef }))"
                        @update:value="
                          v =>
                            resolveExpressionAmbiguity({
                              key: `calc-expression-${idx}`,
                              matchKey: amb.matchKey,
                              rawRef: String(v),
                              applyValue: next => (item.expression = next)
                            })
                        "
                      />
                    </div>
                  </div>
                </div>
              </div>
            </template>
            <template v-else>
              <div class="rule-row">
                <div class="rule-field">
                  <span class="field-label">分支字段</span>
                  <NSelect
                    v-model:value="item.formulaField"
                    :options="availableFields"
                    size="small"
                    filterable
                    tag
                    placeholder="选择分支依据"
                    class="w-220"
                  />
                </div>
              </div>
              <div v-for="(f, fi) in item.formulas" :key="fi" class="formula-card">
                <div class="rule-row">
                  <div class="rule-field">
                    <span class="field-label">匹配方式</span>
                    <NSelect
                      v-model:value="f.matchType"
                      :options="formulaMatchTypeOptions"
                      size="small"
                      class="w-100"
                    />
                  </div>
                  <div class="rule-field">
                    <span class="field-label">{{ getFormulaKeyLabel(f.matchType) }}</span>
                    <NInput
                      v-model:value="f.key"
                      size="small"
                      :placeholder="getFormulaKeyPlaceholder(f.matchType)"
                      class="w-180"
                    />
                  </div>
                  <NPopconfirm @positive-click="item.formulas.splice(fi, 1)">
                    <template #trigger>
                      <NButton size="tiny" quaternary type="error" class="align-self-end">删除</NButton>
                    </template>
                    删除此分支？
                  </NPopconfirm>
                </div>
                <div class="rule-row">
                  <div class="rule-field field-grow">
                    <span class="field-label">表达式</span>
                    <template v-if="editingExpressionKey === `calc-branch-${idx}-${fi}`">
                      <NInput
                        :data-expression-key="`calc-branch-${idx}-${fi}`"
                        :value="getExpressionEditorState(`calc-branch-${idx}-${fi}`, f.expression).text"
                        type="textarea"
                        :autosize="expressionAutosize"
                        class="expression-input"
                        size="small"
                        placeholder="如: 批量/每盒片数"
                        @update:value="
                          v => updateExpressionEditorState(`calc-branch-${idx}-${fi}`, v, next => (f.expression = next))
                        "
                        @focus="
                          (e: FocusEvent) =>
                            trackFocus(
                              () => getExpressionEditorState(`calc-branch-${idx}-${fi}`, f.expression).text,
                              v =>
                                updateExpressionEditorState(
                                  `calc-branch-${idx}-${fi}`,
                                  v,
                                  next => (f.expression = next)
                                ),
                              { event: e, formatField: choice => choice.displayName }
                            )
                        "
                        @blur="endExpressionEdit(`calc-branch-${idx}-${fi}`, v => (f.expression = v))"
                      />
                    </template>
                    <template v-else>
                      <div
                        class="expression-preview-block"
                        @click="beginExpressionEdit(`calc-branch-${idx}-${fi}`, f.expression, v => (f.expression = v))"
                      >
                        <template v-if="f.expression">
                          <template
                            v-for="(token, tokenIdx) in buildExpressionPreviewTokens(f.expression)"
                            :key="tokenIdx"
                          >
                            <span v-if="token.type === 'field'" class="expression-token" :title="token.tableLabel">
                              {{ token.text }}
                            </span>
                            <span v-else>{{ token.text }}</span>
                          </template>
                        </template>
                        <span v-else class="expression-placeholder">点击编辑表达式</span>
                      </div>
                    </template>
                    <div
                      v-if="getExpressionEditorState(`calc-branch-${idx}-${fi}`, f.expression).ambiguities.length"
                      class="expression-ambiguity-list"
                    >
                      <div
                        v-for="amb in getExpressionEditorState(`calc-branch-${idx}-${fi}`, f.expression).ambiguities"
                        :key="amb.matchKey"
                        class="expression-ambiguity-item"
                      >
                        <span class="expression-ambiguity-label">“{{ amb.text }}” 属于</span>
                        <NSelect
                          size="small"
                          class="w-220"
                          :value="
                            getExpressionEditorState(`calc-branch-${idx}-${fi}`, f.expression).selections[
                              amb.matchKey
                            ] || null
                          "
                          :options="amb.options.map(option => ({ label: option.tableLabel, value: option.rawRef }))"
                          @update:value="
                            v =>
                              resolveExpressionAmbiguity({
                                key: `calc-branch-${idx}-${fi}`,
                                matchKey: amb.matchKey,
                                rawRef: String(v),
                                applyValue: next => (f.expression = next)
                              })
                          "
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <NButton
                size="tiny"
                dashed
                class="mt-4"
                @click="item.formulas.push({ key: '', expression: '', matchType: 'equals' })"
              >
                + 添加分支
              </NButton>
            </template>
          </div>
        </template>

        <!-- AGGREGATE -->
        <template v-if="ruleType === 'AGGREGATE'">
          <NEmpty v-if="aggItems.length === 0" description="暂无聚合规则" />
          <div v-for="(item, idx) in aggItems" :key="idx" class="rule-card">
            <div class="rule-header">
              <NTag size="small" :type="item.isExpression ? 'warning' : 'success'">
                {{ item.isExpression ? '表达式' : '聚合函数' }}
              </NTag>
              <span class="rule-index">#{{ idx + 1 }}</span>
              <div class="spacer" />
              <NSwitch v-model:value="item.isExpression" size="small">
                <template #checked>表达式</template>
                <template #unchecked>聚合函数</template>
              </NSwitch>
              <NPopconfirm @positive-click="aggItems.splice(idx, 1)">
                <template #trigger><NButton size="tiny" quaternary type="error">删除</NButton></template>
                确定删除？
              </NPopconfirm>
            </div>
            <div class="rule-row">
              <div class="rule-field">
                <span class="field-label">目标字段 (主表)</span>
                <NSelect
                  v-model:value="item.targetField"
                  :options="availableFields"
                  size="small"
                  filterable
                  tag
                  placeholder="输入或选择"
                  class="w-200"
                />
              </div>
            </div>
            <template v-if="!item.isExpression">
              <div class="rule-row">
                <div class="rule-field">
                  <span class="field-label">聚合函数</span>
                  <NSelect v-model:value="item.algorithm" :options="algorithmOptions" size="small" class="w-160" />
                </div>
                <div class="rule-field">
                  <span class="field-label">源字段 (从表)</span>
                  <NSelect
                    v-model:value="item.sourceField"
                    :options="availableFields"
                    size="small"
                    filterable
                    tag
                    placeholder="输入或选择"
                    class="w-200"
                  />
                </div>
              </div>
              <div class="rule-row">
                <div class="rule-field">
                  <span class="field-label">来源Tab (可选)</span>
                  <NInput v-model:value="item.sourceTab" size="small" placeholder="如: CostMaterial" class="w-180" />
                </div>
                <div class="rule-field field-grow">
                  <span class="field-label">过滤条件 (可选)</span>
                  <NInput
                    v-model:value="item.filter"
                    type="textarea"
                    :autosize="singleLineAutosize"
                    size="small"
                    placeholder="如: 【用途】 === '原料'"
                    @focus="
                      (e: FocusEvent) =>
                        trackFocus(
                          () => item.filter || '',
                          v => (item.filter = v),
                          { event: e }
                        )
                    "
                  />
                </div>
              </div>
            </template>
            <template v-else>
              <div class="rule-row">
                <div class="rule-field field-grow">
                  <span class="field-label">表达式</span>
                  <template v-if="editingExpressionKey === `agg-expression-${idx}`">
                    <NInput
                      :data-expression-key="`agg-expression-${idx}`"
                      :value="getExpressionEditorState(`agg-expression-${idx}`, item.expression).text"
                      type="textarea"
                      :autosize="expressionAutosize"
                      class="expression-input"
                      size="small"
                      placeholder="如: 原辅料成本+包材成本"
                      @update:value="
                        v => updateExpressionEditorState(`agg-expression-${idx}`, v, next => (item.expression = next))
                      "
                      @focus="
                        (e: FocusEvent) =>
                          trackFocus(
                            () => getExpressionEditorState(`agg-expression-${idx}`, item.expression).text,
                            v =>
                              updateExpressionEditorState(`agg-expression-${idx}`, v, next => (item.expression = next)),
                            { event: e, formatField: choice => choice.displayName }
                          )
                      "
                      @blur="endExpressionEdit(`agg-expression-${idx}`, v => (item.expression = v))"
                    />
                  </template>
                  <template v-else>
                    <div
                      class="expression-preview-block"
                      @click="beginExpressionEdit(`agg-expression-${idx}`, item.expression, v => (item.expression = v))"
                    >
                      <template v-if="item.expression">
                        <template
                          v-for="(token, tokenIdx) in buildExpressionPreviewTokens(item.expression)"
                          :key="tokenIdx"
                        >
                          <span v-if="token.type === 'field'" class="expression-token" :title="token.tableLabel">
                            {{ token.text }}
                          </span>
                          <span v-else>{{ token.text }}</span>
                        </template>
                      </template>
                      <span v-else class="expression-placeholder">点击编辑表达式</span>
                    </div>
                  </template>
                  <div
                    v-if="getExpressionEditorState(`agg-expression-${idx}`, item.expression).ambiguities.length"
                    class="expression-ambiguity-list"
                  >
                    <div
                      v-for="amb in getExpressionEditorState(`agg-expression-${idx}`, item.expression).ambiguities"
                      :key="amb.matchKey"
                      class="expression-ambiguity-item"
                    >
                      <span class="expression-ambiguity-label">“{{ amb.text }}” 属于</span>
                      <NSelect
                        size="small"
                        class="w-220"
                        :value="
                          getExpressionEditorState(`agg-expression-${idx}`, item.expression).selections[amb.matchKey] ||
                          null
                        "
                        :options="amb.options.map(option => ({ label: option.tableLabel, value: option.rawRef }))"
                        @update:value="
                          v =>
                            resolveExpressionAmbiguity({
                              key: `agg-expression-${idx}`,
                              matchKey: amb.matchKey,
                              rawRef: String(v),
                              applyValue: next => (item.expression = next)
                            })
                        "
                      />
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </template>

        <!-- VALIDATION -->
        <template v-if="ruleType === 'VALIDATION'">
          <NEmpty v-if="validationItems.length === 0" description="暂无校验规则" />
          <div v-for="(item, idx) in validationItems" :key="idx" class="rule-card">
            <div class="rule-header">
              <NTag size="small" type="info">校验</NTag>
              <span class="rule-index">#{{ idx + 1 }}</span>
              <div class="spacer" />
              <NPopconfirm @positive-click="validationItems.splice(idx, 1)">
                <template #trigger><NButton size="tiny" quaternary type="error">删除</NButton></template>
                确定删除？
              </NPopconfirm>
            </div>
            <div class="rule-row">
              <div class="rule-field">
                <span class="field-label">字段</span>
                <NSelect
                  v-model:value="item.field"
                  :options="availableFields"
                  size="small"
                  filterable
                  tag
                  placeholder="输入或选择"
                  class="w-200"
                />
              </div>
              <div class="rule-field">
                <span class="field-label">规则</span>
                <NSelect v-model:value="item.rule" :options="validationRuleOptions" size="small" class="w-140" />
              </div>
              <div v-if="item.rule !== 'required'" class="rule-field">
                <span class="field-label">值</span>
                <NInput v-model:value="item.value" size="small" placeholder="规则值" class="w-140" />
              </div>
            </div>
            <div class="rule-row">
              <div class="rule-field field-grow">
                <span class="field-label">错误提示</span>
                <NInput v-model:value="item.message" size="small" placeholder="校验失败时的提示信息" />
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 右侧：字段参考侧边栏 -->
      <div class="field-sidebar">
        <div class="sidebar-header">字段参考</div>
        <NInput v-model:value="sidebarFilter" size="tiny" placeholder="搜索字段..." clearable class="sidebar-filter" />
        <div class="sidebar-scroll">
          <div v-for="group in visibleFieldGroups" :key="group.tableCode" class="field-group">
            <div class="group-title">
              <NTag size="tiny" :type="group.isMaster ? 'success' : 'info'">{{ group.isMaster ? '主' : '从' }}</NTag>
              <span>{{ group.label }}</span>
            </div>
            <div
              v-for="f in group.fields"
              :key="f.columnName"
              class="field-item"
              @mousedown.prevent="insertField(buildFieldChoice(group.tableCode, f))"
            >
              <span class="field-name">{{ f.headerText || f.columnName }}</span>
            </div>
          </div>
          <NEmpty v-if="visibleFieldGroups.length === 0" description="无字段" size="small" />
        </div>
      </div>
    </div>
    <div v-else class="dialog-loading">
      <NEmpty description="正在加载规则配置..." />
    </div>

    <template #footer>
      <NSpace justify="space-between" size="small">
        <NButton size="small" @click="addItem">+ 添加规则</NButton>
        <NSpace size="small">
          <NButton size="small" @click="emit('update:show', false)">取消</NButton>
          <NButton size="small" type="primary" :loading="saving" @click="handleSave">保存</NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.dialog-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 320px;
}
.dialog-body {
  display: flex;
  gap: 12px;
  max-height: 65vh;
}
.spacer {
  flex: 1;
}
.rules-area {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
  min-width: 0;
}
.field-sidebar {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e8e8e8;
  padding-left: 12px;
}
.sidebar-header {
  font-size: 13px;
  font-weight: 500;
  color: #333;
  margin-bottom: 6px;
}
.sidebar-scroll {
  flex: 1;
  overflow-y: auto;
}
.sidebar-filter {
  margin-bottom: 6px;
}
.field-group {
  margin-bottom: 10px;
}
.group-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
  font-weight: 500;
}
.field-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 4px;
  font-size: 12px;
  border-radius: 3px;
  cursor: pointer;
  user-select: none;
}
.field-item:hover {
  background: #f0f0f0;
}
.field-name {
  color: #2080f0;
  white-space: nowrap;
}
.rule-card {
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: #fafafa;
}
.rule-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.rule-index {
  font-size: 12px;
  color: #999;
}
.rule-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.rule-field {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.field-grow {
  flex: 1;
}
.w-80 {
  width: 80px;
}
.w-100 {
  width: 100px;
}
.w-140 {
  width: 140px;
}
.w-160 {
  width: 160px;
}
.w-180 {
  width: 180px;
}
.w-200 {
  width: 200px;
}
.w-220 {
  width: 220px;
}
.align-self-end {
  align-self: flex-end;
}
.mt-4 {
  margin-top: 4px;
}
.field-label {
  font-size: 12px;
  color: #666;
}
.formula-card {
  border: 1px dashed #d9d9d9;
  border-radius: 4px;
  padding: 8px;
  margin: 6px 0;
  background: #fff;
}
.expression-preview-block {
  min-height: 34px;
  padding: 6px 11px;
  border: 1px solid #d9d9d9;
  border-radius: 3px;
  background: #fff;
  color: #333;
  line-height: 1.6;
  cursor: text;
  white-space: pre-wrap;
  word-break: break-all;
}
.expression-preview-block:hover {
  border-color: #2080f0;
}
.expression-token {
  display: inline-block;
  padding: 0 2px;
  margin: 0 1px;
  border-radius: 3px;
  color: #2080f0;
  background: rgba(32, 128, 240, 0.08);
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}
.expression-token:hover {
  color: #fff;
  background: #2080f0;
}
.expression-token-ambiguous {
  color: #d03050;
  background: rgba(208, 48, 80, 0.08);
}
.expression-token-ambiguous:hover {
  color: #fff;
  background: #d03050;
}
.expression-ambiguity-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px dashed #f0a020;
  border-radius: 4px;
  background: #fffaf0;
}
.expression-ambiguity-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.expression-ambiguity-label {
  font-size: 12px;
  color: #8a5b00;
}
.expression-placeholder {
  color: #999;
}
.expression-input :deep(textarea) {
  overflow-x: hidden !important;
  overflow-y: hidden !important;
  white-space: pre-wrap;
  word-break: break-all;
  resize: none;
}
</style>
