<script setup lang="ts">
import { computed, h, ref, watch } from 'vue';
import {
  NButton,
  NCheckbox,
  NDataTable,
  NDivider,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPopconfirm,
  NPopover,
  NRadio,
  NRadioGroup,
  NScrollbar,
  NSelect,
  NSpace,
  NTabPane,
  NTabs,
  NTag,
  NTree,
  useMessage
} from 'naive-ui';
import type { SelectOption, TreeOption } from 'naive-ui';
import { Icon } from '@iconify/vue';
import {
  addPageToRole,
  addUserToRole,
  createRole,
  deleteRole,
  fetchAllUsers,
  fetchPageButtons,
  fetchPageColumns,
  fetchResourcePermissionTree,
  fetchRoles,
  fetchRowFilterFields,
  fetchUsersByRole,
  removePageFromRole,
  removeUserFromRole,
  searchRoles,
  updateRole,
  updateRolePage
} from '@/service/api/role-manage';
import type {
  PageButtonVO,
  PageColumnVO,
  PageTableColumnsVO,
  ResourcePermissionVO,
  RolePageVO,
  RoleVO,
  RowFilterFieldVO,
  UserRoleVO,
  UserSimpleVO
} from '@/service/api/role-manage';

const message = useMessage();

// 角色图标颜色
const roleColors = ['#10b981', '#f59e0b', '#3b82f6', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4'];
function getRoleColor(index: number) {
  return roleColors[index % roleColors.length];
}
function getRoleInitial(name: string) {
  return name?.charAt(0) || '角';
}

// ==================== 查询面板 ====================
const showSearchPanel = ref(false);

interface SearchCondition {
  field: string;
  fieldLabel: string;
  operator: string;
  value: string;
  enabled: boolean;
  visible: boolean;
}

type TreeLabelRenderProps = { option: TreeOption };

const searchConditions = ref<SearchCondition[]>([
  { field: 'roleCode', fieldLabel: '角色编码', operator: 'like', value: '', enabled: false, visible: true },
  { field: 'roleName', fieldLabel: '角色名称', operator: 'like', value: '', enabled: false, visible: true },
  { field: 'username', fieldLabel: '包含用户', operator: 'like', value: '', enabled: false, visible: true },
  { field: 'pageCode', fieldLabel: '包含页面', operator: 'like', value: '', enabled: false, visible: true }
]);

const STORAGE_KEY = 'permission-search-fields';
function loadFieldSettings() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const visibleFields = JSON.parse(saved) as string[];
      searchConditions.value.forEach(c => {
        c.visible = visibleFields.includes(c.field);
      });
    }
  } catch (e) {
    /* ignore */
  }
}

function saveFieldSettings() {
  const visibleFields = searchConditions.value.filter(c => c.visible).map(c => c.field);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(visibleFields));
}

watch(
  () => searchConditions.value.map(c => c.visible),
  () => saveFieldSettings(),
  { deep: true }
);
loadFieldSettings();

const visibleConditions = computed(() => searchConditions.value.filter(c => c.visible));

const operatorOptions = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: '包含', value: 'like' },
  { label: '开头是', value: 'likeLeft' },
  { label: '结尾是', value: 'likeRight' },
  { label: '大于', value: 'gt' },
  { label: '大于等于', value: 'ge' },
  { label: '小于', value: 'lt' },
  { label: '小于等于', value: 'le' },
  { label: 'IN', value: 'in' }
];

const activeFilters = ref<string[]>([]);
const isSearching = ref(false);

function openSearchPanel() {
  showSearchPanel.value = true;
}

async function executeSearch() {
  const enabledConditions = searchConditions.value.filter(c => c.enabled && c.value);
  if (enabledConditions.length === 0) {
    await loadRoles();
    activeFilters.value = [];
    showSearchPanel.value = false;
    return;
  }
  isSearching.value = true;
  try {
    const conditions = enabledConditions.map(c => ({ field: c.field, operator: c.operator, value: c.value }));
    const data = await searchRoles(conditions);
    roles.value = data || [];
    activeFilters.value = enabledConditions.map(c => {
      const op = operatorOptions.find(o => o.value === c.operator);
      return `${c.fieldLabel} ${op?.label || c.operator} "${c.value}"`;
    });
    showSearchPanel.value = false;
    if (roles.value.length === 0) {
      message.warning('未找到匹配的角色');
      selectedRoleId.value = null;
    } else {
      message.success(`找到 ${roles.value.length} 个角色`);
      selectedRoleId.value = roles.value[0].id ?? null;
    }
  } catch (e) {
    message.error('查询失败');
  } finally {
    isSearching.value = false;
  }
}

async function clearSearch() {
  searchConditions.value.forEach(c => {
    c.enabled = false;
    c.value = '';
  });
  activeFilters.value = [];
  await loadRoles();
}

// ==================== 角色列表 ====================
const roles = ref<RoleVO[]>([]);
const selectedRoleId = ref<number | null>(null);
const loadingRoles = ref(false);

const selectedRole = computed(() => roles.value.find(r => r.id === selectedRoleId.value));
const filteredRoles = computed(() => roles.value);

async function loadRoles() {
  loadingRoles.value = true;
  try {
    const data = await fetchRoles();
    roles.value = data || [];
    if (roles.value.length > 0 && !selectedRoleId.value) {
      selectedRoleId.value = roles.value[0].id ?? null;
    }
  } catch (e) {
    roles.value = [];
  } finally {
    loadingRoles.value = false;
  }
}

function selectRole(id: number) {
  selectedRoleId.value = id;
}

// ==================== 角色编辑弹窗 ====================
const showRoleModal = ref(false);
const roleForm = ref<RoleVO>({ roleCode: '', roleName: '', description: '' });
const isEditRole = ref(false);
const savingRole = ref(false);

function openAddRole() {
  isEditRole.value = false;
  roleForm.value = { roleCode: '', roleName: '', description: '' };
  showRoleModal.value = true;
}

function openEditRole(role: RoleVO, e: Event) {
  e.stopPropagation();
  isEditRole.value = true;
  roleForm.value = { ...role };
  showRoleModal.value = true;
}

async function saveRole() {
  if (!roleForm.value.roleCode || !roleForm.value.roleName) {
    message.warning('请填写角色编码和名称');
    return;
  }
  savingRole.value = true;
  try {
    if (isEditRole.value && roleForm.value.id) {
      await updateRole(roleForm.value.id, roleForm.value);
      message.success('更新成功');
    } else {
      const newRole = await createRole(roleForm.value);
      selectedRoleId.value = newRole.id!;
      message.success('创建成功');
    }
    showRoleModal.value = false;
    await loadRoles();
  } finally {
    savingRole.value = false;
  }
}

async function handleDeleteRole(id: number) {
  await deleteRole(id);
  message.success('删除成功');
  if (selectedRoleId.value === id) selectedRoleId.value = null;
  await loadRoles();
}

// ==================== 角色人员 ====================
const userRoles = ref<UserRoleVO[]>([]);
const loadingUsers = ref(false);
const allUsers = ref<UserSimpleVO[]>([]);

