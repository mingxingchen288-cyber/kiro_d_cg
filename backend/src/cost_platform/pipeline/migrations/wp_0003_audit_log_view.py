"""审计追踪视图 PF_AUDIT_LOG_V（WP-22）：把 PF_COMMAND 的审计差异（WP-11，每条命令一段 JSON）展开成一条命令、一行数据、
一个字段一行，列对应旧系统审计追踪页 auditLog 的视图 V_COST_AUDIT_LOG。审计追踪页（只读页面，config 的 CF-18）读它。

| 列 | 旧视图 | 取值 |
|---|---|---|
| ID | ID | 命令开始时间（YYYYMMDDHH24MISSFF6）-用户-请求键-行序号-字段序号：按它升序即按时间先后，同一秒内按请求键（旧页面默认按 ID 升序） |
| USER_NAME | USER_NAME | 命令用户的登录名（PF_USER.USERNAME；账号已删除时为用户编号） |
| OPERATION_TIME | OPERATION_TIME | 命令完成时间（FINISHED_AT） |
| PAGE_CODE | PAGE_CODE | 命令的页面 |
| TABLE_CODE | TABLE_CODE | 审计差异的实体（审批写没注册的表时为表名，WP-19） |
| TABLE_NAME | TABLE_NAME | 实体配置的名称；没有时同 TABLE_CODE |
| RECORD_ID | RECORD_ID | 行的主键（rowKey），文本 |
| OPERATION_TYPE | OPERATION_TYPE | add、modify、delete 写成旧系统的 INSERT、UPDATE、DELETE |
| FIELD_CODE、FIELD_NAME、OLD_VALUE、NEW_VALUE | FIELD_CHANGES | 旧系统一行记录的全部字段写在一段文字里（"字段「标题」原值「a」新值「b」"），这里每个字段一行：字段名、字段标题（实体配置当前的 label，没有时为字段名）、修改前、修改后（审计差异中的文本，空值为空，是非为 true/false） |
| CREATE_TIME | CREATE_TIME | 命令开始时间（CREATED_AT） |

只展开已完成（status 为 done）、有审计差异的命令。审计差异中字段是对象的键，Oracle 19c 的 JSON_TABLE 取不到键名，所以先用
正则把 `{"MEMO": {"old": …}, …}` 改写成 `[{"field": "MEMO", "old": …}, …]` 再展开：JSON 字符串中的双引号都转义成 `\\"`，
`[{,]` 后面紧跟的双引号只能是字段名的开头，改写不会碰到值。值超过 4000 字节时为空（JSON_TABLE 默认 NULL ON ERROR）。

读 PF_USER（identity）和 PF_CONFIG_ITEM（config 的实体配置），排在 id_0001、cf_0001 之后。旧系统的审计数据
（cmx T_COST_AUDIT_LOG）不迁移，这里只有新平台产生的命令。
"""

from alembic import op

revision = "wp_0003"
down_revision = "wp_0002"
branch_labels = None
depends_on = ("id_0001", "cf_0001")

VIEW = "PF_AUDIT_LOG_V"

_FIELDS_AS_ARRAY = (
    "REGEXP_REPLACE(REGEXP_REPLACE(r.fields, '([{,])\\s*\"([^\"\\\\]+)\"\\s*:\\s*\\{', '\\1{\"field\":\"\\2\",'), "
    "'^\\s*\\{(.*)\\}\\s*$', '[\\1]', 1, 0, 'n')"
)

SELECT = (
    "SELECT TO_CHAR(c.created_at, 'YYYYMMDDHH24MISSFF6') || '-' || c.user_id || '-' || c.request_key || '-' "
    "|| LPAD(r.row_no, 5, '0') || '-' || LPAD(f.field_no, 4, '0') AS ID, "
    "COALESCE(u.username, c.user_id) AS USER_NAME, c.finished_at AS OPERATION_TIME, c.page AS PAGE_CODE, "
    "r.entity AS TABLE_CODE, COALESCE(e.name, r.entity) AS TABLE_NAME, r.row_key AS RECORD_ID, "
    "CASE r.op WHEN 'add' THEN 'INSERT' WHEN 'modify' THEN 'UPDATE' WHEN 'delete' THEN 'DELETE' ELSE UPPER(r.op) END "
    "AS OPERATION_TYPE, f.field_code AS FIELD_CODE, COALESCE(l.label, f.field_code) AS FIELD_NAME, "
    "f.old_value AS OLD_VALUE, f.new_value AS NEW_VALUE, c.created_at AS CREATE_TIME "
    "FROM pf_command c "
    "CROSS APPLY JSON_TABLE(c.audit_diff, '$[*]' COLUMNS (row_no FOR ORDINALITY, entity VARCHAR2(64) PATH '$.entity', "
    "row_key VARCHAR2(200) PATH '$.rowKey', op VARCHAR2(16) PATH '$.op', fields CLOB FORMAT JSON PATH '$.fields')) r "
    f"CROSS APPLY JSON_TABLE({_FIELDS_AS_ARRAY}, '$[*]' COLUMNS (field_no FOR ORDINALITY, "
    "field_code VARCHAR2(64) PATH '$.field', old_value VARCHAR2(4000) PATH '$.old', new_value VARCHAR2(4000) PATH '$.new')) f "
    "LEFT JOIN pf_user u ON TO_CHAR(u.user_id) = c.user_id "
    "LEFT JOIN pf_config_item e ON e.config_type = 'entity' AND e.config_key = r.entity "
    "LEFT JOIN (SELECT ci.config_key AS entity, jt.name, jt.label FROM pf_config_item ci, "
    "JSON_TABLE(ci.content, '$.fields[*]' COLUMNS (name VARCHAR2(64) PATH '$.name', label VARCHAR2(200) PATH '$.label')) jt "
    "WHERE ci.config_type = 'entity') l ON l.entity = r.entity AND l.name = f.field_code "
    "WHERE c.status = 'done' AND c.audit_diff IS NOT NULL"
)
"""视图的查询（真实验证 `tests/pipeline/test_oracle_audit_log_view.py` 直接执行它）。"""


def upgrade() -> None:
    op.execute(f"CREATE OR REPLACE VIEW {VIEW} AS {SELECT}")


def downgrade() -> None:
    op.execute(f"DROP VIEW {VIEW}")
