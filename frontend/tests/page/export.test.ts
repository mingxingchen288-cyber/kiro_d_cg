/**
 * 自定义导出（FP-19，同旧系统成本核算页主表右键的"自定义导出"）：打开页面时取当前角色可用的导出配置，每个配置两项
 * "导出当前""导出所有"；导出当前带主表当前的筛选、高级查询和排序，导出所有都不带；下载文件名取 Content-Disposition。
 * 例子：admin 可用 cost-pinggu-export（物料成本核算表导出），成本会计没有可用的导出配置。
 * 用 contracts 的 C09 模拟实现和 FakeGrid（support.ts）。
 */
import { describe, expect, it, vi } from 'vitest';
import { serverMessageSamples } from '../../src/contracts/fakes/samples';
import { fileNameOf } from '../../src/modules/page/export';
import { openCostPage } from './support';

const EXPORT = 'cost-pinggu-export';
const FILE_NAME = '物料成本核算表导出.xlsx';
/** 后端的写法（queries/exports.py 的 content_disposition）：文件名百分号编码 */
const DISPOSITION = `attachment; filename*=UTF-8''${encodeURIComponent(FILE_NAME)}`;

const SORT = [{ colId: 'DOCID', sort: 'desc' as const }];
const FILTER = { DOCID: { filterType: 'number', type: 'equals', filter: 2550 } };
const ADVANCED = { op: 'and' as const, conditions: [{ field: 'TOTAL_COST', operator: '>=', value: '10' }] };

/** 打开成本核算，导出接口返回物料成本核算表导出.xlsx，记下交给浏览器下载的文件 */
async function openForExport() {
  const saved: Array<{ blob: Blob; fileName: string }> = [];
  const file = new Blob(['xlsx'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const ctx = await openCostPage(
    undefined,
    fake =>
      fake.http.on('POST', '/api/pages/:pageCode/export', () => ({ blob: file, contentDisposition: DISPOSITION })),
    undefined,
    { saveFile: (blob, fileName) => saved.push({ blob, fileName }) }
  );
  await vi.waitFor(() => expect(ctx.runtime.exportMenu()).not.toHaveLength(0));
  // 主表按单据号 2550 筛选、单据号倒序，并用了高级查询"总成本 >= 10"：表格按这份条件取第一页
  ctx.runtime.ui.advanced.value = ADVANCED;
  await ctx.runtime.fetchMasterRows({ startRow: 0, endRow: 100, sortModel: SORT, filterModel: FILTER });
  return { ...ctx, file, saved };
}

describe('主表右键的"自定义导出"子菜单', () => {
  it('admin 打开成本核算：取一次可用的导出配置，物料成本核算表导出有"导出当前""导出所有"两项', async () => {
    const { runtime, fake } = await openForExport();
    expect(fake.http.callsTo('GET', '/api/pages/:pageCode/exports')).toMatchObject([
      { path: '/api/pages/COST_PINGGU/exports' }
    ]);
    expect(runtime.exportMenu()).toEqual([
      { label: '物料成本核算表导出 - 导出当前', exportCode: EXPORT, scope: 'current' },
      { label: '物料成本核算表导出 - 导出所有', exportCode: EXPORT, scope: 'all' }
    ]);
  });

  it('成本会计没有可用的导出配置：子菜单没有项（右键菜单中不出现"自定义导出"）', async () => {
    const { runtime, fake } = await openCostPage(undefined, f =>
      f.http.on('GET', '/api/pages/:pageCode/exports', { items: [] })
    );
    await vi.waitFor(() => expect(fake.http.callsTo('GET', '/api/pages/:pageCode/exports')).toHaveLength(1));
    expect(runtime.exportMenu()).toEqual([]);
  });

  it('收到 config.changed 后以后台请求重新取可用的导出配置', async () => {
    const { runtime, fake } = await openForExport();
    fake.http.on('GET', '/api/pages/:pageCode/exports', { items: [] });
    fake.realtime.push(serverMessageSamples[0]);
    await vi.waitFor(() => expect(fake.http.callsTo('GET', '/api/pages/:pageCode/exports')).toHaveLength(2));
    expect(fake.http.callsTo('GET', '/api/pages/:pageCode/exports')[1].options?.background).toBe(true);
    await vi.waitFor(() => expect(runtime.exportMenu()).toEqual([]));
  });
});

describe('导出', () => {
  it('导出当前：请求带主表当前的筛选、高级查询和排序，下载物料成本核算表导出.xlsx', async () => {
    const { runtime, fake, file, saved } = await openForExport();
    await runtime.exportFile(EXPORT, 'current');
    expect(fake.http.callsTo('POST', '/api/pages/:pageCode/export')).toMatchObject([
      {
        path: '/api/pages/COST_PINGGU/export',
        body: {
          mode: 'config',
          exportCode: EXPORT,
          scope: 'current',
          request: { startRow: 0, endRow: 0, sortModel: SORT, filterModel: FILTER, advanced: ADVANCED }
        }
      }
    ]);
    expect(saved).toEqual([{ blob: file, fileName: FILE_NAME }]);
    expect(fake.messages).toEqual([{ kind: 'success', text: '导出已开始' }]);
  });

  it('导出所有：请求不带筛选、高级查询和排序', async () => {
    const { runtime, fake, saved } = await openForExport();
    await runtime.exportFile(EXPORT, 'all');
    const [call] = fake.http.callsTo('POST', '/api/pages/:pageCode/export');
    expect(call.body).toEqual({
      mode: 'config',
      exportCode: EXPORT,
      scope: 'all',
      request: { startRow: 0, endRow: 0 }
    });
    expect(saved.map(s => s.fileName)).toEqual([FILE_NAME]);
  });
});

describe('下载文件名（同旧系统 parseFileName）', () => {
  it('取 filename*=UTF-8 后面的文件名并解码', () => {
    expect(fileNameOf(DISPOSITION)).toBe(FILE_NAME);
  });

  it('没有 Content-Disposition 或其中没有文件名时为 export.xlsx', () => {
    expect(fileNameOf(null)).toBe('export.xlsx');
    expect(fileNameOf('attachment')).toBe('export.xlsx');
  });
});