async function loadUserRoles() {
  if (!selectedRoleId.value) return;
  loadingUsers.value = true;
  try {
    const data = await fetchUsersByRole(selectedRoleId.value);
    userRoles.value = data || [];
  } catch (e) {
    userRoles.value = [];
  } finally {
    loadingUsers.value = false;
  }
}

const showAddUserModal = ref(false);
const selectedUserId = ref<number | null>(null);
const addingUser = ref(false);

async function openAddUser() {
  if (allUsers.value.length === 0) {
    allUsers.value = await fetchAllUsers();
  }
  selectedUserId.value = null;
  showAddUserModal.value = true;
}

const availableUsers = computed(() => {
  const existingIds = new Set(userRoles.value.map(ur => ur.userId));
  return allUsers.value.filter(u => !existingIds.has(u.id));
});

const availableUserOptions = computed(() =>
  availableUsers.value.map(u => ({
    label: `${u.realName || u.username} (${u.username})`,
    value: u.id,
    keywords: [u.realName, u.username, String(u.id)].filter(Boolean).join(' ').toLowerCase()
  }))
);

function filterAvailableUserOption(pattern: string, option: SelectOption & { keywords?: string }): boolean {
  const keyword = pattern.trim().toLowerCase();
  if (!keyword) return true;
  const label = typeof option?.label === 'string' ? option.label.toLowerCase() : '';
  return label.includes(keyword) || (option.keywords || '').includes(keyword);
}

async function handleAddUser() {
  if (!selectedUserId.value || !selectedRoleId.value) return;
  addingUser.value = true;
  try {
    await addUserToRole(selectedRoleId.value, { userId: selectedUserId.value });
    message.success('添加成功');
    showAddUserModal.value = false;
    await loadUserRoles();
  } finally {
    addingUser.value = false;
  }
}

async function handleRemoveUser(id: number) {
  await removeUserFromRole(id);
  message.success('解除成功');
  await loadUserRoles();
}

// 人员表格列
const userColumns = [
  { title: '姓名', key: 'realName', render: (row: UserRoleVO) => row.realName || row.username },
  { title: '用户名', key: 'username' },
  {
    title: '操作',
    key: 'action',
    width: 80,
    render: (row: UserRoleVO) => {
      if (!row.id) return null;
      return h(
        NButton,
        { text: true, type: 'error', size: 'small', onClick: () => handleRemoveUser(row.id!) },
        { default: () => '解除' }
      );
    }
  }
];

// ==================== 角色页面（树形权限） ====================
const loadingPages = ref(false);
const resourceTree = ref<ResourcePermissionVO[]>([]);
const checkedKeys = ref<string[]>([]);

// 资源映射表（用于快速查找）
const resourceMap = computed(() => {
  const map = new Map<string, ResourcePermissionVO>();
  function traverse(nodes: ResourcePermissionVO[]) {
    for (const node of nodes) {
      if (node.pageCode) {
        map.set(node.pageCode, node);
      }
      if (node.children?.length) {
        traverse(node.children);
      }
    }
  }
  traverse(resourceTree.value);
  return map;
});

// 加载资源权限树（包含授权状态）
async function loadResourcePermissionTree() {
  if (!selectedRoleId.value) return;
  loadingPages.value = true;
  try {
    const data = await fetchResourcePermissionTree(selectedRoleId.value);
    resourceTree.value = data || [];
    // 从树中提取已授权的pageCode
    checkedKeys.value = extractAuthorizedKeys(resourceTree.value);
  } catch (e) {
    resourceTree.value = [];
    checkedKeys.value = [];
  } finally {
    loadingPages.value = false;
  }
}

// 从树中提取已授权的key（使用pageCode）
function extractAuthorizedKeys(nodes: ResourcePermissionVO[]): string[] {
  const keys: string[] = [];
  function traverse(list: ResourcePermissionVO[]) {
    for (const node of list) {
      if (node.isAuthorized === 1 && node.pageCode) {
        keys.push(node.pageCode);
      }
      if (node.children?.length) {
        traverse(node.children);
      }
    }
  }
  traverse(nodes);
  return keys;
}

// 扩展TreeOption，添加原始数据
interface ExtendedTreeOption extends TreeOption {
  raw?: ResourcePermissionVO;
}

// 将ResourcePermissionVO转换为TreeOption
function convertToTreeOptions(nodes: ResourcePermissionVO[]): ExtendedTreeOption[] {
  return nodes.map(node => ({
    key: node.pageCode || `dir-${node.id}`,
    label: node.resourceName,
    isLeaf: node.resourceType === 'PAGE',
    raw: node,
    children: node.children?.length ? convertToTreeOptions(node.children) : undefined
  }));
}

const treeOptions = computed(() => convertToTreeOptions(resourceTree.value));

// 判断是否是全部按钮权限
function isAllButtonsPolicy(policy: string | undefined): boolean {
  return policy === '["*"]' || !policy;
}

// 自定义树节点渲染
function renderTreeLabel({ option }: TreeLabelRenderProps) {
  const opt = option as ExtendedTreeOption;
  const raw = opt.raw;
  const isPage = raw?.resourceType === 'PAGE';
  const isAuthorized = raw?.isAuthorized === 1;

  // 目录节点：只显示名称
  if (!isPage) {
    return h('span', { class: 'tree-node-label' }, opt.label as string);
  }

  // 页面节点：显示名称 + 按钮权限标签 + 配置按钮
  const children: any[] = [h('span', { class: 'tree-node-label' }, opt.label as string)];

  // 已授权的页面显示三个配置按钮
  if (isAuthorized && raw) {
    children.push(
      h(
        NButton,
        {
          text: true,
          size: 'tiny',
          type: 'primary',
          class: 'ml-2 config-btn',
          onClick: (e: Event) => {
            e.stopPropagation();
            openEditButton(raw);
          }
        },
        { default: () => '配置按钮' }
      )
    );
    children.push(
      h(
        NButton,
        {
          text: true,
          size: 'tiny',
          type: 'primary',
          class: 'ml-1 config-btn',
          onClick: (e: Event) => {
            e.stopPropagation();
            openEditColumn(raw);
          }
        },
        { default: () => '配置列' }
      )
    );
    children.push(
      h(
        NButton,
        {
          text: true,
          size: 'tiny',
          type: 'primary',
          class: 'ml-1 config-btn',
          onClick: (e: Event) => {
            e.stopPropagation();
            openEditRow(raw);
          }
        },
        { default: () => '配置行' }
      )
    );
  }

  return h('span', { class: 'tree-node-content' }, children);
}

// 处理树节点选中变化
async function handleCheckedKeysChange(keys: string[]) {
  if (!selectedRoleId.value) return;

  const oldKeys = new Set(checkedKeys.value);
  const newKeys = new Set(keys);

  // 找出新增的和删除的（排除目录节点）
  const toAdd = keys.filter(k => !oldKeys.has(k) && !k.startsWith('dir-'));
  const toRemove = checkedKeys.value.filter(k => !newKeys.has(k) && !k.startsWith('dir-'));

  // 添加新权限
  for (const pageCode of toAdd) {
    try {
      await addPageToRole(selectedRoleId.value, { pageCode, buttonPolicy: '["*"]' });
    } catch (e) {
      // ignore
    }
  }

  // 移除权限
  for (const pageCode of toRemove) {
    const resource = resourceMap.value.get(pageCode);
    if (resource?.rolePageId) {
      try {
        await removePageFromRole(resource.rolePageId);
      } catch (e) {
        // ignore
      }
    }
  }

  // 重新加载
  await loadResourcePermissionTree();

  if (toAdd.length > 0 || toRemove.length > 0) {
    message.success('权限已更新');
  }
}

