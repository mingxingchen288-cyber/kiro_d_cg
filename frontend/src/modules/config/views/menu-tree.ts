/**
 * 一体化配置左侧的菜单树（同旧系统 UnifiedConfigPage.vue）：数据来自 `menu` 配置项（C06 第 9 节），
 * 拖动调整顺序和上级（before / after 同级排序，inside 放进分组），改动后保存这个菜单配置项。
 * 没有挂在任何菜单下的页面列在"未挂菜单的页面"下，也可以配置。
 */
import type { MenuNode } from '../core/types';

export interface TreeNode {
  key: string;
  label: string;
  kind: MenuNode['kind'] | 'menu' | 'orphans';
  menuKey: string;
  nodeKey: string | null;
  pageCode: string | null;
  children?: TreeNode[];
}

const ICON: Record<string, string> = { group: '📁', page: '📄', config: '⚙', admin: '⚙', menu: '🗂', orphans: '📂' };
export const iconOf = (kind: string) => ICON[kind] ?? '📄';

export function buildTree(
  menus: Array<{ key: string; name: string; content: { items: MenuNode[] } }>,
  pages: Array<{ key: string; name: string }>
): TreeNode[] {
  const placed = new Set<string>();
  const walk = (menuKey: string, items: MenuNode[]): TreeNode[] =>
    items.map(item => {
      if (item.pageCode) placed.add(item.pageCode);
      const children = item.children?.length ? walk(menuKey, item.children) : undefined;
      return {
        key: `${menuKey}/${item.key}`,
        label: item.title,
        kind: item.kind,
        menuKey,
        nodeKey: item.key,
        pageCode: item.pageCode ?? null,
        ...(children ? { children } : {})
      };
    });
  const roots: TreeNode[] = menus.map(menu => ({
    key: `menu:${menu.key}`,
    label: menu.name,
    kind: 'menu',
    menuKey: menu.key,
    nodeKey: null,
    pageCode: null,
    children: walk(menu.key, menu.content.items)
  }));
  const orphans = pages.filter(p => !placed.has(p.key));
  if (orphans.length) {
    roots.push({
      key: 'orphans',
      label: '未挂菜单的页面',
      kind: 'orphans',
      menuKey: '',
      nodeKey: null,
      pageCode: null,
      children: orphans.map(p => ({ key: `orphan/${p.key}`, label: p.name, kind: 'page', menuKey: '', nodeKey: null, pageCode: p.key }))
    });
  }
  return roots;
}

export function filterTree(nodes: TreeNode[], keyword: string): TreeNode[] {
  const k = keyword.trim().toLowerCase();
  if (!k) return nodes;
  const out: TreeNode[] = [];
  for (const node of nodes) {
    const match = node.label.toLowerCase().includes(k) || (node.pageCode ?? '').toLowerCase().includes(k);
    const children = node.children ? filterTree(node.children, keyword) : [];
    if (match || children.length) out.push({ ...node, ...(node.children ? { children: children.length ? children : node.children } : {}) });
  }
  return out;
}

function take(items: MenuNode[], key: string): MenuNode | null {
  const index = items.findIndex(i => i.key === key);
  if (index >= 0) return items.splice(index, 1)[0];
  for (const item of items) {
    const found = item.children ? take(item.children, key) : null;
    if (found) return found;
  }
  return null;
}

function siblingsOf(items: MenuNode[], key: string): MenuNode[] | null {
  if (items.some(i => i.key === key)) return items;
  for (const item of items) {
    const found = item.children ? siblingsOf(item.children, key) : null;
    if (found) return found;
  }
  return null;
}

export function findNode(items: MenuNode[], key: string): MenuNode | null {
  for (const item of items) {
    if (item.key === key) return item;
    const found = item.children ? findNode(item.children, key) : null;
    if (found) return found;
  }
  return null;
}

