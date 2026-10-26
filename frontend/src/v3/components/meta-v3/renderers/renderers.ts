let initialized = false;

export function initComponentRenderers(): void {
  if (initialized) return;
  initialized = true;
  const modules = import.meta.glob('./*.renderer.ts', { eager: true });
  for (const mod of Object.values(modules)) {
    const register = (mod as { register?: () => void }).register;
    if (typeof register === 'function') register();
  }
}