// 编辑按钮权限弹窗
const showEditButtonModal = ref(false);
const editButtonForm = ref<{ id?: number; pageCode: string; pageName?: string; buttonPolicy?: string }>({
  pageCode: ''
});
const editingButton = ref(false);
const pageButtons = ref<PageButtonVO[]>([]);
const selectedButtons = ref<string[]>([]);
const loadingButtons = ref(false);
const isAllButtons = ref(true);
const systemDefaultButtonKeys = new Set([
  'addRow',
  'deleteRow',
  'save',
  'approval.apply',
  'approval.approve',
  'approval.reject',
  'approval.cancel',
  'approval.progress',
  'advancedSearch'
]);

// 按钮按分组显示
const groupedButtons = computed(() => {
  const groups = new Map<string, PageButtonVO[]>();
  const seenKeys = new Set<string>();
  for (const btn of pageButtons.value) {
    const groupName = systemDefaultButtonKeys.has(btn.buttonKey) ? '系统默认按钮' : btn.groupName || '';
    const uniqueKey = getButtonUniqueKey(groupName, btn.buttonKey);
    if (seenKeys.has(uniqueKey)) continue;
    seenKeys.add(uniqueKey);
    if (!groups.has(groupName)) {
      groups.set(groupName, []);
    }
    groups.get(groupName)!.push({ ...btn, groupName });
  }
  return Array.from(groups.entries()).map(([groupName, buttons]) => ({ groupName, buttons }));
});

// 生成按钮唯一标识（groupName:buttonKey）
function getButtonUniqueKey(groupName: string, buttonKey: string): string {
  return groupName ? `${groupName}:${buttonKey}` : buttonKey;
}

function normalizeButtonPolicyKeys(keys: string[]): string[] {
  const result = new Set<string>();
  for (const key of keys) {
    const buttonKey = key.includes(':') ? key.slice(key.lastIndexOf(':') + 1) : key;
    result.add(systemDefaultButtonKeys.has(buttonKey) ? getButtonUniqueKey('系统默认按钮', buttonKey) : key);
  }
  return Array.from(result);
}

// 编辑列权限弹窗
const showEditColumnModal = ref(false);
const editColumnForm = ref<{ id?: number; pageCode: string; pageName?: string; columnPolicy?: string }>({
  pageCode: ''
});
const editingColumn = ref(false);
const loadingColumns = ref(false);
const pageTableColumns = ref<PageTableColumnsVO[]>([]);
const activeColumnTab = ref<string>('');
type ColumnPermissionState = { columnName?: string; visible: boolean; editable: boolean };
// 列权限状态：{ tableKey: { columnId|string(columnName): { visible, editable, columnName } } }
const columnPermissions = ref<Record<string, Record<string, ColumnPermissionState>>>({});

function getColumnPolicyKey(column: Pick<PageColumnVO, 'id' | 'columnName'>): string {
  return typeof column.id === 'number' ? String(column.id) : column.columnName;
}

function getColumnPermissionState(tableKey: string, column: Pick<PageColumnVO, 'id' | 'columnName'>) {
  return columnPermissions.value[tableKey]?.[getColumnPolicyKey(column)];
}

function getBaseColumnConfig(
  tableKey: string,
  column: Pick<PageColumnVO, 'id' | 'columnName'>
): { visible: boolean; editable: boolean } {
  const table = pageTableColumns.value.find(t => t.tableKey === tableKey);
  const col = table?.columns.find(c => getColumnPolicyKey(c) === getColumnPolicyKey(column));
  return { visible: col?.visible ?? true, editable: col?.editable ?? true };
}

function ensureColumnPermissionState(
  tableKey: string,
  column: Pick<PageColumnVO, 'id' | 'columnName'>,
  base?: { visible: boolean; editable: boolean }
) {
  if (!columnPermissions.value[tableKey]) {
    columnPermissions.value[tableKey] = {};
  }
  const key = getColumnPolicyKey(column);
  if (!columnPermissions.value[tableKey][key]) {
    const resolvedBase = base ?? getBaseColumnConfig(tableKey, column);
    columnPermissions.value[tableKey][key] = {
      columnName: column.columnName,
      visible: resolvedBase.visible,
      editable: resolvedBase.editable
    };
  }
  return columnPermissions.value[tableKey][key];
}

// 编辑行权限弹窗
const showEditRowModal = ref(false);
const editRowForm = ref<{ id?: number; pageCode: string; pageName?: string; rowPolicy?: string }>({ pageCode: '' });
const editingRow = ref(false);
const loadingRowFields = ref(false);
const rowFilterFields = ref<RowFilterFieldVO[]>([]);

// 行权限配置模式：visual 或 sql
const rowConfigMode = ref<'visual' | 'sql'>('visual');

// 切换模式时清空另一个模式的内容
watch(rowConfigMode, (newMode, oldMode) => {
  if (newMode === 'visual' && oldMode === 'sql') {
    // 切换到可视化模式，清空自定义SQL
    rowCustomSql.value = '';
  } else if (newMode === 'sql' && oldMode === 'visual') {
    // 切换到自定义SQL模式，把可视化生成的SQL填入，然后清空可视化条件
    if (rowConditions.value.length > 0) {
      rowCustomSql.value = generateSqlFromConditions();
    }
    rowConditions.value = [];
    rowConditionLogic.value = 'AND';
  }
});

// 可视化条件
interface RowCondition {
  field: string;
  op: string;
  valueType: 'static' | 'dynamic';
  value: string;
}
const rowConditions = ref<RowCondition[]>([]);
const rowConditionLogic = ref<'AND' | 'OR'>('AND');

// 自定义 SQL
const rowCustomSql = ref('');

// 操作符选项
const rowOperatorOptions = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: '大于', value: 'gt' },
  { label: '大于等于', value: 'ge' },
  { label: '小于', value: 'lt' },
  { label: '小于等于', value: 'le' },
  { label: '包含', value: 'like' },
  { label: '属于', value: 'in' },
  { label: '为空', value: 'isNull' },
  { label: '不为空', value: 'isNotNull' }
];

// 动态值选项
const dynamicValueOptions = [
  { label: '当前用户', value: '${username}' },
  { label: '当前用户ID', value: '${userId}' }
];

// 字段选项（computed）
const fieldOptions = computed(() => {
  return rowFilterFields.value.map(f => ({
    label: f.label,
    value: f.field
  }));
});

