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
