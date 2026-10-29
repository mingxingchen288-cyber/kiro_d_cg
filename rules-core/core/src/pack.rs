//! C07 第 1 节：规则包的解析、JDM 检查和编译、计算规则的依赖排序（RC-03、RC-09）。

use crate::scan::scan;
use serde::Deserialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use zen_engine::model::GraphContent;
use zen_engine::Decision;

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
}

/// load_pack 的结果：编译好的规则（RC-03），计算规则已按依赖排好序（RC-09）。
pub struct Pack {
    pub master: String,
    pub fields: HashMap<String, HashMap<String, FieldType>>,
    pub calc: Vec<CalcRule>,
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
    for rule in pack.rules.iter().filter(|r| r.category == Category::Calc) {
        let graph = graphs[&rule.jdm].clone();
        let (field, expression) = single_expression(&rule.id, &graph)?;
        let entity = rule.entity.clone().unwrap_or_else(|| master.clone());
        let is_master = entity == master;
        let s = scan(&expression);
        let plain_refs = s.chains.iter().filter(|c| c.len() == 1 && !c[0].starts_with(['#', '$'])).map(|c| c[0].clone()).collect();
        let mut decision = Decision::from(graph);
        decision.compile();
        orders.push((rule.order, rule.id.clone(), s.chains));
        calc.push(CalcRule {
            id: rule.id.clone(),
            layer: rule.layer,
            operation: rule.operation.clone(),
            page: rule.page.clone(),
            entity,
            is_master,
            field,
            server_only: rule.server_only,
            plain_refs,
            divisors: s.divisors,
            decision,
        });
    }
    let order = sort(&calc, &orders, &fields, &master)?;
    let mut slots: Vec<Option<CalcRule>> = calc.into_iter().map(Some).collect();
    let calc = order.into_iter().map(|i| slots[i].take().expect("每条规则只排一次")).collect();
    Ok(Pack { master, fields, calc })
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

/// 计算规则的 JDM 约定：只有一个表达式节点、一个表达式，key 为作用的字段。
fn single_expression(rule: &str, graph: &GraphContent) -> Result<(String, String), String> {
    let mut found = Vec::new();
    for node in &graph.nodes {
        if let zen_engine::model::DecisionNodeKind::ExpressionNode { content } = &node.kind {
            for e in content.expressions.iter() {
                found.push((e.key.to_string(), e.value.to_string()));
            }
        }
    }
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