// 根据条件生成 SQL
function generateSqlFromConditions(): string {
  if (rowConditions.value.length === 0) return '';

  const parts = rowConditions.value
    .map(cond => {
      const field = cond.field;
      const value = cond.value;

      switch (cond.op) {
        case 'eq':
          return `${field} = ${formatSqlValue(value, cond.valueType)}`;
        case 'ne':
          return `${field} <> ${formatSqlValue(value, cond.valueType)}`;
        case 'gt':
          return `${field} > ${formatSqlValue(value, cond.valueType)}`;
        case 'ge':
          return `${field} >= ${formatSqlValue(value, cond.valueType)}`;
        case 'lt':
          return `${field} < ${formatSqlValue(value, cond.valueType)}`;
        case 'le':
          return `${field} <= ${formatSqlValue(value, cond.valueType)}`;
        case 'like':
          return `${field} LIKE '%${value.replace(/'/g, "''")}%'`;
        case 'in':
          const inValues = value
            .split(',')
            .map(v => formatSqlValue(v.trim(), cond.valueType))
            .join(', ');
          return `${field} IN (${inValues})`;
        case 'isNull':
          return `${field} IS NULL`;
        case 'isNotNull':
          return `${field} IS NOT NULL`;
        default:
          return '';
      }
    })
    .filter(Boolean);

  return parts.join(` ${rowConditionLogic.value} `);
}

function formatSqlValue(value: string, valueType: 'static' | 'dynamic'): string {
  if (valueType === 'dynamic') {
    return value; // ${username} 等占位符直接返回
  }
  // 静态值：数字不加引号，字符串加引号
  if (/^-?\d+(\.\d+)?$/.test(value)) {
    return value;
  }
  return `'${value.replace(/'/g, "''")}'`;
}

// 生成的 SQL（computed）
const generatedSql = computed(() => generateSqlFromConditions());

// 添加条件
function addRowCondition() {
  rowConditions.value.push({
    field: rowFilterFields.value[0]?.field || '',
    op: 'eq',
    valueType: 'static',
    value: ''
  });
}

// 删除条件
function removeRowCondition(index: number) {
  rowConditions.value.splice(index, 1);
}

// 打开按钮权限配置
async function openEditButton(resource: ResourcePermissionVO) {
  editButtonForm.value = {
    id: resource.rolePageId,
    pageCode: resource.pageCode || '',
    pageName: resource.resourceName,
    buttonPolicy: resource.buttonPolicy
  };

  if (resource.buttonPolicy === '["*"]' || !resource.buttonPolicy) {
    isAllButtons.value = true;
    selectedButtons.value = [];
  } else {
    isAllButtons.value = false;
    try {
      selectedButtons.value = normalizeButtonPolicyKeys(JSON.parse(resource.buttonPolicy));
    } catch {
      selectedButtons.value = [];
    }
  }

  loadingButtons.value = true;
  try {
    pageButtons.value = await fetchPageButtons(resource.pageCode || '');
  } catch (e) {
    pageButtons.value = [];
  } finally {
    loadingButtons.value = false;
  }
  showEditButtonModal.value = true;
}

// 打开列权限配置
async function openEditColumn(resource: ResourcePermissionVO) {
  editColumnForm.value = {
    id: resource.rolePageId,
    pageCode: resource.pageCode || '',
    pageName: resource.resourceName,
    columnPolicy: resource.columnPolicy
  };

  // 加载页面的表格列信息
  loadingColumns.value = true;
  try {
    pageTableColumns.value = await fetchPageColumns(resource.pageCode || '');

    // 设置默认选中的 tab
    if (pageTableColumns.value.length > 0) {
      activeColumnTab.value = pageTableColumns.value[0].tableKey;
    }

    // 解析已有的列权限配置，并按当前列 id / columnName 归一
    let rawPolicy: Record<string, any> = {};
    if (resource.columnPolicy) {
      try {
        rawPolicy = JSON.parse(resource.columnPolicy);
      } catch {
        rawPolicy = {};
      }
    }
    columnPermissions.value = {};

    // 初始化每个表格的列权限（基于 COLUMN_METADATA 的 visible/editable 默认值）
    for (const table of pageTableColumns.value) {
      columnPermissions.value[table.tableKey] = {};
      const scopedPolicy =
        rawPolicy?.[table.tableKey] && typeof rawPolicy[table.tableKey] === 'object' ? rawPolicy[table.tableKey] : {};
      for (const col of table.columns) {
        const rawPerm =
          scopedPolicy?.[getColumnPolicyKey(col)] ??
          scopedPolicy?.[col.columnName] ??
          rawPolicy?.[getColumnPolicyKey(col)] ??
          rawPolicy?.[col.columnName];
        columnPermissions.value[table.tableKey][getColumnPolicyKey(col)] = {
          columnName: col.columnName,
          visible: typeof rawPerm?.visible === 'boolean' ? rawPerm.visible : col.visible,
          editable: typeof rawPerm?.editable === 'boolean' ? rawPerm.editable : col.editable
        };
      }
    }
  } catch (e) {
    pageTableColumns.value = [];
  } finally {
    loadingColumns.value = false;
  }
  showEditColumnModal.value = true;
}

// 打开行权限配置
async function openEditRow(resource: ResourcePermissionVO) {
  editRowForm.value = {
    id: resource.rolePageId,
    pageCode: resource.pageCode || '',
    pageName: resource.resourceName,
    rowPolicy: resource.rowPolicy
  };

  // 加载字段列表
  loadingRowFields.value = true;
  try {
    rowFilterFields.value = await fetchRowFilterFields(resource.pageCode || '');
  } catch (e) {
    rowFilterFields.value = [];
  } finally {
    loadingRowFields.value = false;
  }

  // 解析已有的行权限配置
  rowConditions.value = [];
  rowConditionLogic.value = 'AND';
  rowCustomSql.value = '';

  if (resource.rowPolicy) {
    const policy = resource.rowPolicy.trim();
    if (policy.startsWith('{')) {
      // JSON 格式（可视化模式）
      try {
        const json = JSON.parse(policy);
        if (json.mode === 'visual' && json.conditions) {
          rowConfigMode.value = 'visual';
          rowConditionLogic.value = json.logic || 'AND';
          rowConditions.value = json.conditions.map((c: any) => ({
            field: c.field,
            op: c.op,
            valueType: c.valueType || 'static',
            value: c.value
          }));
        } else {
          // 有 sql 字段但不是 visual 模式
          rowConfigMode.value = 'sql';
          rowCustomSql.value = json.sql || '';
        }
      } catch {
        // JSON 解析失败，当作 SQL
        rowConfigMode.value = 'sql';
        rowCustomSql.value = policy;
      }
    } else {
      // 纯 SQL 字符串
      rowConfigMode.value = 'sql';
      rowCustomSql.value = policy;
    }
  } else {
    // 空配置，默认可视化模式
    rowConfigMode.value = 'visual';
  }

  showEditRowModal.value = true;
}

function toggleAllButtons(checked: boolean) {
  isAllButtons.value = checked;
  if (checked) selectedButtons.value = [];
}

// 保存按钮权限
async function handleUpdateButton() {
  if (!editButtonForm.value.id) return;
  editingButton.value = true;
  try {
    const buttonPolicy = isAllButtons.value ? '["*"]' : JSON.stringify(selectedButtons.value);
    await updateRolePage(editButtonForm.value.id, { buttonPolicy });
    message.success('按钮权限更新成功');
    showEditButtonModal.value = false;
    await loadResourcePermissionTree();
  } finally {
    editingButton.value = false;
  }
}