/** 在同一个菜单配置项内移动节点；`inside` 只能放进分组。返回 false 表示没有移动 */
export function moveNode(items: MenuNode[], dragKey: string, targetKey: string, position: 'before' | 'after' | 'inside') {
  if (dragKey === targetKey) return false;
  const target = findNode(items, targetKey);
  if (!target || (position === 'inside' && target.kind !== 'group')) return false;
  const dragged = findNode(items, dragKey);
  if (!dragged || (dragged.children && findNode(dragged.children, targetKey))) return false;
  take(items, dragKey);
  if (position === 'inside') {
    target.children = [...(target.children ?? []), dragged];
    return true;
  }
  const siblings = siblingsOf(items, targetKey)!;
  const index = siblings.findIndex(i => i.key === targetKey);
  siblings.splice(position === 'after' ? index + 1 : index, 0, dragged);
  return true;
}

export function removeNode(items: MenuNode[], key: string) {
  return take(items, key) !== null;
}

/**
 * 菜单图标的常用选项（FC-16），同旧系统 SectionBasicInfo.vue 第 33–54 行的 20 个；下拉可以输入其他 Iconify 图标名，
 * 例如旧菜单资源里的 mdi:calculator-variant、mdi:domain（cmx `T_COST_RESOURCE.ICON`）。
 */
export const ICON_OPTIONS: Array<{ label: string; value: string }> = [
  { label: '📁 文件夹', value: 'mdi:folder' },
  { label: '📄 文件', value: 'mdi:file-document' },
  { label: '📊 图表', value: 'mdi:chart-bar' },
  { label: '🧮 计算器', value: 'mdi:calculator-variant' },
  { label: '📦 包裹', value: 'mdi:package-variant' },
  { label: '🚚 运输', value: 'mdi:truck-delivery' },
  { label: '💰 货币', value: 'mdi:currency-usd' },
  { label: '👥 用户', value: 'mdi:account-group' },
  { label: '🔒 锁', value: 'mdi:lock' },
  { label: '⚙ 设置', value: 'mdi:cog' },
  { label: '🏢 部门', value: 'mdi:office-building' },
  { label: '📋 列表', value: 'mdi:format-list-bulleted' },
  { label: '🔍 搜索', value: 'mdi:magnify' },
  { label: '📝 编辑', value: 'mdi:pencil' },
  { label: '📈 趋势', value: 'mdi:trending-up' },
  { label: '🏭 工厂', value: 'mdi:factory' },
  { label: '💊 药品', value: 'mdi:pill' },
  { label: '🧪 实验', value: 'mdi:flask' },
  { label: '📑 审批', value: 'mdi:file-check' },
  { label: '🗂 归档', value: 'mdi:archive' }
];

/** 下拉的选项：常用图标，再加上当前值（输入的、不在常用里的图标也能显示出来） */
export function iconOptions(current: string | null | undefined) {
  if (!current || ICON_OPTIONS.some(o => o.value === current)) return ICON_OPTIONS;
  return [...ICON_OPTIONS, { label: current, value: current }];
}

/** 菜单配置项中这一项的图标 */
export function iconOfNode(items: MenuNode[], key: string): string | null {
  return findNode(items, key)?.icon ?? null;
}

/** 改这一项的图标；空值去掉 `icon`（外壳用默认图标）。返回 false 表示菜单中没有这一项 */
export function setNodeIcon(items: MenuNode[], key: string, icon: string | null | undefined) {
  const node = findNode(items, key);
  if (!node) return false;
  const value = icon?.trim();
  if (value) node.icon = value;
  else delete node.icon;
  return true;
}

/** 页面挂在哪个菜单项下：菜单配置项编码和菜单项编码；没有挂在菜单下时为 null */
export function menuItemOfPage(
  menus: Array<{ key: string; content: { items: MenuNode[] } }>,
  pageCode: string
): { menuKey: string; nodeKey: string } | null {
  const walk = (items: MenuNode[]): MenuNode | null => {
    for (const item of items) {
      if (item.kind === 'page' && item.pageCode === pageCode) return item;
      const found = item.children ? walk(item.children) : null;
      if (found) return found;
    }
    return null;
  };
  for (const menu of menus) {
    const found = walk(menu.content.items);
    if (found) return { menuKey: menu.key, nodeKey: found.key };
  }
  return null;
}
