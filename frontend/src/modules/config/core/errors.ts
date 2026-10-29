/**
 * 校验错误的定位（FC-02）：后端 422 VALIDATION_FAILED 和 `POST /api/config/validate` 的每条明细带 `configType`、
 * `configKey`、`path`（C03、C09 第 3 节）。`path` 相对配置项的 `content`，写法如 `levels[0].nodes[1].condition`、
 * `display[3].columns[1].field`、`operations.COST_MATERIAL`（后端 config 的 validation.py、validation_flow.py）。
 */
import type { ErrorDetail } from '../../../contracts/errors';
import { PlatformError } from '../../../contracts/errors';

export interface PathSegment {
  key: string;
  index: number | null;
}

export interface ConfigProblem {
  message: string;
  configType: string | null;
  configKey: string | null;
  path: string | null;
  segments: PathSegment[];
}

/** `levels[0].nodes[1].condition` → [{levels,0},{nodes,1},{condition,null}] */
export function parsePath(path: string | null | undefined): PathSegment[] {
  if (!path) return [];
  const segments: PathSegment[] = [];
  for (const part of path.split('.')) {
    const match = /^([^[\]]*)((?:\[\d+\])*)$/.exec(part);
    if (!match) {
      segments.push({ key: part, index: null });
      continue;
    }
    const indexes = [...match[2].matchAll(/\[(\d+)\]/g)].map(m => Number(m[1]));
    if (indexes.length === 0) segments.push({ key: match[1], index: null });
    indexes.forEach((index, i) => segments.push({ key: i === 0 ? match[1] : '', index }));
  }
  return segments;
}

export function toProblem(detail: ErrorDetail): ConfigProblem {
  return {
    message: detail.message ?? '',
    configType: detail.configType,
    configKey: detail.configKey,
    path: detail.path,
    segments: parsePath(detail.path)
  };
}

/** 422 时取出明细；其他错误返回 null（由调用方按普通错误提示） */
export function problemsOf(error: unknown): ConfigProblem[] | null {
  if (error instanceof PlatformError && error.code === 'VALIDATION_FAILED') {
    const problems = error.details.map(toProblem);
    return problems.length ? problems : [{ message: error.message, configType: null, configKey: null, path: null, segments: [] }];
  }
  return null;
}

export function errorText(error: unknown) {
  if (error instanceof PlatformError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

/** 问题在配置项中的位置文字，例如"第 1 级 · 第 1 个节点 · approvers" */
export function describePath(problem: ConfigProblem) {
  return problem.path ?? '（整个配置项）';
}

/** 取 path 以 `prefix`（例如 `levels`）开头的问题；`index` 给出时只取该行 */
export function problemsUnder(problems: ConfigProblem[], key: string, index?: number) {
  return problems.filter(p => p.segments[0]?.key === key && (index === undefined || p.segments[0]?.index === index));
}