// 切换列可见性
function toggleColumnVisible(tableKey: string, column: PageColumnVO, checked: boolean) {
  const base = getBaseColumnConfig(tableKey, column);
  // 只能缩小权限：如果基础配置是不可见，则不能设为可见
  if (!base.visible && checked) {
    message.warning('该列在基础配置中已设为不可见，无法通过权限放大');
    return;
  }
  const state = ensureColumnPermissionState(tableKey, column, base);
  state.columnName = column.columnName;
  state.visible = checked;
  // 如果设为不可见，则编辑也要设为 false
  if (!checked) {
    state.editable = false;
  }
}

// 切换列可编辑性
function toggleColumnEditable(tableKey: string, column: PageColumnVO, checked: boolean) {
  const base = getBaseColumnConfig(tableKey, column);
  // 只能缩小权限：如果基础配置是不可编辑，则不能设为可编辑
  if (!base.editable && checked) {
    message.warning('该列在基础配置中已设为不可编辑，无法通过权限放大');
    return;
  }
  const state = ensureColumnPermissionState(tableKey, column, base);
  state.columnName = column.columnName;
  state.editable = checked;
}

// 计算当前表格的全选状态
function isAllVisibleChecked(tableKey: string): boolean {
  const table = pageTableColumns.value.find(t => t.tableKey === tableKey);
  if (!table) return false;
  // 只检查基础配置可见的列
  const checkableCols = table.columns.filter(col => col.visible);
  if (checkableCols.length === 0) return false;
  return checkableCols.every(col => {
    return getColumnPermissionState(tableKey, col)?.visible ?? col.visible;
  });
}

function isAllEditableChecked(tableKey: string): boolean {
  const table = pageTableColumns.value.find(t => t.tableKey === tableKey);
  if (!table) return false;
  // 只检查基础配置可编辑且当前可见的列
  const checkableCols = table.columns.filter(col => {
    if (!col.editable) return false; // 基础配置不可编辑的跳过
    const visible = getColumnPermissionState(tableKey, col)?.visible ?? col.visible;
    return visible; // 只检查可见的列
  });
  if (checkableCols.length === 0) return false;
  return checkableCols.every(col => {
    return getColumnPermissionState(tableKey, col)?.editable ?? col.editable;
  });
}

// 全选/取消全选可见
function toggleAllVisible(tableKey: string, checked: boolean) {
  const table = pageTableColumns.value.find(t => t.tableKey === tableKey);
  if (!table) return;

  if (!columnPermissions.value[tableKey]) {
    columnPermissions.value[tableKey] = {};
  }

  for (const col of table.columns) {
    if (!col.visible) continue; // 基础配置不可见的不能操作
    const state = ensureColumnPermissionState(tableKey, col, { visible: col.visible, editable: col.editable });
    state.columnName = col.columnName;
    state.visible = checked;
    // 如果设为不可见，则编辑也要设为 false
    if (!checked) {
      state.editable = false;
    }
  }
}

// 全选/取消全选可编辑
function toggleAllEditable(tableKey: string, checked: boolean) {
  const table = pageTableColumns.value.find(t => t.tableKey === tableKey);
  if (!table) return;

  if (!columnPermissions.value[tableKey]) {
    columnPermissions.value[tableKey] = {};
  }

  for (const col of table.columns) {
    if (!col.editable) continue; // 基础配置不可编辑的不能操作
    const visible = getColumnPermissionState(tableKey, col)?.visible ?? col.visible;
    if (!visible) continue; // 不可见的不能编辑

    const state = ensureColumnPermissionState(tableKey, col, { visible: col.visible, editable: col.editable });
    state.columnName = col.columnName;
    state.editable = checked;
  }
}

// 保存列权限
async function handleUpdateColumn() {
  if (!editColumnForm.value.id) return;
  editingColumn.value = true;
  try {
    // 只保存与基础配置不同的列权限（缩小的部分）
    const policyToSave: Record<string, Record<string, { visible?: boolean; editable?: boolean }>> = {};
    for (const table of pageTableColumns.value) {
      const tablePerms = columnPermissions.value[table.tableKey];
      if (!tablePerms) continue;

      for (const col of table.columns) {
        const perm = tablePerms[getColumnPolicyKey(col)];
        if (!perm) continue;

        // 只保存与基础配置不同的值
        const diff: { columnName?: string; columnId?: number; visible?: boolean; editable?: boolean } = {};
        if (perm.visible !== col.visible) {
          diff.visible = perm.visible;
        }
        if (perm.editable !== col.editable) {
          diff.editable = perm.editable;
        }

        if (Object.keys(diff).length > 0) {
          if (!policyToSave[table.tableKey]) {
            policyToSave[table.tableKey] = {};
          }
          if (typeof col.id === 'number') {
            diff.columnId = col.id;
          }
          diff.columnName = col.columnName;
          policyToSave[table.tableKey][getColumnPolicyKey(col)] = diff;
        }
      }
    }

    const columnPolicy = Object.keys(policyToSave).length > 0 ? JSON.stringify(policyToSave) : '';
    await updateRolePage(editColumnForm.value.id, { columnPolicy });
    message.success('列权限更新成功');
    showEditColumnModal.value = false;
    await loadResourcePermissionTree();
  } finally {
    editingColumn.value = false;
  }
}

// 保存行权限
async function handleUpdateRow() {
  if (!editRowForm.value.id) return;
  editingRow.value = true;
  try {
    let rowPolicy = '';

    if (rowConfigMode.value === 'visual') {
      if (rowConditions.value.length > 0) {
        // 可视化模式：保存 JSON + SQL
        const sql = generateSqlFromConditions();
        rowPolicy = JSON.stringify({
          mode: 'visual',
          logic: rowConditionLogic.value,
          conditions: rowConditions.value.map(c => ({
            field: c.field,
            fieldLabel: rowFilterFields.value.find(f => f.field === c.field)?.label || c.field,
            op: c.op,
            valueType: c.valueType,
            value: c.value
          })),
          sql
        });
      }
    } else {
      // 自定义 SQL 模式：直接保存 SQL
      rowPolicy = rowCustomSql.value.trim();
    }

    await updateRolePage(editRowForm.value.id, { rowPolicy });
    message.success('行权限更新成功');
    showEditRowModal.value = false;
    await loadResourcePermissionTree();
  } finally {
    editingRow.value = false;
  }
}

// ==================== 监听和初始化 ====================
watch(selectedRoleId, async () => {
  loadUserRoles();
  loadResourcePermissionTree();
});

loadRoles();
</script>

