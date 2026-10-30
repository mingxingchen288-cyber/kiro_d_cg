//! C07 第 2、3 节：解析求值请求，按阶段选规则、组装输入（RC-08）、调用 zen-engine、解释结果。
//! 数值处理按模块说明第 8 节：空值按 0，除以 0、溢出、空数组的汇总为 0，求值出错为 0 并给出提示，条件求值出错按成立，
//! 分支都不匹配保持原值，不舍入。计算规则全部执行完后，再用最终值执行校验和界面规则（C06 第 5 节执行顺序 3）。

use crate::decimal;
use crate::pack::{Branches, CalcRule, CheckKind, CheckRule, FieldType, Layer, Pack, UiEffect};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};
use zen_expression::variable::{Variable, VariableMap};
use zen_expression::Isolate;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Request {
    /// C07 第 2 节：固定为 `operation`，只用来校验请求。
    #[allow(dead_code)]
    purpose: Purpose,
    #[serde(default)]
    operation: Option<String>,
    #[serde(default)]
    page: Option<String>,
    phase: Phase,
    context: Context,
    document: Document,
    changed: Vec<Changed>,
    data: Map<String, Value>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
enum Purpose {
    Operation,
}

#[derive(Deserialize, PartialEq, Eq, Clone, Copy)]
#[serde(rename_all = "camelCase")]
enum Phase {
    Preview,
    Commit,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Context {
    user_id: String,
    department_id: Option<String>,
    role: String,
    today: String,
    origin: Origin,
}

#[derive(Deserialize, Clone, Copy)]
#[serde(rename_all = "camelCase")]
enum Origin {
    User,
    Approval,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Document {
    entity: String,
    master: RowJson,
    details: Map<String, Value>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RowJson {
    #[serde(default)]
    row_key: Option<String>,
    #[serde(default)]
    client_row_id: Option<String>,
    values: Map<String, Value>,
    #[serde(default)]
    old: Option<Map<String, Value>>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Changed {
    entity: String,
    #[serde(default)]
    row_key: Option<String>,
    #[serde(default)]
    client_row_id: Option<String>,
    op: RowOp,
    #[allow(dead_code)]
    fields: Vec<String>,
}

#[derive(Deserialize, PartialEq, Eq, Clone, Copy)]
#[serde(rename_all = "camelCase")]
enum RowOp {
    Modify,
    Add,
    Delete,
}

/// 业务字段的值：数值字段为 Decimal，其他按 JSON 类型。
#[derive(Clone, Debug)]
enum Val {
    Null,
    Num(Decimal),
    Str(String),
    Bool(bool),
}

impl Val {
    fn to_variable(&self) -> Variable {
        match self {
            Val::Null => Variable::Null,
            Val::Num(d) => Variable::Number(*d),
            Val::Str(s) => Variable::String(s.as_str().into()),
            Val::Bool(b) => Variable::Bool(*b),
        }
    }

    fn to_json(&self) -> Value {
        match self {
            Val::Null => Value::Null,
            Val::Num(d) => Value::String(decimal::format(*d)),
            Val::Str(s) => Value::String(s.clone()),
            Val::Bool(b) => Value::Bool(*b),
        }
    }
}

#[derive(Clone, PartialEq, Eq, Hash)]
enum RowId {
    Key(String),
    Client(String),
}

struct Row {
    entity: String,
    id: RowId,
    values: HashMap<String, Val>,
    /// 本命令开始前的值：请求中的 `old` 覆盖当前值；新增行为空（C07 第 2 节）。
    old: HashMap<String, Val>,
    /// 按计算顺序记下的计算字段的最终值。
    computed: Vec<(String, Val)>,
    /// 界面规则给出的字段状态：字段 → {"editable": …, "required": …}（C07 第 3 节 `fields`）。
    fields: Map<String, Value>,
    /// 界面规则给出的行样式和单元格样式（C07 第 3 节 `style`）。
    row_style: Option<Map<String, Value>>,
    cells: Map<String, Value>,
}

type Types = HashMap<String, FieldType>;

pub struct Failure {
    pub code: &'static str,
    pub message: String,
}

fn input_invalid(message: impl Into<String>) -> Failure {
    Failure { code: "INPUT_INVALID", message: message.into() }
}

pub fn evaluate(pack: &Pack, request_text: &str) -> Result<Value, Failure> {
    let request: Request =
        serde_json::from_str(request_text).map_err(|e| input_invalid(format!("求值请求不符合 C07 第 2 节：{e}")))?;
    let no_types = Types::new();
    let types_of = |entity: &str| pack.fields.get(entity).unwrap_or(&no_types);

    let deleted: HashSet<(String, RowId)> = request
        .changed
        .iter()
        .filter(|c| c.op == RowOp::Delete)
        .filter_map(|c| row_id(c.row_key.clone(), c.client_row_id.clone()).ok().map(|id| (c.entity.clone(), id)))
        .collect();

    let master_entity = request.document.entity.clone();
    let mut master = parse_row(&master_entity, request.document.master, types_of(&master_entity))?;
    let mut details: Vec<(String, Vec<Row>)> = Vec::new();
    for (entity, rows) in request.document.details {
        let rows: Vec<RowJson> = serde_json::from_value(rows)
            .map_err(|e| input_invalid(format!("document.details.{entity} 不符合 C07 第 2 节：{e}")))?;
        let mut parsed = Vec::with_capacity(rows.len());
        for row in rows {
            let row = parse_row(&entity, row, types_of(&entity))?;
            if !deleted.contains(&(entity.clone(), row.id.clone())) {
                parsed.push(row);
            }
        }
        details.push((entity, parsed));
    }

    let env = Env {
        pack,
        empty: Types::new(),
        context: context_variable(&request.context),
        data: data_variable(&Value::Object(request.data)),
    };
    let mut effects: Vec<Value> = Vec::new();
    let (phase, operation, page) = (request.phase, request.operation, request.page);
    let picked = |layer: Layer, rule_operation: &Option<String>, rule_page: &Option<String>, server_only: bool| {
        selected(layer, rule_operation, rule_page, server_only, phase, &operation, &page)
    };

    for rule in pack.calc.iter().filter(|r| picked(r.layer, &r.operation, &r.page, r.server_only)) {
        if rule.is_master {
            let scope = env.master_scope(&master, &details, &rule.plain_refs);
            let ty = env.types(&master_entity).get(&rule.field).copied();
            apply(rule, &mut master, scope, ty, &mut effects);
        } else {
            let master_var = env.row_variable(&master);
            let ty = env.types(&rule.entity).get(&rule.field).copied();
            if let Some((_, rows)) = details.iter_mut().find(|(e, _)| *e == rule.entity) {
                for row in rows.iter_mut() {
                    let scope = env.detail_scope(row, &master_var, &rule.plain_refs);
                    apply(rule, row, scope, ty, &mut effects);
                }
            }
        }
    }

    // 校验和界面规则用计算后的最终值（C06 第 5 节执行顺序 3）
    for rule in pack.checks.iter().filter(|r| picked(r.layer, &r.operation, &r.page, r.server_only)) {
        if rule.is_master {
            let scope = env.master_scope(&master, &details, &rule.plain_refs);
            check(rule, &mut master, scope, env.types(&master_entity), &mut effects);
        } else {
            let master_var = env.row_variable(&master);
            let types = env.types(&rule.entity);
            if let Some((_, rows)) = details.iter_mut().find(|(e, _)| *e == rule.entity) {
                for row in rows.iter_mut() {
                    let scope = env.detail_scope(row, &master_var, &rule.plain_refs);
                    check(rule, row, scope, types, &mut effects);
                }
            }
        }
    }

    let mut rows_out = vec![row_result(&master)];
    for (_, rows) in &details {
        rows_out.extend(rows.iter().map(row_result));
    }
    Ok(json!({"ok": true, "rows": rows_out, "effects": effects}))
}

/// 一次求值的公共输入：规则包、`context`、`data`。
struct Env<'a> {
    pack: &'a Pack,
    empty: Types,
    context: Variable,
    data: Variable,
}

impl Env<'_> {
    fn types(&self, entity: &str) -> &Types {
        self.pack.fields.get(entity).unwrap_or(&self.empty)
    }

    /// 主表行作为明细规则的 `master`。
    fn row_variable(&self, row: &Row) -> Variable {
        Variable::from_object(row_object(row, self.types(&row.entity), &[]))
    }

    /// 主表规则的输入（RC-08）：主表字段直接写，明细实体编码为这个明细的行的数组。
    fn master_scope(&self, master: &Row, details: &[(String, Vec<Row>)], refs: &[String]) -> VariableMap {
        let mut scope = row_object(master, self.types(&master.entity), &[]);
        for (entity, rows) in details {
            let types = self.types(entity);
            let items = rows.iter().map(|r| Variable::from_object(row_object(r, types, &[]))).collect();
            scope.insert_str(entity, Variable::from_array(items));
        }
        for entity in self.pack.fields.keys().filter(|e| **e != master.entity) {
            if !scope.contains_key_str(entity) {
                scope.insert_str(entity, Variable::empty_array());
            }
        }
        fill_refs(&mut scope, refs);
        scope.insert_str("old", old_variable(master));
        scope.insert_str("context", self.context.clone());
        scope.insert_str("data", self.data.clone());
        scope
    }

    /// 明细规则的输入（RC-08）：本行字段直接写，主表字段为 `master.字段`。
    fn detail_scope(&self, row: &Row, master_var: &Variable, refs: &[String]) -> VariableMap {
        let mut scope = row_object(row, self.types(&row.entity), refs);
        scope.insert_str("master", master_var.clone());
        scope.insert_str("old", old_variable(row));
        scope.insert_str("context", self.context.clone());
        scope.insert_str("data", self.data.clone());
        scope
    }
}

/// preview 执行实体、操作、页面三层规则；commit 只执行实体和操作规则（C07 第 2 节）。
/// 依赖数据库数据的规则（serverOnly）在前端预览时不出结论。
fn selected(
    layer: Layer,
    rule_operation: &Option<String>,
    rule_page: &Option<String>,
    server_only: bool,
    phase: Phase,
    operation: &Option<String>,
    page: &Option<String>,
) -> bool {
    let layer_ok = match layer {
        Layer::Entity => true,
        Layer::Operation => rule_operation.is_some() && rule_operation == operation,
        Layer::Page => phase == Phase::Preview && rule_page.is_some() && rule_page == page,
    };
    layer_ok && !(phase == Phase::Preview && server_only)
}

fn row_id(row_key: Option<String>, client_row_id: Option<String>) -> Result<RowId, Failure> {
    match (row_key, client_row_id) {
        (Some(k), None) => Ok(RowId::Key(k)),
        (None, Some(c)) => Ok(RowId::Client(c)),
        _ => Err(input_invalid("行的 rowKey 和 clientRowId 必须有且只有一个（C07 第 2 节）")),
    }
}

fn parse_row(entity: &str, row: RowJson, types: &Types) -> Result<Row, Failure> {
    let id = row_id(row.row_key, row.client_row_id)?;
    let is_new = matches!(id, RowId::Client(_));
    let values = parse_values(entity, &row.values, types)?;
    let old = if is_new {
        HashMap::new()
    } else {
        let mut old = values.clone();
        if let Some(given) = &row.old {
            old.extend(parse_values(entity, given, types)?);
        }
        old
    };
    Ok(Row {
        entity: entity.to_string(),
        id,
        values,
        old,
        computed: Vec::new(),
        fields: Map::new(),
        row_style: None,
        cells: Map::new(),
    })
}

fn parse_values(entity: &str, values: &Map<String, Value>, types: &Types) -> Result<HashMap<String, Val>, Failure> {
    let mut out = HashMap::with_capacity(values.len());
    for (name, value) in values {
        let val = match value {
            Value::Null => Val::Null,
            Value::Bool(b) => Val::Bool(*b),
            Value::String(s) if types.get(name) == Some(&FieldType::Number) => {
                Val::Num(decimal::parse(s).map_err(|e| input_invalid(format!("{entity}.{name}：{e}")))?)
            }
            Value::String(s) => Val::Str(s.clone()),
            _ => return Err(input_invalid(format!("{entity}.{name} 的值必须是文本、布尔或 null（C01）"))),
        };
        out.insert(name.clone(), val);
    }
    Ok(out)
}

/// 一行的表达式输入：本行字段；数值字段为空或缺失时按 0（模块说明第 8 节）。
fn row_object(row: &Row, types: &Types, refs: &[String]) -> VariableMap {
    let mut map = VariableMap::with_capacity(row.values.len() + types.len() + 4);
    for (name, val) in &row.values {
        map.insert_str(name, val.to_variable());
    }
    for (name, ty) in types {
        if *ty == FieldType::Number && matches!(row.values.get(name), None | Some(Val::Null)) {
            map.insert_str(name, Variable::Number(Decimal::ZERO));
        }
    }
    fill_refs(&mut map, refs);
    map
}

/// 表达式引用了、行中没有的字段按 0（旧系统 ensureFieldRefInScope）。
fn fill_refs(map: &mut VariableMap, refs: &[String]) {
    for name in refs {
        if !map.contains_key_str(name) {
            map.insert_str(name, Variable::Number(Decimal::ZERO));
        }
    }
}

fn old_variable(row: &Row) -> Variable {
    let mut map = VariableMap::with_capacity(row.old.len());
    for (name, val) in &row.old {
        map.insert_str(name, val.to_variable());
    }
    Variable::from_object(map)
}

fn context_variable(c: &Context) -> Variable {
    let origin = match c.origin {
        Origin::User => "user",
        Origin::Approval => "approval",
    };
    // 都是文本，不含 JSON 数字
    Variable::from(json!({
        "userId": c.user_id, "departmentId": c.department_id, "role": c.role, "today": c.today, "origin": origin
    }))
}

/// `data` 转成表达式输入：十进制文本按数值参与计算（C01：精确数值在 JSON 中都是字符串），
/// 直接解析为 Decimal，不经过 serde_json 的数字（那会转成 f64，RC-02）。
fn data_variable(value: &Value) -> Variable {
    match value {
        Value::String(s) => match decimal::parse(s) {
            Ok(d) => Variable::Number(d),
            Err(_) => Variable::String(s.as_str().into()),
        },
        Value::Array(a) => Variable::from_array(a.iter().map(data_variable).collect()),
        Value::Object(o) => {
            let mut map = VariableMap::with_capacity(o.len());
            for (k, v) in o {
                map.insert_str(k, data_variable(v));
            }
            Variable::from_object(map)
        }
        Value::Null => Variable::Null,
        Value::Bool(b) => Variable::Bool(*b),
        Value::Number(_) => Variable::Null,
    }
}

/// 求值一条计算规则，把结果写回行（下游规则按全部精度使用，C06 第 5 节执行顺序 5）。
fn apply(rule: &CalcRule, row: &mut Row, scope: VariableMap, ty: Option<FieldType>, effects: &mut Vec<Value>) {
    let input = Variable::from_object(scope);
    let probe = input.clone();
    let number = ty == Some(FieldType::Number);
    let outcome = match pollster::block_on(rule.decision.evaluate(input)) {
        // 表达式节点不写出 null 的 key
        Ok(response) => interpret(Ok(response.result.dot(&rule.field).unwrap_or(Variable::Null)), &rule.divisors, &probe, number),
        // 有分支时逐段求值：条件出错按成立（模块说明第 8 节），再按选中的那一段判断除以 0
        Err(_) if rule.branches.is_some() => {
            let (result, divisors) = branch_value(rule.branches.as_ref().expect("有分支"), &probe);
            interpret(result, divisors, &probe, number)
        }
        Err(error) => interpret(Err(error_text(error.as_ref())), &rule.divisors, &probe, number),
    };
    let value = match outcome {
        Ok(v) => v,
        Err(reason) => {
            let message = format!("计算规则 {} 求值出错，{} 按 0 处理：{reason}", rule.id, rule.field);
            effects.push(effect("prompt", &rule.id, message, row, Some(&rule.field)));
            Val::Num(Decimal::ZERO)
        }
    };
    row.values.insert(rule.field.clone(), value.clone());
    match row.computed.iter_mut().find(|(f, _)| *f == rule.field) {
        Some(slot) => slot.1 = value,
        None => row.computed.push((rule.field.clone(), value)),
    }
}

fn error_text(error: &zen_engine::EvaluationError) -> String {
    let mut parts = vec![error.to_string()];
    let mut source = std::error::Error::source(error);
    while let Some(s) = source {
        parts.push(s.to_string());
        source = s.source();
    }
    parts.dedup();
    parts.join("：")
}

/// 按模块说明第 8 节解释一条计算表达式的结果：
/// 结果为 null（除以 0 的直接结果，zen-expression 的 checked_div）时数值字段为 0；
/// 溢出、空数组的 avg/max/min、除以 0 之后的运算出错（某个除数在同一输入下为 0，含 0/0）都为 0，不算出错；
/// 其余错误返回原因，由调用方按 0 处理并给出提示。
fn interpret(result: Result<Variable, String>, divisors: &[String], scope: &Variable, number: bool) -> Result<Val, String> {
    match result {
        Ok(Variable::Number(d)) => Ok(Val::Num(d)),
        Ok(Variable::Null) => Ok(if number { Val::Num(Decimal::ZERO) } else { Val::Null }),
        Ok(Variable::String(s)) if !number => Ok(Val::Str(s.to_string())),
        Ok(Variable::Bool(b)) if !number => Ok(Val::Bool(b)),
        Ok(other) => Err(format!("结果为 {}，不是数值", other.type_name())),
        Err(text) if text.contains("Number overflow") || text.contains("Empty array") || divides_by_zero(divisors, scope) => {
            Ok(Val::Num(Decimal::ZERO))
        }
        Err(text) => Err(text),
    }
}

/// 逐个分支求值：条件为 true 时取这个分支；条件求值出错按成立（旧系统 evalCondition 的 catch 返回 true）；
/// 条件为 false 或 null 时看下一个；都不成立时取最后一段（字段自己）。返回选中那一段的结果和它的除数。
fn branch_value<'a>(branches: &'a Branches, scope: &Variable) -> (Result<Variable, String>, &'a [String]) {
    let part = branches
        .arms
        .iter()
        .find(|(condition, _)| holds(condition.evaluate(scope.clone())))
        .map(|(_, part)| part)
        .unwrap_or(&branches.otherwise);
    (part.expression.evaluate(scope.clone()).map_err(|e| e.to_string()), &part.divisors)
}

/// 条件是否成立：true 成立，false 和 null 不成立；求值出错或结果不是布尔时按成立（模块说明第 8 节）。
fn holds(result: Result<Variable, zen_expression::IsolateError>) -> bool {
    match result {
        Ok(Variable::Bool(b)) => b,
        Ok(Variable::Null) => false,
        _ => true,
    }
}

/// 求值出错时，表达式里有除数在同一输入下为 0，就是除以 0（含 0/0）：按 0，不算出错。
fn divides_by_zero(divisors: &[String], scope: &Variable) -> bool {
    divisors.iter().any(|d| {
        let mut isolate = Isolate::with_environment(scope.clone());
        matches!(isolate.run_standard(d), Ok(Variable::Number(n)) if n.is_zero())
    })
}

/// C07 第 3 节的效果：定位到实体、行（rowKey 或 clientRowId）和字段；规则没有作用字段时不写 field。
fn effect(kind: &str, rule: &str, message: String, row: &Row, field: Option<&str>) -> Value {
    let mut out = Map::new();
    out.insert("kind".into(), kind.into());
    out.insert("rule".into(), rule.into());
    out.insert("message".into(), message.into());
    out.insert("entity".into(), row.entity.clone().into());
    match &row.id {
        RowId::Key(k) => out.insert("rowKey".into(), k.clone().into()),
        RowId::Client(c) => out.insert("clientRowId".into(), c.clone().into()),
    };
    if let Some(f) = field {
        out.insert("field".into(), f.into());
    }
    Value::Object(out)
}

/// 执行一条校验或界面规则：`when` 成立时，校验给出 reject 或 prompt；界面规则把效果记到这一行。
fn check(rule: &CheckRule, row: &mut Row, scope: VariableMap, types: &Types, effects: &mut Vec<Value>) {
    if !holds(rule.condition.evaluate(Variable::from_object(scope))) {
        return;
    }
    match &rule.kind {
        CheckKind::Validate { level, message } => {
            effects.push(effect(level.kind(), &rule.id, message.clone(), row, rule.field.as_deref()));
        }
        CheckKind::Ui(ui) => apply_ui(ui, rule.field.as_deref(), row, types),
    }
}

/// 界面规则的效果（C06 第 5 节）：`editable`、`required` 记到 `fields`，`rowStyle` 记到 `style.row`，`cellStyle` 记到
/// `style.cells`。`field` 为空时作用于整行：字段状态和单元格样式给到这一实体的每个字段（按字段名排序，结果与运行无关）。
/// 多条规则命中同一处时按执行顺序合并，后面的覆盖前面的同名属性（旧系统 GRID_STYLE 合并样式的做法）。
fn apply_ui(ui: &UiEffect, field: Option<&str>, row: &mut Row, types: &Types) {
    let targets: Vec<String> = match field {
        Some(f) => vec![f.to_string()],
        None => {
            let mut all: Vec<String> = types.keys().cloned().collect();
            all.sort();
            all
        }
    };
    for name in &targets {
        if ui.editable.is_some() || ui.required.is_some() {
            let state = row.fields.entry(name.clone()).or_insert_with(|| Value::Object(Map::new()));
            if let Value::Object(state) = state {
                if let Some(b) = ui.editable {
                    state.insert("editable".into(), b.into());
                }
                if let Some(b) = ui.required {
                    state.insert("required".into(), b.into());
                }
            }
        }
        if let Some(style) = &ui.cell_style {
            let cell = row.cells.entry(name.clone()).or_insert_with(|| Value::Object(Map::new()));
            if let Value::Object(cell) = cell {
                cell.extend(style.clone());
            }
        }
    }
    if let Some(style) = &ui.row_style {
        row.row_style.get_or_insert_with(Map::new).extend(style.clone());
    }
}

fn row_result(row: &Row) -> Value {
    let mut out = Map::new();
    out.insert("entity".into(), row.entity.clone().into());
    match &row.id {
        RowId::Key(k) => out.insert("rowKey".into(), k.clone().into()),
        RowId::Client(c) => out.insert("clientRowId".into(), c.clone().into()),
    };
    let computed: Map<String, Value> = row.computed.iter().map(|(f, v)| (f.clone(), v.to_json())).collect();
    out.insert("computed".into(), Value::Object(computed));
    out.insert("fields".into(), Value::Object(row.fields.clone()));
    let style_row = row.row_style.clone().map(Value::Object).unwrap_or(Value::Null);
    out.insert("style".into(), json!({"row": style_row, "cells": Value::Object(row.cells.clone())}));
    Value::Object(out)
}
