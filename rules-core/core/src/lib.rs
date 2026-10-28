//! rules-core 的内核（C07）：业务衔接逻辑只在这里写一次（RC-01），Python 包和 WASM 两个包装层只做 JSON 文本进出。

pub mod decimal;
mod eval;
mod pack;
mod scan;

pub use pack::Pack;

use serde_json::{json, Value};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicU64, Ordering};

static COMPILES: AtomicU64 = AtomicU64::new(0);

/// 两个产物返回相同的值（RC-06）。
pub fn core_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// C07 `load_pack`：解析、检查并编译规则包；不合法（包括依赖成环）时返回原因，对应 PACK_INVALID。
pub fn load_pack(bytes: &[u8]) -> Result<Pack, String> {
    let pack = catch_unwind(|| pack::load(bytes)).unwrap_or_else(|_| Err("规则包无法加载".to_string()))?;
    COMPILES.fetch_add(1, Ordering::Relaxed);
    Ok(pack)
}

/// C07 `evaluate`：总是返回第 3 节的 JSON 文本；请求有问题时为 INPUT_INVALID，内部出错为 EVAL_FAILED，不返回部分结果（RC-05）。
pub fn evaluate(pack: &Pack, request_json: &str) -> String {
    let result = catch_unwind(AssertUnwindSafe(|| eval::evaluate(pack, request_json)));
    match result {
        Ok(Ok(value)) => value.to_string(),
        Ok(Err(failure)) => failure_json(failure.code, &failure.message),
        Err(_) => failure_json("EVAL_FAILED", "求值出错"),
    }
}

/// C07 第 3 节的失败结果。
pub fn failure_json(code: &str, message: &str) -> String {
    json!({"ok": false, "error": {"code": code, "message": message}}).to_string()
}

/// 已编译的规则包个数（每次成功的 load_pack 加一），用来检查重复求值不重新编译（RC-03）。
pub fn compile_count() -> u64 {
    COMPILES.load(Ordering::Relaxed)
}

/// 按 C01 第 3 节比较两段 JSON 文本，返回不一致的位置；空表示一致。
pub fn compare_json_text(a: &str, b: &str) -> Result<Vec<String>, String> {
    let a: Value = serde_json::from_str(a).map_err(|e| format!("甲不是 JSON：{e}"))?;
    let b: Value = serde_json::from_str(b).map_err(|e| format!("乙不是 JSON：{e}"))?;
    Ok(decimal::compare_json(&a, &b))
}