<template>
  <div class="permission-page">
    <!-- 左侧：角色列表 -->
    <div class="role-panel">
      <div class="panel-header">
        <span class="panel-title">角色管理</span>
      </div>

      <div class="panel-toolbar">
        <NButton size="small" @click="openSearchPanel">
          <template #icon><Icon icon="mdi:magnify" /></template>
          查询
        </NButton>
        <NButton type="primary" size="small" @click="openAddRole">
          <template #icon><Icon icon="mdi:plus" /></template>
          新增
        </NButton>
      </div>

      <!-- 筛选条件 -->
      <div v-if="activeFilters.length > 0" class="filter-tags">
        <NTag v-for="(f, i) in activeFilters" :key="i" size="small" closable @close="clearSearch">{{ f }}</NTag>
        <NButton text size="tiny" type="error" @click="clearSearch">清除</NButton>
      </div>

      <NScrollbar class="role-list">
        <div
          v-for="(role, idx) in filteredRoles"
          :key="role.id ?? 0"
          class="role-card"
          :class="{ active: selectedRoleId === role.id }"
          @click="role.id && selectRole(role.id)"
        >
          <div class="role-icon" :style="{ background: getRoleColor(idx) }">
            {{ getRoleInitial(role.roleName) }}
          </div>
          <div class="role-info">
            <div class="role-name">{{ role.roleName }}</div>
            <div class="role-code">{{ role.roleCode }}</div>
          </div>
          <NPopover trigger="click" placement="bottom">
            <template #trigger>
              <NButton quaternary circle size="tiny" class="role-menu-btn" @click.stop>
                <template #icon><Icon icon="mdi:dots-vertical" /></template>
              </NButton>
            </template>
            <div class="role-menu">
              <div class="role-menu-item" @click="openEditRole(role, $event)">
                <Icon icon="mdi:pencil-outline" />
                编辑
              </div>
              <NPopconfirm v-if="role.id" @positive-click="handleDeleteRole(role.id)">
                <template #trigger>
                  <div class="role-menu-item danger">
                    <Icon icon="mdi:delete-outline" />
                    删除
                  </div>
                </template>
                确定删除「{{ role.roleName }}」？
              </NPopconfirm>
            </div>
          </NPopover>
        </div>
        <NEmpty v-if="filteredRoles.length === 0" description="暂无角色" class="mt-8" />
      </NScrollbar>
    </div>

    <!-- 中间分隔线 -->
    <div class="panel-divider">
      <div class="divider-btn">
        <Icon icon="mdi:chevron-left" />
      </div>
    </div>

    <!-- 右侧：详情区域 -->
    <div class="detail-panel">
      <template v-if="selectedRole">
        <div class="detail-header">
          <div class="header-left">
            <NTag type="success" size="small">激活角色</NTag>
            <span class="role-title">{{ selectedRole.roleName }}</span>
          </div>
        </div>

        <NTabs type="line" animated class="detail-tabs">
          <!-- Tab1: 人员列表 -->
          <NTabPane name="users" tab="人员列表">
            <div class="tab-header">
              <NButton type="primary" size="small" @click="openAddUser">
                <template #icon><Icon icon="mdi:plus" /></template>
                分配人员
              </NButton>
            </div>
            <div class="tab-content">
              <NDataTable
                :columns="userColumns"
                :data="userRoles"
                :loading="loadingUsers"
                :bordered="false"
                size="small"
                :pagination="{ pageSize: 10 }"
              />
            </div>
          </NTabPane>

          <!-- Tab2: 页面权限配置 -->
          <NTabPane name="pages" tab="页面权限配置">
            <div class="tab-content">
              <div class="permission-section">
                <div class="section-header">
                  <div class="section-title">
                    <span class="title-bar"></span>
                    功能权限树
                  </div>
                  <div class="section-tip">勾选页面授权，点击「配置」设置按钮权限</div>
                </div>

                <div class="tree-container">
                  <NTree
                    :data="treeOptions"
                    :checked-keys="checkedKeys"
                    :render-label="renderTreeLabel"
                    checkable
                    cascade
                    selectable
                    expand-on-click
                    default-expand-all
                    @update:checked-keys="handleCheckedKeysChange"
                  />
                  <NEmpty v-if="treeOptions.length === 0" description="暂无页面" />
                </div>
              </div>
            </div>
          </NTabPane>
        </NTabs>
      </template>

      <div v-else class="empty-state">
        <Icon icon="mdi:shield-off-outline" class="empty-icon" />
        <div class="empty-text">请选择一个角色</div>
      </div>
    </div>

    <!-- 角色编辑弹窗 -->
    <NModal v-model:show="showRoleModal" preset="card" :title="isEditRole ? '编辑角色' : '新增角色'" class="w-420px">
      <NForm label-placement="left" label-width="70" size="small">
        <NFormItem label="角色编码" required>
          <NInput v-model:value="roleForm.roleCode" placeholder="请输入" :disabled="isEditRole" />
        </NFormItem>
        <NFormItem label="角色名称" required>
          <NInput v-model:value="roleForm.roleName" placeholder="请输入" />
        </NFormItem>
        <NFormItem label="描述">
          <NInput v-model:value="roleForm.description" type="textarea" placeholder="请输入" :rows="3" />
        </NFormItem>
      </NForm>
      <template #footer>
        <div class="modal-footer">
          <NButton size="small" @click="showRoleModal = false">取消</NButton>
          <NButton type="primary" size="small" :loading="savingRole" @click="saveRole">确定</NButton>
        </div>
      </template>
    </NModal>

    <!-- 添加用户弹窗 -->
    <NModal v-model:show="showAddUserModal" preset="card" title="分配人员" class="w-380px">
      <NSelect
        v-model:value="selectedUserId"
        :options="availableUserOptions"
        :filter="filterAvailableUserOption"
        placeholder="请选择用户"
        filterable
        clearable
        size="small"
      />
      <template #footer>
        <div class="modal-footer">
          <NButton size="small" @click="showAddUserModal = false">取消</NButton>
          <NButton type="primary" size="small" :loading="addingUser" :disabled="!selectedUserId" @click="handleAddUser">
            确定
          </NButton>
        </div>
      </template>
    </NModal>

    <!-- 查询面板 -->
    <NModal v-model:show="showSearchPanel" preset="card" class="w-560px">
      <template #header>
        <div class="search-header">
          <span>查询条件</span>
          <NPopover trigger="click" placement="bottom-end">
            <template #trigger>
              <NButton quaternary circle size="small">
                <template #icon><Icon icon="mdi:cog-outline" /></template>
              </NButton>
            </template>
            <div class="field-settings">
              <div class="settings-title">显示字段</div>
              <div v-for="cond in searchConditions" :key="cond.field" class="field-setting-item">
                <NCheckbox v-model:checked="cond.visible" size="small">{{ cond.fieldLabel }}</NCheckbox>
              </div>
            </div>
          </NPopover>
        </div>
      </template>
      <div class="search-condition-list">
        <div v-for="cond in visibleConditions" :key="cond.field" class="search-condition-row">
          <NCheckbox v-model:checked="cond.enabled" class="condition-label">{{ cond.fieldLabel }}</NCheckbox>
          <NSelect v-model:value="cond.operator" :options="operatorOptions" size="small" class="condition-operator" />
          <NInput
            v-model:value="cond.value"
            size="small"
            class="condition-value"
            :placeholder="cond.operator === 'in' ? '多个值用逗号分隔' : '请输入'"
            @input="
              () => {
                if (cond.value) cond.enabled = true;
              }
            "
            @keyup.enter="executeSearch"
          />
        </div>
        <NEmpty v-if="visibleConditions.length === 0" description="请在设置中选择要显示的字段" size="small" />
      </div>
      <template #footer>
        <div class="search-footer">
          <NButton size="small" @click="clearSearch">重置</NButton>
          <NSpace :size="8">
            <NButton size="small" @click="showSearchPanel = false">取消</NButton>
            <NButton type="primary" size="small" :loading="isSearching" @click="executeSearch">查询</NButton>
          </NSpace>
        </div>
      </template>
    </NModal>

    <!-- 编辑按钮权限弹窗 -->
    <NModal v-model:show="showEditButtonModal" preset="card" title="配置按钮权限" style="width: 1000px">
      <NForm label-placement="left" label-width="70" size="small">
        <NFormItem label="页面">
          <NInput :value="editButtonForm.pageName || editButtonForm.pageCode" disabled />
        </NFormItem>
        <NFormItem label="按钮权限">
          <div class="button-policy-section">
            <NCheckbox :checked="isAllButtons" @update:checked="toggleAllButtons">全部按钮</NCheckbox>
            <div v-if="!isAllButtons" class="button-select-list">
              <template v-if="loadingButtons"><span class="loading-text">加载中...</span></template>
              <template v-else-if="pageButtons.length === 0">
                <span class="empty-text-small">该页面暂无按钮配置</span>
              </template>
              <template v-else>
                <div v-for="group in groupedButtons" :key="group.groupName" class="button-group">
                  <div class="button-group-title">{{ group.groupName || '通用' }}</div>
                  <div class="button-group-items">
                    <NCheckbox
                      v-for="btn in group.buttons"
                      :key="getButtonUniqueKey(group.groupName, btn.buttonKey)"
                      :checked="selectedButtons.includes(getButtonUniqueKey(group.groupName, btn.buttonKey))"
                      @update:checked="
                        (checked: boolean) => {
                          const uniqueKey = getButtonUniqueKey(group.groupName, btn.buttonKey);
                          if (checked) {
                            selectedButtons.push(uniqueKey);
                          } else {
                            selectedButtons = selectedButtons.filter(k => k !== uniqueKey);
                          }
                        }
                      "
                    >
                      {{ btn.buttonLabel }}
                    </NCheckbox>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </NFormItem>
      </NForm>
      <template #footer>
        <div class="modal-footer">
          <NButton size="small" @click="showEditButtonModal = false">取消</NButton>
          <NButton type="primary" size="small" :loading="editingButton" @click="handleUpdateButton">确定</NButton>
        </div>
      </template>
    </NModal>

    <!-- 编辑列权限弹窗 -->
    <NModal v-model:show="showEditColumnModal" preset="card" title="配置列权限" style="width: 800px">
      <div class="column-modal-header">
        <span class="page-label">页面：{{ editColumnForm.pageName || editColumnForm.pageCode }}</span>
      </div>

      <template v-if="loadingColumns">
        <div class="loading-container">加载中...</div>
      </template>
      <template v-else-if="pageTableColumns.length === 0">
        <NEmpty description="该页面暂无列配置" />
      </template>
      <template v-else>
        <NTabs v-model:value="activeColumnTab" type="line" size="small">
          <NTabPane
            v-for="table in pageTableColumns"
            :key="table.tableKey"
            :name="table.tableKey"
            :tab="table.tableName"
          >
            <div class="column-table-container">
              <NDataTable
                :columns="[
                  { title: '列名', key: 'headerText', width: 150 },
                  { title: '列名', key: 'columnName', width: 150 },
                  {
                    title: () =>
                      h('div', { class: 'column-header-with-checkbox' }, [
                        h(NCheckbox, {
                          checked: isAllVisibleChecked(table.tableKey),
                          onUpdateChecked: (checked: boolean) => toggleAllVisible(table.tableKey, checked)
                        }),
                        h('span', '可见')
                      ]),
                    key: 'visible',
                    width: 100,
                    render: (row: PageColumnVO) =>
                      h(NCheckbox, {
                        checked: getColumnPermissionState(table.tableKey, row)?.visible ?? row.visible,
                        disabled: !row.visible,
                        onUpdateChecked: (checked: boolean) => toggleColumnVisible(table.tableKey, row, checked)
                      })
                  },
                  {
                    title: () =>
                      h('div', { class: 'column-header-with-checkbox' }, [
                        h(NCheckbox, {
                          checked: isAllEditableChecked(table.tableKey),
                          onUpdateChecked: (checked: boolean) => toggleAllEditable(table.tableKey, checked)
                        }),
                        h('span', '可编辑')
                      ]),
                    key: 'editable',
                    width: 100,
                    render: (row: PageColumnVO) =>
                      h(NCheckbox, {
                        checked: getColumnPermissionState(table.tableKey, row)?.editable ?? row.editable,
                        disabled:
                          !row.editable || !(getColumnPermissionState(table.tableKey, row)?.visible ?? row.visible),
                        onUpdateChecked: (checked: boolean) => toggleColumnEditable(table.tableKey, row, checked)
                      })
                  }
                ]"
                :data="table.columns"
                :bordered="false"
                size="small"
                :max-height="400"
              />
            </div>
          </NTabPane>
        </NTabs>
      </template>

      <template #footer>
        <div class="modal-footer">
          <NButton size="small" @click="showEditColumnModal = false">取消</NButton>
          <NButton type="primary" size="small" :loading="editingColumn" @click="handleUpdateColumn">确定</NButton>
        </div>
      </template>
    </NModal>

    <!-- 编辑行权限弹窗 -->
    <NModal v-model:show="showEditRowModal" preset="card" title="配置行权限" style="width: 700px">
      <div class="row-modal-header">
        <span class="page-label">页面：{{ editRowForm.pageName || editRowForm.pageCode }}</span>
      </div>

      <div class="row-config-mode">
        <span class="mode-label">配置方式：</span>
        <NRadioGroup v-model:value="rowConfigMode" size="small">
          <NRadio value="visual">可视化配置</NRadio>
          <NRadio value="sql">自定义SQL</NRadio>
        </NRadioGroup>
      </div>

      <!-- 可视化配置模式 -->
      <template v-if="rowConfigMode === 'visual'">
        <div class="row-visual-section">
          <div class="condition-header">
            <span>满足</span>
            <NSelect
              v-model:value="rowConditionLogic"
              :options="[
                { label: '全部', value: 'AND' },
                { label: '任一', value: 'OR' }
              ]"
              size="small"
              style="width: 80px"
            />
            <span>条件时可见：</span>
          </div>

          <template v-if="loadingRowFields">
            <div class="loading-container">加载中...</div>
          </template>
          <template v-else>
            <div class="condition-list">
              <div v-for="(cond, index) in rowConditions" :key="index" class="condition-row">
                <NSelect
                  v-model:value="cond.field"
                  :options="fieldOptions"
                  size="small"
                  style="width: 140px"
                  placeholder="选择字段"
                  filterable
                />
                <NSelect v-model:value="cond.op" :options="rowOperatorOptions" size="small" style="width: 100px" />
                <template v-if="cond.op !== 'isNull' && cond.op !== 'isNotNull'">
                  <NSelect
                    v-model:value="cond.valueType"
                    :options="[
                      { label: '固定值', value: 'static' },
                      { label: '动态值', value: 'dynamic' }
                    ]"
                    size="small"
                    style="width: 90px"
                  />
                  <template v-if="cond.valueType === 'dynamic'">
                    <NSelect
                      v-model:value="cond.value"
                      :options="dynamicValueOptions"
                      size="small"
                      style="flex: 1"
                      placeholder="选择动态值"
                    />
                  </template>
                  <template v-else>
                    <NInput
                      v-model:value="cond.value"
                      size="small"
                      style="flex: 1"
                      :placeholder="cond.op === 'in' ? '多个值用逗号分隔' : '输入值'"
                    />
                  </template>
                </template>
                <NButton quaternary circle size="small" @click="removeRowCondition(index)">
                  <template #icon><Icon icon="mdi:close" /></template>
                </NButton>
              </div>

              <NButton dashed size="small" style="width: 100%" @click="addRowCondition">
                <template #icon><Icon icon="mdi:plus" /></template>
                添加条件
              </NButton>
            </div>

            <div v-if="generatedSql" class="generated-sql">
              <div class="sql-label">生成的SQL（只读）：</div>
              <div class="sql-content">{{ generatedSql }}</div>
            </div>
          </template>
        </div>
      </template>

      <!-- 自定义SQL模式 -->
      <template v-else>
        <div class="row-sql-section">
          <NInput
            v-model:value="rowCustomSql"
            type="textarea"
            placeholder="SQL WHERE 条件，如：DEPT_ID = 1 或 CREATE_BY = ${username}"
            :rows="5"
          />
          <div class="row-policy-tip">
            <div>支持占位符：</div>
            <div class="tip-item">
              <code>${userId}</code>
              - 当前用户ID
            </div>
            <div class="tip-item">
              <code>${username}</code>
              - 当前用户名
            </div>
            <div class="tip-item warning">⚠️ 请确保SQL语法正确，避免使用 1=2、1=0 等永假条件</div>
          </div>
        </div>
      </template>

      <template #footer>
        <div class="modal-footer">
          <NButton size="small" @click="showEditRowModal = false">取消</NButton>
          <NButton type="primary" size="small" :loading="editingRow" @click="handleUpdateRow">确定</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.permission-page {
  display: flex;
  height: 100%;
  background: #f5f7fa;
}

