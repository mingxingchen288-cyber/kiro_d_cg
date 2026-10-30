//! C01 第 2、3 节：十进制文本的解析、格式化和数值一致判定（Rust 版）。
//! 全程用 `rust_decimal`，不经过 `f64`（RC-02）。

use rust_decimal::Decimal;
use serde_json::Value;
use std::str::FromStr;

/// 是否为 C01 第 2 节的十进制文本：`^-?[0-9]+(\.[0-9]+)?$`。
pub fn is_decimal_text(text: &str) -> bool {
    split(text).is_some()
}

/// 拆成（负号、整数部分、小数部分）；格式不合法时为 None。
fn split(text: &str) -> Option<(bool, &str, &str)> {
    let (negative, body) = match text.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, text),
    };
    let (integer, fraction) = match body.split_once('.') {
        Some((i, f)) => {
            if f.is_empty() {
                return None;
            }
            (i, f)
        }
        None => (body, ""),
    };
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    if !digits(integer) || (!fraction.is_empty() && !digits(fraction)) {
        return None;
    }
    Some((negative, integer, fraction))
}

/// 把十进制文本解析为 Decimal；格式不合法或超出 28 位有效数字时为 Err。
pub fn parse(text: &str) -> Result<Decimal, String> {
    if !is_decimal_text(text) {
        return Err(format!("\"{text}\" 不是十进制文本（C01 第 2 节）"));
    }
    Decimal::from_str_exact(text)
        .or_else(|_| Decimal::from_str(text))
        .map_err(|_| format!("\"{text}\" 超出 28 位有效数字"))
}

/// 把 Decimal 格式化为十进制文本：不用指数，去掉末尾的零，零不带负号；不舍入（RC-04）。
pub fn format(value: Decimal) -> String {
    value.normalize().to_string()
}

/// 保存时最多保留的小数位（write-pipeline 的 WP-15）。
pub const STORED_PLACES: u32 = 8;

/// 按 WP-15 的写法得到保存后的值：最多 8 位小数，第 9 位四舍五入，负数按绝对值四舍五入（与 Oracle、后端
/// `pipeline/values.py` 的 `ROUND_HALF_UP` 相同）；小数位不超过 8 位的原样返回。只用于判断计算是否带出变化（C07 v8），
/// 计算本身和 `computed` 仍不舍入（RC-04）。列定义了更小小数位的情况不在这里处理：rules-core 不知道列的小数位，
/// 规则包字段的 `scale` 是显示小数位（C05），不是列的小数位；d_cg 和旧库 cmx 中计算字段的列都没有定义小数位，一律 8 位。
pub fn stored(value: Decimal) -> Decimal {
    value.round_dp_with_strategy(STORED_PLACES, rust_decimal::RoundingStrategy::MidpointAwayFromZero)
}

/// C01 第 3 节：两个十进制文本是否一致。
pub fn numbers_consistent(a: &str, b: &str) -> Result<bool, String> {
    Ok(key(a)? == key(b)?)
}

/// C01 第 3 节：两个数值是否一致（按格式化后的十进制文本判定，与 `numbers_consistent` 相同）。
pub fn consistent(a: Decimal, b: Decimal) -> bool {
    numbers_consistent(&format(a), &format(b)).unwrap_or(false)
}

/// 正负号、整数部分（去掉前导零）、截断（不舍入）到 15 位的小数部分；截断后为零的数不区分正负。
fn key(text: &str) -> Result<(bool, String, String), String> {
    let (negative, integer, fraction) =
        split(text).ok_or_else(|| format!("\"{text}\" 不是十进制文本（C01 第 2 节）"))?;
    let integer = integer.trim_start_matches('0');
    let integer = if integer.is_empty() { "0" } else { integer };
    let mut fraction15: String = fraction.chars().take(15).collect();
    while fraction15.len() < 15 {
        fraction15.push('0');
    }
    let zero = integer == "0" && fraction15.bytes().all(|b| b == b'0');
    Ok((negative && !zero, integer.to_string(), fraction15))
}

/// 按 C01 第 3 节比较两个 JSON 值：两边都是十进制文本的按数值一致判定，其余必须完全相同；
/// 一方为空、另一方为数值时不一致。返回所有不一致的位置，空表示一致。
pub fn compare_json(a: &Value, b: &Value) -> Vec<String> {
    let mut diffs = Vec::new();
    walk(a, b, "$", &mut diffs);
    diffs
}

fn walk(a: &Value, b: &Value, path: &str, diffs: &mut Vec<String>) {
    match (a, b) {
        (Value::String(x), Value::String(y)) if is_decimal_text(x) && is_decimal_text(y) => {
            if !numbers_consistent(x, y).unwrap_or(false) {
                diffs.push(format!("{path}: {x} ≠ {y}"));
            }
        }
        (Value::Object(x), Value::Object(y)) => {
            for (k, va) in x {
                match y.get(k) {
                    Some(vb) => walk(va, vb, &format!("{path}.{k}"), diffs),
                    None => diffs.push(format!("{path}.{k}: 只在一方出现")),
                }
            }
            for k in y.keys() {
                if !x.contains_key(k) {
                    diffs.push(format!("{path}.{k}: 只在一方出现"));
                }
            }
        }
        (Value::Array(x), Value::Array(y)) => {
            if x.len() != y.len() {
                diffs.push(format!("{path}: 长度 {} ≠ {}", x.len(), y.len()));
                return;
            }
            for (i, (va, vb)) in x.iter().zip(y).enumerate() {
                walk(va, vb, &format!("{path}[{i}]"), diffs);
            }
        }
        _ => {
            if a != b {
                diffs.push(format!("{path}: {a} ≠ {b}"));
            }
        }
    }
}
