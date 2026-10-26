import { fetchPageComponents } from '@/service/api';
import type {
  PageComponentWithRules,
  PageRule,
  RelationRule,
  SplitLayoutConfig
} from '@/v3/composables/meta-v3/types';
import {
  collectPageRules,
  groupRulesByComponent,
  parseRelationRule,
  parseRoleBindingRule
} from '@/v3/composables/meta-v3/usePageRules';

type LoadedPageComponents = {
  components: PageComponentWithRules[];
  rulesByComponent: Map<string, PageRule[]>;
  masterGridKey?: string;
  detailTabsKey?: string;
  detailType?: string;
  splitConfig?: SplitLayoutConfig;
};

function hasComponentType(components: PageComponentWithRules[], type: string): boolean {
  const visit = (items: PageComponentWithRules[]): boolean => {
    for (const item of items) {
      if (item.componentType === type) return true;
      if (Array.isArray(item.children) && visit(item.children)) return true;
    }
    return false;
  };
  return visit(components || []);
}

function normalizeRole(role?: string): string | null {
  if (!role) return null;
  const normalized = role.trim().toUpperCase();
  return normalized.length > 0 ? normalized : null;
}

export function buildComponentTree(components: PageComponentWithRules[]): PageComponentWithRules[] {
  const hasChildren = components.some(component => Array.isArray(component.children) && component.children.length > 0);
  if (hasChildren) return components;

  const map = new Map<string, PageComponentWithRules>();
  for (const component of components) {
    map.set(component.componentKey, { ...component, children: [] });
  }

  const roots: PageComponentWithRules[] = [];
  for (const component of map.values()) {
    if (component.parentKey && map.has(component.parentKey)) {
      map.get(component.parentKey)!.children!.push(component);
    } else {
      roots.push(component);
    }
  }

  for (const component of map.values()) {
    if (component.children) {
      component.children.sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0));
    }
  }
  roots.sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0));

  return roots;
}

export function injectMasterDetailRoot(components: PageComponentWithRules[]): PageComponentWithRules[] {
  if (hasComponentType(components, 'MASTER_DETAIL')) return components;
  const hasGrid = hasComponentType(components, 'GRID');
  const hasDetailGrid = hasComponentType(components, 'DETAIL_GRID');
  if (!hasGrid || !hasDetailGrid) return components;
  const pageCode = components[0]?.pageCode || '';
  return [
    {
      id: -1,
      pageCode,
      componentKey: '__v3_master_detail__',
      componentType: 'MASTER_DETAIL',
      sortOrder: -1,
      children: components
    } as PageComponentWithRules
  ];
}

export function collectComponentKeysByType(components: PageComponentWithRules[], type: string): string[] {
  const keys: string[] = [];
  const visit = (component: PageComponentWithRules) => {
    if (component.componentType === type) keys.push(component.componentKey);
    if (Array.isArray(component.children)) {
      component.children.forEach(visit);
    }
  };
  components.forEach(visit);
  return keys;
}

export function findComponentByKey(
  components: PageComponentWithRules[],
  key: string
): PageComponentWithRules | null {
  for (const component of components) {
    if (component.componentKey === key) return component;
    if (Array.isArray(component.children)) {
      const found = findComponentByKey(component.children, key);
      if (found) return found;
    }
  }
  return null;
}

export function getComponentConfig(
  components: PageComponentWithRules[],
  key: string
): string | undefined {
  const component = findComponentByKey(components, key);
  return component?.componentConfig;
}

export function getDetailGridComponentConfig(
  components: PageComponentWithRules[],
  key: string
): string | undefined {
  return getComponentConfig(components, key);
}

export async function loadPageComponents(pageCode: string): Promise<LoadedPageComponents | null> {
  const pageRes = await fetchPageComponents(pageCode);
  if (pageRes.error || !pageRes.data) {
    return null;
  }

  const pageComponentsData = pageRes.data as PageComponentWithRules[];
  const pageComponentTree = injectMasterDetailRoot(buildComponentTree(pageComponentsData));
  const rulesByComponent = groupRulesByComponent(collectPageRules(pageComponentTree));
  const layoutKeys = resolveLayoutKeys(pageComponentTree, rulesByComponent);

  return {
    components: pageComponentTree,
    rulesByComponent,
    masterGridKey: layoutKeys.masterGridKey,
    detailTabsKey: layoutKeys.detailTabsKey,
    detailType: layoutKeys.detailType,
    splitConfig: layoutKeys.splitConfig
  };
}

export function resolveLayoutKeys(
  components: PageComponentWithRules[],
  rulesByComponent: Map<string, PageRule[]>
): { masterGridKey?: string; detailTabsKey?: string; detailType?: string; splitConfig?: SplitLayoutConfig } {
  let relation: RelationRule | null = null;
  const roleMap = new Map<string, string>();

  const visit = (component: PageComponentWithRules) => {
    const rules = rulesByComponent.get(component.componentKey) || [];
    const roleRule = parseRoleBindingRule(component.componentKey, rules);
    const normalizedRole = normalizeRole(roleRule?.role);
    if (normalizedRole) roleMap.set(component.componentKey, normalizedRole);

    const relationRule = parseRelationRule(component.componentKey, rules);
    if (relationRule) relation = { ...(relation || {}), ...relationRule };

    if (Array.isArray(component.children)) {
      component.children.forEach(visit);
    }
  };
  components.forEach(visit);

  const relationValue = relation as RelationRule | null;
  let masterGridKey = relationValue?.masterKey;
  let detailTabsKey = relationValue?.detailKey;

  if (!masterGridKey) {
    for (const [key, role] of roleMap.entries()) {
      if (role === 'MASTER_GRID' || role === 'MASTER') {
        masterGridKey = key;
        break;
      }
    }
  }

  if (!detailTabsKey) {
    for (const [key, role] of roleMap.entries()) {
      if (role === 'DETAIL_TABS' || role === 'DETAIL') {
        detailTabsKey = key;
        break;
      }
    }
  }

  if (!masterGridKey) {
    const gridKeys = collectComponentKeysByType(components, 'GRID');
    if (gridKeys.length === 1) masterGridKey = gridKeys[0];
  }

  if (!detailTabsKey) {
    const detailGridKeys = collectComponentKeysByType(components, 'DETAIL_GRID');
    if (detailGridKeys.length > 0) detailTabsKey = 'detailTabs';
  }

  return {
    masterGridKey,
    detailTabsKey,
    detailType: relationValue?.detailType,
    splitConfig: relationValue?.splitConfig
  };
}