/* 左侧角色面板 */
.role-panel {
  width: 280px;
  min-width: 280px;
  background: #fff;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e8e8e8;
}

.panel-header {
  padding: 16px 16px 12px;
  border-bottom: 1px solid #f0f0f0;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  color: #333;
}

.panel-toolbar {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
}

.filter-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 8px 16px;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
  align-items: center;
}

.role-list {
  flex: 1;
  padding: 8px;
}

.role-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  margin-bottom: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.role-card:hover {
  background: #f5f5f5;
}

.role-card.active {
  background: #e6f7ff;
  border: 1px solid #91d5ff;
}

.role-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  flex-shrink: 0;
}

.role-info {
  flex: 1;
  min-width: 0;
}

.role-name {
  font-size: 14px;
  font-weight: 500;
  color: #333;
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-code {
  font-size: 12px;
  color: #999;
}

.role-menu-btn {
  opacity: 0;
  transition: opacity 0.2s;
}

.role-card:hover .role-menu-btn {
  opacity: 1;
}

.role-menu {
  min-width: 100px;
}

.role-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
  color: #333;
}

.role-menu-item:hover {
  background: #f5f5f5;
}

.role-menu-item.danger {
  color: #ff4d4f;
}

.role-menu-item.danger:hover {
  background: #fff1f0;
}

