//! Python 包装层：只做 JSON 文本进出（RC-01），业务逻辑都在 rules_core。
//! Python 侧的 `cost_rules_core.RulesEngine`（C08 第 8 节）调用这里的函数。

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

create_exception!(_native, PackInvalid, PyException, "规则包不合法（C07 PACK_INVALID）。");

/// load_pack 返回的句柄：持有编译好的规则包，由垃圾回收释放（C07 第 5 节）。
#[pyclass(frozen, name = "PackHandle", module = "cost_rules_core._native")]
struct PackHandle {
    pack: rules_core::Pack,
}

#[pyfunction]
fn core_version() -> &'static str {
    rules_core::core_version()
}

#[pyfunction]
fn load_pack(py: Python<'_>, pack_json: &[u8]) -> PyResult<PackHandle> {
    let owned = pack_json.to_vec();
    py.detach(move || rules_core::load_pack(&owned))
        .map(|pack| PackHandle { pack })
        .map_err(PackInvalid::new_err)
}

#[pyfunction]
fn evaluate(py: Python<'_>, handle: &Bound<'_, PackHandle>, request_json: &str) -> String {
    let handle = handle.get();
    let request = request_json.to_owned();
    py.detach(move || rules_core::evaluate(&handle.pack, &request))
}

#[pyfunction]
fn failure(code: &str, message: &str) -> String {
    rules_core::failure_json(code, message)
}

#[pyfunction]
fn compile_count() -> u64 {
    rules_core::compile_count()
}

/// C01 第 3 节的数值一致判定（Rust 版）。
#[pyfunction]
fn numbers_consistent(a: &str, b: &str) -> PyResult<bool> {
    rules_core::decimal::numbers_consistent(a, b).map_err(pyo3::exceptions::PyValueError::new_err)
}

/// 按 C01 第 3 节比较两段 JSON 文本，返回不一致的位置；空列表表示一致。
#[pyfunction]
fn compare_json(a: &str, b: &str) -> PyResult<Vec<String>> {
    rules_core::compare_json_text(a, b).map_err(pyo3::exceptions::PyValueError::new_err)
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("PackInvalid", m.py().get_type::<PackInvalid>())?;
    m.add_class::<PackHandle>()?;
    m.add_function(wrap_pyfunction!(core_version, m)?)?;
    m.add_function(wrap_pyfunction!(load_pack, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(failure, m)?)?;
    m.add_function(wrap_pyfunction!(compile_count, m)?)?;
    m.add_function(wrap_pyfunction!(numbers_consistent, m)?)?;
    m.add_function(wrap_pyfunction!(compare_json, m)?)?;
    Ok(())
}
