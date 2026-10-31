/**
 * 审计追踪（第 8 批 G3；config 的 CF-18 只读页面、write-pipeline 的 WP-22 视图 PF_AUDIT_LOG_V；同旧系统 auditLog：
 * cmx 表元数据 146、视图 V_COST_AUDIT_LOG，菜单"审计追踪"，只有系统管理员能打开）。
 *
 * 待主代理合并后运行：页面用了本组新加的写法（页面 saveOperation 为 null、实体读视图），要先合并、执行
 * `platform db upgrade`（迁移 wp_0003 建视图）、重启后端，再执行 `.reports/batch8-20261031/g3-audit-export/save_audit_log_config.py`
 * 把 entity/page AUDIT_LOG 和 role/ADMIN 的键写进 d_cg。
 *
 * 场景（业务例子）：admin 经平台复制 200680（只有主表）得到测试成本单，备注为 PF_TEST 标记；在成本核算页把备注改成"审计测试"
 * 并保存。打开审计追踪（/page/AUDIT_LOG），按记录ID 筛选这张单据：
 * - 修改：一行操作类型 UPDATE、表编码 COST_PINGGU、表名称"物料成本核算表"、字段编码 MEMO、字段"备注"、修改前为原备注、
 *   修改后"审计测试"、操作用户 admin（旧系统写成一段文字"字段「备注」原值「…」新值「审计测试」"，这里每个字段一行）；
 * - 新增：复制时的 INSERT 中备注一行，修改前为空、修改后为原备注。
 * 页面只读：工具栏没有"保存"，双击格子不能编辑；ID 不显示。成本会计 chengben01 读这个页面视图为 403。
 * 测试成本单和命令记录（审计差异在命令记录里）在用例结束时删掉。
 */
import {
  type Page,
  canEdit,
  cell,
  edit,
  expect,
  filterColumn,
  header,
  masterGrid,
  openDoc,
  openPage,
  save,
  test,
  toast,
  toolbar
} from './support';

type AuditRow = { values: Record<string, string | null> };

async function auditRows(page: Page, docId: string) {
  await openPage(page, 'AUDIT_LOG');
  const { body } = await filterColumn(page, 'RECORD_ID', docId);
  return (body.rows as AuditRow[]).filter(r => r.values.RECORD_ID === docId && r.values.TABLE_CODE === 'COST_PINGGU');
}

test('admin 改测试成本单的备注后，审计追踪按记录ID 查出 INSERT 和 UPDATE 的备注行；页面只读，成本会计不能打开', async ({
  page,
  data,
  as,
  apiOf
}) => {
  const { docId } = await data.copyDoc('200680', { details: 'none' });
  await openDoc(page, docId);
  await edit(page, await cell(masterGrid(page), docId, 'MEMO'), '审计测试');
  expect((await save(page)).outcome).toBe('saved');
  await toast(page, '已保存');

  const rows = await auditRows(page, docId);
  const memo = (type: string) => rows.find(r => r.values.OPERATION_TYPE === type && r.values.FIELD_CODE === 'MEMO');
  const updated = memo('UPDATE');
  expect(updated?.values).toMatchObject({
    USER_NAME: 'admin',
    PAGE_CODE: 'COST_PINGGU',
    TABLE_NAME: '物料成本核算表',
    FIELD_NAME: '备注',
    OLD_VALUE: data.marker,
    NEW_VALUE: '审计测试'
  });
  expect(memo('INSERT')?.values).toMatchObject({ OLD_VALUE: null, NEW_VALUE: data.marker });

  // 表格里这一行（row-id 为视图的 ID）显示同样的值
  const grid = masterGrid(page);
  const rowId = String(updated!.values.ID);
  await expect(await cell(grid, rowId, 'FIELD_NAME')).toHaveText('备注');
  await expect(await cell(grid, rowId, 'OLD_VALUE')).toHaveText(data.marker);
  await expect(await cell(grid, rowId, 'NEW_VALUE')).toHaveText('审计测试');
  await expect(await cell(grid, rowId, 'OPERATION_TYPE')).toHaveText('UPDATE');
  await expect(header(grid, 'ID')).toHaveCount(0);

  // 只读：没有保存按钮，格子不能编辑
  await expect(toolbar(page).getByRole('button', { name: '保存', exact: true })).toHaveCount(0);
  expect(await canEdit(page, await cell(grid, rowId, 'NEW_VALUE'))).toBe(false);

  // 只给系统管理员（旧 T_COST_ROLE_PAGE 142）
  const accountant = await as('chengben01');
  const denied = await apiOf(accountant).send('GET', '/api/pages/AUDIT_LOG/view');
  expect(denied.status).toBe(403);
  expect(denied.body.code).toBe('PERMISSION_DENIED');
});
