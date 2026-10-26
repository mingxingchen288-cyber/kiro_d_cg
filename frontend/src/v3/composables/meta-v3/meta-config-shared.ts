import type { LookupRule } from '@/v3/composables/meta-v3/useMetaColumns';
import type { PageRule } from '@/v3/composables/meta-v3/types';

export function uniqueKeys(keys: Array<string | undefined | null>): string[] {
  const result: string[] = [];
  const seen = new Set<string>();

  for (const key of keys) {
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(key);
  }

  return result;
}

export function collectRulesByKeys(rulesByComponent: Map<string, PageRule[]>, keys: string[]): PageRule[] {
  const result: PageRule[] = [];

  for (const key of keys) {
    const rules = rulesByComponent.get(key);
    if (rules && rules.length > 0) {
      result.push(...rules);
    }
  }

  return result;
}

export function mergeLookupRules(metadataRules: LookupRule[], pageRules: LookupRule[]): LookupRule[] {
  const map = new Map<string, LookupRule>();

  for (const rule of metadataRules || []) {
    if (rule?.columnName) {
      map.set(rule.columnName, rule);
    }
  }

  for (const rule of pageRules || []) {
    if (rule?.columnName) {
      map.set(rule.columnName, rule);
    }
  }

  return Array.from(map.values());
}
