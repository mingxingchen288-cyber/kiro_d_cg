/**
 * T-FC-1 配置列表与通用编辑（FC-01、FC-02）：打开列表、编辑并保存一个配置项、显示新版本号；
 * 校验不通过或后端 422 时显示校验明细并定位到配置的具体位置；新建时预填必须写的字段；非管理员看不到入口。
 */
import { describe, expect, it } from 'vitest';
import { PlatformError } from '../../src/contracts/errors';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import { canConfigure, configModule, isConfigModuleInstalled, useConfigShell } from '../../src/modules/config';
import { newContent } from '../../src/modules/config/core/defaults';
import { parsePath } from '../../src/modules/config/core/errors';
import { ItemEditor } from '../../src/modules/config/core/item-editor';
import { createBackend, detail, notifier } from './support';

describe('配置模块装载（C11、FC-01）', () => {
  it('导出 FrontendModule：名称 config，路由 /config；install 只接收 ShellApi', () => {
    expect(configModule.name).toBe('config');
    expect(configModule.routes.map(r => [r.path, r.name])).toEqual([['/config', 'config']]);
    const { shell } = createFakeShell();
    expect(isConfigModuleInstalled()).toBe(false);
    configModule.install(shell);
    expect(useConfigShell()).toBe(shell);
  });

  it('只有管理员角色可以使用：成本会计看不到，系统管理员可以', () => {
    expect(canConfigure(createFakeShell().shell.session)).toBe(false);
    const admin = createFakeShell({ role: { code: 'ADMIN', name: '系统管理员', admin: true } });
    expect(canConfigure(admin.shell.session)).toBe(true);
  });
});

describe('配置项的列表、编辑、保存（FC-02）', () => {
  it('打开字典列表，编辑"启用状态"并保存：先校验再保存，显示新版本号', async () => {
    const backend = createBackend();
    backend.items.set('dict/ENABLE_STATUS', {
      type: 'dict',
      key: 'ENABLE_STATUS',
      name: '启用状态',
      version: 2,
      content: { items: [{ value: '1', label: '启用', order: 1 }] }
    });
    const n = notifier();
    const editor = new ItemEditor(backend.store, 'dict', n);
    await editor.loadList();
    expect(editor.state.items.map(i => [i.key, i.name, i.version])).toEqual([['ENABLE_STATUS', '启用状态', 2]]);

    await editor.open('ENABLE_STATUS');
    editor.state.current!.content.items.push({ value: '0', label: '停用', order: 2 });
    editor.markDirty();
    expect(await editor.save()).toBe(3);

    expect(backend.http.callsTo('POST', '/api/config/validate')[0].body).toEqual({
      items: [
        {
          type: 'dict',
          key: 'ENABLE_STATUS',
          name: '启用状态',
          content: { items: [{ value: '1', label: '启用', order: 1 }, { value: '0', label: '停用', order: 2 }] }
        }
      ]
    });
    expect(backend.http.callsTo('PUT', '/api/config/items/:type/:key')[0].body).toEqual({
      name: '启用状态',
      content: { items: [{ value: '1', label: '启用', order: 1 }, { value: '0', label: '停用', order: 2 }] }
    });
    expect(editor.state.status).toBe('已保存，版本 3');
    expect(editor.state.dirty).toBe(false);
    expect(n.messages).toEqual([{ kind: 'success', text: '启用状态 已保存，版本 3' }]);
  });

  it('后端 422：显示校验明细，定位到配置项和路径，当前版本不变', async () => {
    const backend = createBackend();
    const editor = new ItemEditor(backend.store, 'page', notifier());
    await editor.open('COST_PINGGU');
    editor.state.current!.content.master.formLayout = [{ field: 'GOODSNAME', x: 20, y: 0, w: 8, h: 1 }];
    backend.http.fail(
      'PUT',
      '/api/config/items/:type/:key',
      new PlatformError(422, 'VALIDATION_FAILED', '配置校验不通过', [detail('master.formLayout[0].w', '表单布局越出 24 列', 'page', 'COST_PINGGU')]),
      1
    );
    expect(await editor.save()).toBeNull();
    expect(editor.state.problems).toEqual([
      {
        message: '表单布局越出 24 列',
        configType: 'page',
        configKey: 'COST_PINGGU',
        path: 'master.formLayout[0].w',
        segments: [
          { key: 'master', index: null },
          { key: 'formLayout', index: 0 },
          { key: 'w', index: null }
        ]
      }
    ]);
    expect(editor.state.current!.version).toBe(1);
    expect(backend.get('page', 'COST_PINGGU')?.version).toBe(1);
  });

  it('新建操作和页面：必须写的字段由界面预填，保存时带上', async () => {
    expect(newContent('operation', 'COST_PINGGU.syncPrice', '同步价格')).toMatchObject({ propagation: 'continue', rowNotFound: 'skip' });
    expect(newContent('page', 'GOODS_MANAGE', '物料管理')).toMatchObject({ audit: true, detailMode: 'tabs', saveOperation: 'GOODS_MANAGE.save' });
    expect(newContent('lookup', 'GOODS', '物料')).toMatchObject({ keywordColumns: [] });
    expect(newContent('role', 'COST_ACCOUNTANT', '成本会计')).toMatchObject({ admin: false });

    const backend = createBackend();
    const editor = new ItemEditor(backend.store, 'lookup', notifier());
    editor.create('GOODS', '物料');
    Object.assign(editor.state.current!.content, { table: 'T_COST_GOODS', columns: ['GOODSID', 'NAME', 'SPEC'], keywordColumns: ['GOODSID', 'NAME'], orderBy: 'GOODSID' });
    expect(await editor.save()).toBe(1);
    expect(backend.get('lookup', 'GOODS')?.content).toEqual({
      table: 'T_COST_GOODS',
      columns: ['GOODSID', 'NAME', 'SPEC'],
      keywordColumns: ['GOODSID', 'NAME'],
      orderBy: 'GOODSID'
    });
  });

  it('错误路径的解析：数组下标和对象键分开', () => {
    expect(parsePath('levels[0].nodes[1].condition')).toEqual([
      { key: 'levels', index: 0 },
      { key: 'nodes', index: 1 },
      { key: 'condition', index: null }
    ]);
    expect(parsePath('operations.COST_MATERIAL')).toEqual([
      { key: 'operations', index: null },
      { key: 'COST_MATERIAL', index: null }
    ]);
  });
});
