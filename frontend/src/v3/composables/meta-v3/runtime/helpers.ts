function safeStringify(value: unknown): string {
  const seen = new WeakSet<object>();
  return JSON.stringify(value, (_key, current) => {
    if (typeof current === 'function') return `__fn__:${current.toString()}`;
    if (current instanceof RegExp) return `__re__:${current.toString()}`;
    if (current && typeof current === 'object') {
      if (seen.has(current as object)) return '__circular__';
      seen.add(current as object);
    }
    return current;
  });
}

function toUpperToken(value: unknown): string {
  return typeof value === 'string' ? value.trim().toUpperCase() : '';
}

export function findFirstGridKey(components: any[]): string | null {
  const visit = (items: any[]): string | null => {
    for (const item of items) {
      if (item.componentType === 'GRID') return item.componentKey;
      if (Array.isArray(item.children)) {
        const found = visit(item.children);
        if (found) return found;
      }
    }
    return null;
  };
  return visit(components || []);
}

export function flattenComponents(components: any[]): any[] {
  const result: any[] = [];
  const visit = (items: any[]) => {
    for (const item of items || []) {
      result.push(item);
      if (Array.isArray(item.children)) visit(item.children);
    }
  };
  visit(components);
  return result;
}

export function findComponentByKey(components: any[], key: string): any | null {
  const visit = (items: any[]): any | null => {
    for (const item of items) {
      if (item.componentKey === key) return item;
      if (Array.isArray(item.children)) {
        const found = visit(item.children);
        if (found) return found;
      }
    }
    return null;
  };
  return visit(components || []);
}

export function columnDefsEquivalent(left: any[] | undefined | null, right: any[] | undefined | null): boolean {
  if (left === right) return true;
  if (!Array.isArray(left) || !Array.isArray(right)) return false;
  if (left.length !== right.length) return false;
  return safeStringify(left) === safeStringify(right);
}

export function detailColumnDefsMapEquivalent(
  left: Record<string, any[]> | undefined | null,
  right: Record<string, any[]> | undefined | null
): boolean {
  if (left === right) return true;
  if (!left || !right) return false;
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  if (leftKeys.length !== rightKeys.length) return false;
  for (let i = 0; i < leftKeys.length; i++) {
    if (leftKeys[i] !== rightKeys[i]) return false;
    if (!columnDefsEquivalent(left[leftKeys[i]], right[rightKeys[i]])) return false;
  }
  return true;
}

export function shouldUseCalcOnlyHotReload(payload?: Record<string, any>): boolean {
  if (!payload || Object.keys(payload).length === 0) return false;
  const entity = toUpperToken(payload.entity || payload.scope || payload.changeType);
  const ruleType = toUpperToken(payload.ruleType || payload.rule_type || payload.rule);
  const calcLikeRuleTypes = new Set(['CALC', 'AGGREGATE', 'BROADCAST']);
  if (entity && entity !== 'RULE') return false;
  return calcLikeRuleTypes.has(ruleType);
}
