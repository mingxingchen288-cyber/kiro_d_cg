import type { MetaError, RuntimeLogger, RuntimeStage } from './types';

function formatPrefix(pageCode: string, componentKey?: string, stage?: RuntimeStage) {
  const key = componentKey || '-';
  const st = stage || 'render';
  return `[MetaV3][${pageCode}][${key}][${st}]`;
}

export function createRuntimeLogger(pageCode: string, notifyError?: (message: string) => void): RuntimeLogger {
  return {
    log: (stage, message, componentKey) => {},
    error: (err: MetaError) => {
      const prefix = formatPrefix(err.pageCode, err.componentKey, err.stage);
      console.warn(`${prefix} ${err.code}: ${err.message}`);
      if (notifyError) notifyError(err.message);
    }
  };
}
