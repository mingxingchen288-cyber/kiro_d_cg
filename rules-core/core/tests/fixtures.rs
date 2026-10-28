//! 在原生目标上跑样例集（开发时快速核对；两端一致的证据见 Python 包和浏览器的运行）。

use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("fixtures")
}

/// 运行一个样例，返回不通过的原因。
pub fn run(case: &Value) -> Vec<String> {
    let dir = fixtures_dir();
    let read_pack = || fs::read(dir.join(case["pack"].as_str().unwrap())).unwrap();
    match case["kind"].as_str().unwrap() {
        "evaluate" => {
            let pack = match rules_core::load_pack(&read_pack()) {
                Ok(p) => p,
                Err(e) => return vec![format!("load_pack 失败：{e}")],
            };
            let request = serde_json::to_string(&case["request"]).unwrap();
            let actual: Value = serde_json::from_str(&rules_core::evaluate(&pack, &request)).unwrap();
            let expected = &case["expected"];
            if case["match"] == "errorCode" {
                if actual["ok"] == false && actual["error"]["code"] == expected["error"]["code"] {
                    vec![]
                } else {
                    vec![format!("期望错误 {}，实际 {actual}", expected["error"]["code"])]
                }
            } else {
                rules_core::decimal::compare_json(&actual, expected)
            }
        }
        "packInvalid" => match rules_core::load_pack(&read_pack()) {
            Ok(_) => vec!["期望 PACK_INVALID，实际加载成功".into()],
            Err(message) => case["expected"]["messageContains"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|w| !message.contains(w.as_str().unwrap()))
                .map(|w| format!("消息「{message}」不含 {w}"))
                .collect(),
        },
        "consistency" => case["cases"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|c| {
                let got = rules_core::decimal::numbers_consistent(c["a"].as_str().unwrap(), c["b"].as_str().unwrap()).unwrap();
                (Value::Bool(got) != c["consistent"]).then(|| format!("{} 与 {}：判定为 {got}", c["a"], c["b"]))
            })
            .collect(),
        other => vec![format!("未知的样例类型 {other}")],
    }
}

#[test]
fn all_fixtures() {
    let mut paths: Vec<PathBuf> = fs::read_dir(fixtures_dir().join("cases")).unwrap().map(|e| e.unwrap().path()).collect();
    paths.sort();
    let mut failed = 0;
    for path in &paths {
        let case: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        let problems = run(&case);
        if problems.is_empty() {
            println!("通过 {}", case["name"]);
        } else {
            failed += 1;
            println!("失败 {}：\n  {}", case["name"], problems.join("\n  "));
        }
    }
    println!("样例 {} 个，通过 {}，失败 {failed}", paths.len(), paths.len() - failed);
    assert_eq!(failed, 0);
}
