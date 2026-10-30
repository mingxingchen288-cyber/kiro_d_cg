//! C07 第 1 节：规则包的解析、JDM 检查和编译、计算规则的依赖排序（RC-03、RC-09），校验和界面规则的条件与效果。

use crate::scan::{conditional, scan, strip_parens};
use serde::Deserialize;
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use zen_engine::model::GraphContent;
use zen_engine::Decision;
use zen_expression::expression::Standard;
use zen_expression::{compile_expression, Expression, Variable};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PackJson {
    pack_id: String,
    #[allow(dead_code)]
    version: i64,
    #[allow(dead_code)]
    core_version: String,
    fields: BTreeMap<String, BTreeMap<String, PackFieldJson>>,
    rules: Vec<PackRuleJson>,
    jdm: BTreeMap<String, Value>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PackFieldJson {
    #[serde(rename = "type")]
    field_type: FieldType,
    #[serde(default)]
    #[allow(dead_code)]
    scale: Option<i64>,
    #[allow(dead_code)]
    role: FieldRole,
    #[allow(dead_code)]
    source: FieldSource,
}

#[derive(Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "camelCase")]
pub enum FieldType {
    Text,
    Number,
    Date,
    Datetime,
    Boolean,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
enum FieldRole {
    Input,
    Calculated,
    System,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
enum FieldSource {
    Erp,
    Own,
}

#[derive(Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "camelCase")]
pub enum Layer {
    Entity,
    Operation,
    Page,
}

#[derive(Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "camelCase")]
enum Category {
    Calc,
    Validate,
    Ui,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PackRuleJson {
    id: String,
    layer: Layer,
    #[serde(default)]
    entity: Option<String>,
    #[serde(default)]
    operation: Option<String>,
    #[serde(default)]
    page: Option<String>,
    category: Category,
    order: i64,
    server_only: bool,
    jdm: String,
}

/// 一条计算规则：作用在 `entity` 的 `field` 上，表达式为 `expression`（JDM 表达式节点中唯一的一个表达式）。
pub struct CalcRule {
    pub id: String,
    pub layer: Layer,
    pub operation: Option<String>,
    pub page: Option<String>,
    pub entity: String,
    pub is_master: bool,
    pub field: String,
    pub server_only: bool,
    /// 表达式引用、但行中可能没有的字段名（按 0 补上，模块说明第 8 节）。
    pub plain_refs: Vec<String>,
    /// `/`、`%` 右边的操作数：求值出错时据此判断是不是除以 0（模块说明第 8 节）。
    pub divisors: Vec<String>,
    pub decision: Decision,
    /// 表达式拆成的各段：`when`、`branches` 编成的条件表达式按分支拆开，其他表达式只有最后一段。
    /// zen-engine 求值出错时给出的错误不带原因（表达式节点只写"Failed to evaluate expression"），这时逐段直接求值：
    /// 得到原因，判断溢出和除以 0，条件出错按成立处理（模块说明第 8 节）。
    pub branches: Option<Branches>,
}

/// 表达式的一段：编译好的表达式和它的除数。
pub struct Part {
    pub expression: Expression<Standard>,
    pub divisors: Vec<String>,
}

/// `(w1) ? (e1) : ((w2) ? (e2) : 字段)` 拆成 `[(w1, e1), (w2, e2)]` 和最后的 `字段`；不是条件写法时 arms 为空。
pub struct Branches {
    pub arms: Vec<(Expression<Standard>, Part)>,
    pub otherwise: Part,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Level {
    Reject,
    Prompt,
}

impl Level {
    pub fn kind(self) -> &'static str {
        match self {
            Level::Reject => "reject",
            Level::Prompt => "prompt",
        }
    }
}

/// 界面规则的效果（C06 第 5 节 `effect`）。
pub struct UiEffect {
    pub editable: Option<bool>,
    pub required: Option<bool>,
    pub row_style: Option<Map<String, Value>>,
    pub cell_style: Option<Map<String, Value>>,
}

pub enum CheckKind {
    Validate { level: Level, message: String },
    Ui(UiEffect),
}

/// 一条校验或界面规则：计算规则全部执行完后执行，用计算后的最终值（C06 第 5 节执行顺序 3）。
/// `condition` 为 JDM 中的 `matched`，`field` 为空时界面规则作用于整行、校验结果只定位到行。
pub struct CheckRule {
    pub id: String,
    pub layer: Layer,
    pub operation: Option<String>,
    pub page: Option<String>,
    pub entity: String,
    pub is_master: bool,
    pub field: Option<String>,
    pub server_only: bool,
    pub plain_refs: Vec<String>,
    /// 主表规则的条件引用的明细实体（值是行的数组）。显示求值时请求没有给出这些明细的，这条规则不出结论（C07 第 3.1 节）。
    pub detail_refs: Vec<String>,
    pub condition: Expression<Standard>,
    pub kind: CheckKind,
}

/// load_pack 的结果：编译好的规则（RC-03），计算规则已按依赖排好序（RC-09），校验和界面规则按 order、规则编码排序。
pub struct Pack {
    pub master: String,
    pub fields: HashMap<String, HashMap<String, FieldType>>,
    pub calc: Vec<CalcRule>,
    pub checks: Vec<CheckRule>,
}

const ALLOWED_NODES: [&str; 5] = ["inputNode", "outputNode", "expressionNode", "decisionTableNode", "switchNode"];

pub fn load(bytes: &[u8]) -> Result<Pack, String> {
    let pack: PackJson = serde_json::from_slice(bytes).map_err(|e| format!("规则包不符合 C07 第 1 节：{e}"))?;
    let master = pack.pack_id.clone();
    let fields: HashMap<String, HashMap<String, FieldType>> = pack
        .fields
        .iter()
        .map(|(entity, fs)| (entity.clone(), fs.iter().map(|(n, f)| (n.clone(), f.field_type)).collect()))
        .collect();

    let mut graphs: HashMap<String, GraphContent> = HashMap::new();
    for (key, value) in &pack.jdm {
        graphs.insert(key.clone(), parse_graph(key, value)?);
    }
    for rule in &pack.rules {
        if !graphs.contains_key(&rule.jdm) {
            return Err(format!("{} 引用的 JDM \"{}\" 不在规则包的 jdm 中", rule.id, rule.jdm));
        }
    }

    let mut calc = Vec::new();
    let mut orders = Vec::new();
    let mut checks = Vec::new();
    for rule in &pack.rules {
        let graph = graphs[&rule.jdm].clone();
        let entity = rule.entity.clone().unwrap_or_else(|| master.clone());
        let is_master = entity == master;
        if rule.category != Category::Calc {
            let details: BTreeSet<&str> = if is_master {
                fields.keys().map(String::as_str).filter(|e| *e != master).collect()
            } else {
                BTreeSet::new()
            };
            checks.push((rule.order, rule.id.clone(), check_rule(rule, &graph, entity, is_master, &details)?));
            continue;
        }
        let (field, expression) = single_expression(&rule.id, &graph)?;
        let s = scan(&expression);
        let mut decision = Decision::from(graph);
        decision.compile();
        orders.push((rule.order, rule.id.clone(), s.chains.clone()));
        calc.push(CalcRule {
            id: rule.id.clone(),
            layer: rule.layer,
            operation: rule.operation.clone(),
            page: rule.page.clone(),
            entity,
            is_master,
            field,
            server_only: rule.server_only,
            plain_refs: plain_refs(&s.chains),
            divisors: s.divisors,
            decision,
            branches: branches(&expression),
        });
    }
    let order = sort(&calc, &orders, &fields, &master)?;
    let mut slots: Vec<Option<CalcRule>> = calc.into_iter().map(Some).collect();
    let calc = order.into_iter().map(|i| slots[i].take().expect("每条规则只排一次")).collect();
    // 校验、界面规则之间没有依赖（它们不改字段的值）：按 order、规则编码执行（C06 第 5 节执行顺序 2、3）
    checks.sort_by(|a, b| (a.0, &a.1).cmp(&(b.0, &b.1)));
    let checks = checks.into_iter().map(|(_, _, c)| c).collect();
    Ok(Pack { master, fields, calc, checks })
}

/// 表达式引用、但行中可能没有的字段名（`#`、`$` 开头的不算）。
fn plain_refs(chains: &[Vec<String>]) -> Vec<String> {
    chains.iter().filter(|c| c.len() == 1 && !c[0].starts_with(['#', '$'])).map(|c| c[0].clone()).collect()
}

/// config 编出的条件表达式拆成各个分支（README 第 2 节）；不是条件写法、或某段不能单独编译时，整条表达式作为最后一段。
/// 整条表达式也不能编译时为 None。
fn branches(expression: &str) -> Option<Branches> {
    let part = |text: &str| -> Option<Part> {
        Some(Part { expression: compile_expression(text).ok()?, divisors: scan(text).divisors })
    };
    let whole = || part(expression).map(|otherwise| Branches { arms: Vec::new(), otherwise });
    let mut arms = Vec::new();
    let mut rest = expression.to_string();
    while let Some((cond, then, other)) = conditional(strip_parens(&rest)) {
        let (Ok(condition), Some(then)) = (compile_expression(&cond), part(&then)) else { return whole() };
        arms.push((condition, then));
        rest = other;
    }
    match part(strip_parens(&rest)) {
        Some(otherwise) => Some(Branches { arms, otherwise }),
        None => whole(),
    }
}

/// 校验、界面规则的 JDM（config `packs.py` 生成）：表达式节点依次为 `matched`（条件，空为 `true`）、`field`（作用的字段，
/// 整行时没有）；校验另有 `level`、`message`，界面另有 `editable`、`required`、`rowStyle`、`cellStyle`（样式 JSON 文本）。
/// 除 `matched` 外都是常量，在 load_pack 时求出；`matched` 编译一次，求值时对每行执行。
/// `details`：主表规则可以引用的明细实体编码（明细规则为空）。
fn check_rule(
    rule: &PackRuleJson,
    graph: &GraphContent,
    entity: String,
    is_master: bool,
    details: &BTreeSet<&str>,
) -> Result<CheckRule, String> {
    let items: HashMap<String, String> = expressions(graph).into_iter().collect();
    let matched = items.get("matched").map(String::as_str).unwrap_or("true");
    let condition = compile_expression(matched).map_err(|e| format!("规则 {} 的条件 \"{matched}\" 不能编译：{e}", rule.id))?;
    let constant = |key: &str| -> Result<Option<Variable>, String> {
        let Some(text) = items.get(key) else { return Ok(None) };
        let value = compile_expression(text)
            .and_then(|e| e.evaluate(Variable::empty_object()))
            .map_err(|e| format!("规则 {} 的 {key} \"{text}\" 不是常量：{e}", rule.id))?;
        Ok(Some(value))
    };
    let text = |key: &str| -> Result<Option<String>, String> {
        match constant(key)? {
            None | Some(Variable::Null) => Ok(None),
            Some(Variable::String(s)) => Ok(Some(s.to_string())),
            Some(other) => Err(format!("规则 {} 的 {key} 应当是文本，实际为 {}", rule.id, other.type_name())),
        }
    };
    let flag = |key: &str| -> Result<Option<bool>, String> {
        match constant(key)? {
            None | Some(Variable::Null) => Ok(None),
            Some(Variable::Bool(b)) => Ok(Some(b)),
            Some(other) => Err(format!("规则 {} 的 {key} 应当是 true 或 false，实际为 {}", rule.id, other.type_name())),
        }
    };
    let style = |key: &str| -> Result<Option<Map<String, Value>>, String> {
        let Some(json) = text(key)? else { return Ok(None) };
        match serde_json::from_str::<Value>(&json) {
            Ok(Value::Object(map)) => Ok(Some(map)),
            _ => Err(format!("规则 {} 的 {key} 应当是样式对象的 JSON 文本：{json}", rule.id)),
        }
    };
    let kind = if rule.category == Category::Validate {
        // 没写 level 时为 reject，同 config（C06 第 5 节）
        let level = match text("level")?.as_deref() {
            None | Some("reject") => Level::Reject,
            Some("prompt") => Level::Prompt,
            Some(other) => return Err(format!("规则 {} 的 level 应当是 reject 或 prompt，实际为 {other}", rule.id)),
        };
        CheckKind::Validate { level, message: text("message")?.unwrap_or_default() }
    } else {
        CheckKind::Ui(UiEffect {
            editable: flag("editable")?,
            required: flag("required")?,
            row_style: style("rowStyle")?,
            cell_style: style("cellStyle")?,
        })
    };
    let chains = scan(matched).chains;
    let detail_refs: BTreeSet<String> =
        chains.iter().filter_map(|c| c.first()).filter(|f| details.contains(f.as_str())).cloned().collect();
    Ok(CheckRule {
        id: rule.id.clone(),
        layer: rule.layer,
        operation: rule.operation.clone(),
        page: rule.page.clone(),
        entity,
        is_master,
        field: text("field")?,
        server_only: rule.server_only,
        plain_refs: plain_refs(&chains),
        detail_refs: detail_refs.into_iter().collect(),
        condition,
        kind,
    })
}

fn parse_graph(key: &str, value: &Value) -> Result<GraphContent, String> {
    if let Some(nodes) = value.get("nodes").and_then(Value::as_array) {
        for node in nodes {
            let kind = node.get("type").and_then(Value::as_str).unwrap_or("");
            if !ALLOWED_NODES.contains(&kind) {
                return Err(format!("JDM \"{key}\" 含不允许的节点 \"{kind}\"：只允许输入、输出、表达式、决策表、Switch 五种节点"));
            }
        }
    }
    serde_json::from_value(value.clone()).map_err(|e| format!("JDM \"{key}\" 不合法：{e}"))
}

/// JDM 中全部表达式节点的表达式（key、value），按出现顺序。
fn expressions(graph: &GraphContent) -> Vec<(String, String)> {
    let mut found = Vec::new();
    for node in &graph.nodes {
        if let zen_engine::model::DecisionNodeKind::ExpressionNode { content } = &node.kind {
            for e in content.expressions.iter() {
                found.push((e.key.to_string(), e.value.to_string()));
            }
        }
    }
    found
}

/// 计算规则的 JDM 约定：只有一个表达式节点、一个表达式，key 为作用的字段。
fn single_expression(rule: &str, graph: &GraphContent) -> Result<(String, String), String> {
    let mut found = expressions(graph);
    match found.len() {
        1 => Ok(found.remove(0)),
        n => Err(format!("计算规则 {rule} 的 JDM 应当只有一个表达式（key 为作用的字段），实际有 {n} 个")),
    }
}

/// 按依赖排序（C06 第 5 节执行顺序 1、2、4）：被引用的先执行；没有依赖时按 order、规则编码；成环时报错并列出环上的规则。
fn sort(
    calc: &[CalcRule],
    orders: &[(i64, String, Vec<Vec<String>>)],
    fields: &HashMap<String, HashMap<String, FieldType>>,
    master: &str,
) -> Result<Vec<usize>, String> {
    let producer: HashMap<(&str, &str), Vec<usize>> = calc.iter().enumerate().fold(HashMap::new(), |mut m, (i, r)| {
        m.entry((r.entity.as_str(), r.field.as_str())).or_default().push(i);
        m
    });
    let details: HashSet<&str> = fields.keys().map(String::as_str).filter(|e| *e != master).collect();
    // deps[i]：规则 i 依赖的规则
    let mut deps: Vec<BTreeSet<usize>> = vec![BTreeSet::new(); calc.len()];
    for (i, rule) in calc.iter().enumerate() {
        let chains = &orders[i].2;
        let mut refs: Vec<(String, String)> = Vec::new();
        let members: Vec<&str> = chains.iter().filter(|c| c[0] == "#" && c.len() > 1).map(|c| c[1].as_str()).collect();
        for c in chains {
            let first = c[0].as_str();
            match first {
                "old" | "context" | "data" | "$" | "$root" | "#" => {}
                "master" if c.len() > 1 => refs.push((master.to_string(), c[1].clone())),
                d if rule.is_master && details.contains(d) => {
                    for m in &members {
                        refs.push((d.to_string(), m.to_string()));
                    }
                    if c.len() > 1 {
                        refs.push((d.to_string(), c[1].clone()));
                    }
                }
                f => refs.push((rule.entity.clone(), f.to_string())),
            }
        }
        for (e, f) in &refs {
            if let Some(ps) = producer.get(&(e.as_str(), f.as_str())) {
                deps[i].extend(ps.iter().copied().filter(|p| *p != i));
            }
        }
    }
    // Kahn：每次取没有未完成依赖、order 和编码最小的规则
    let mut remaining: Vec<usize> = deps.iter().map(BTreeSet::len).collect();
    let mut dependents: Vec<Vec<usize>> = vec![Vec::new(); calc.len()];
    for (i, ds) in deps.iter().enumerate() {
        for d in ds {
            dependents[*d].push(i);
        }
    }
    let mut ready: BTreeSet<(i64, String, usize)> =
        (0..calc.len()).filter(|i| remaining[*i] == 0).map(|i| (orders[i].0, orders[i].1.clone(), i)).collect();
    let mut out = Vec::with_capacity(calc.len());
    while let Some(first) = ready.iter().next().cloned() {
        ready.remove(&first);
        let i = first.2;
        out.push(i);
        for &j in &dependents[i] {
            remaining[j] -= 1;
            if remaining[j] == 0 {
                ready.insert((orders[j].0, orders[j].1.clone(), j));
            }
        }
    }
    if out.len() == calc.len() {
        return Ok(out);
    }
    // 成环：从任一未排出的规则沿依赖走，直到回到走过的规则
    let start = (0..calc.len()).find(|i| remaining[*i] > 0).expect("有未排出的规则");
    let mut path = vec![start];
    let mut cur = start;
    loop {
        let next = *deps[cur].iter().find(|d| remaining[**d] > 0).expect("未排出的规则一定还有未排出的依赖");
        if let Some(pos) = path.iter().position(|p| *p == next) {
            let mut cycle: Vec<&str> = path[pos..].iter().map(|i| calc[*i].id.as_str()).collect();
            cycle.reverse();
            cycle.push(cycle[0]);
            return Err(format!("计算规则的依赖成环：{}", cycle.join(" → ")));
        }
        path.push(next);
        cur = next;
    }
}
