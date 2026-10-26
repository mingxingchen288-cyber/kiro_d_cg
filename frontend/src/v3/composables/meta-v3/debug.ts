const DEBUG_KEY = 'metaV3Debug';

export function isDebugEnabled(): boolean {
  try {
    if (import.meta?.env?.VITE_META_V3_DEBUG === 'true') return true;
  } catch {
    // ignore
  }
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage?.getItem(DEBUG_KEY) === '1';
  } catch {
    return false;
  }
}

export function debugLog(...args: any[]) {
  if (!isDebugEnabled()) return;
  // Prefix for filtering in console
}