/* 分隔线 */
.panel-divider {
  width: 12px;
  background: #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.divider-btn {
  width: 16px;
  height: 40px;
  background: #e8e8e8;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
}

/* 右侧详情面板 */
.detail-panel {
  flex: 1;
  background: #fff;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.role-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.detail-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.detail-tabs :deep(.n-tabs-nav) {
  padding: 0 20px;
}

.detail-tabs :deep(.n-tab-pane) {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0;
}

.tab-header {
  display: flex;
  justify-content: flex-end;
  padding: 12px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.tab-content {
  flex: 1;
  padding: 16px 20px;
  overflow: auto;
}

/* 权限区块 */
.permission-section {
  margin-bottom: 16px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  color: #333;
}

.section-tip {
  font-size: 12px;
  color: #9ca3af;
}

.title-bar {
  width: 3px;
  height: 14px;
  background: #1890ff;
  border-radius: 2px;
}

.tree-container {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 12px;
  max-height: 500px;
  overflow: auto;
}

/* 树节点样式 */
.tree-node-content {
  display: inline-flex;
  align-items: center;
}

.tree-node-label {
  font-size: 13px;
}

.ml-2 {
  margin-left: 8px;
}

.config-btn {
  opacity: 0;
  transition: opacity 0.2s;
}

.tree-container :deep(.n-tree-node:hover) .config-btn {
  opacity: 1;
}

/* 空状态 */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.empty-icon {
  font-size: 60px;
  color: #d1d5db;
}

.empty-text {
  color: #9ca3af;
  margin-top: 16px;
}

/* 弹窗 */
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* 查询面板 */
.search-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 32px;
}

.search-condition-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.search-condition-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.condition-label {
  width: 100px;
}

.condition-operator {
  width: 100px;
}

.condition-value {
  flex: 1;
}

.search-footer {
  display: flex;
  justify-content: space-between;
}

/* 字段设置 */
.field-settings {
  min-width: 140px;
}

.settings-title {
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 8px;
}

.field-setting-item {
  padding: 4px 0;
}

/* 按钮权限 */
.button-policy-section {
  width: 100%;
}

.button-select-list {
  padding: 8px;
  background: #fafafa;
  border-radius: 4px;
  margin-top: 8px;
}

.button-group {
  margin-bottom: 12px;
}

.button-group:last-child {
  margin-bottom: 0;
}

.button-group-title {
  font-size: 13px;
  font-weight: 500;
  color: #333;
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #e8e8e8;
}

.button-group-items {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.loading-text,
.empty-text-small {
  font-size: 12px;
  color: #9ca3af;
}

/* 列权限弹窗 */
.column-modal-header {
  margin-bottom: 12px;
}

.page-label {
  font-size: 14px;
  color: #666;
}

.column-table-container {
  border: 1px solid #e8e8e8;
  border-radius: 4px;
}

.loading-container {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: #9ca3af;
}

.column-header-with-checkbox {
  display: flex;
  align-items: center;
  gap: 4px;
}

.row-policy-tip {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 8px;
  padding: 8px;
  background: #f9fafb;
  border-radius: 4px;
}

.row-policy-tip .tip-item {
  margin-top: 4px;
}

.row-policy-tip .tip-item.warning {
  color: #f59e0b;
  margin-top: 8px;
}

.row-policy-tip code {
  background: #e5e7eb;
  padding: 1px 4px;
  border-radius: 2px;
  font-family: monospace;
}

/* 行权限弹窗 */
.row-modal-header {
  margin-bottom: 16px;
}

.row-config-mode {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f0f0;
}

.mode-label {
  font-size: 14px;
  color: #333;
}

.row-visual-section {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
  background: #fafafa;
}

.condition-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 14px;
  color: #333;
}

.condition-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.condition-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
}

.generated-sql {
  margin-top: 16px;
  padding: 12px;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
}

.sql-label {
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 4px;
}

.sql-content {
  font-family: monospace;
  font-size: 13px;
  color: #333;
  word-break: break-all;
}

.row-sql-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 工具类 */
.mt-4 {
  margin-top: 16px;
}

.mt-8 {
  margin-top: 32px;
}
.ml-1 {
  margin-left: 4px;
}
</style>
