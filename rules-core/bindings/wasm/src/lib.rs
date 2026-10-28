//! WASM 包装层（wasm32-wasip1）：只做 JSON 文本进出（RC-01），业务逻辑都在 rules_core。
//!
//! 导出给 `web/src/index.js` 的 C 接口：
//! - `rc_alloc(len) -> ptr`、`rc_free(ptr, len)`：JS 写入输入文本用的缓冲区；
//! - `rc_load_pack(ptr, len) -> handle`：成功时句柄大于 0；为 0 时，输出缓冲区是 C07 第 3 节的失败 JSON；
//! - `rc_evaluate(handle, ptr, len)`：输出缓冲区是第 3 节的结果 JSON；句柄不存在时为 PACK_INVALID；
//! - `rc_dispose(handle)`、`rc_core_version()`、`rc_compare_json(a_ptr, a_len, b_ptr, b_len)`（C01 判定，输出为不一致位置的 JSON 数组）；
//! - `rc_out_ptr()`、`rc_out_len()`：读取最近一次的输出文本（UTF-8）。

use std::cell::RefCell;
use std::collections::HashMap;

thread_local! {
    static PACKS: RefCell<HashMap<u32, rules_core::Pack>> = RefCell::new(HashMap::new());
    static NEXT: RefCell<u32> = const { RefCell::new(1) };
    static OUT: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
}

fn set_out(text: String) {
    OUT.with(|o| *o.borrow_mut() = text.into_bytes());
}

/// # Safety
/// `ptr`、`len` 必须是 `rc_alloc` 分配、已由 JS 写满的缓冲区。
unsafe fn input<'a>(ptr: *const u8, len: usize) -> &'a [u8] {
    if len == 0 {
        &[]
    } else {
        std::slice::from_raw_parts(ptr, len)
    }
}

#[no_mangle]
pub extern "C" fn rc_alloc(len: usize) -> *mut u8 {
    let mut buf = Vec::<u8>::with_capacity(len.max(1));
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    ptr
}

/// # Safety
/// 只能释放 `rc_alloc` 分配的缓冲区，`len` 与分配时相同。
#[no_mangle]
pub unsafe extern "C" fn rc_free(ptr: *mut u8, len: usize) {
    drop(Vec::from_raw_parts(ptr, 0, len.max(1)));
}

#[no_mangle]
pub extern "C" fn rc_out_ptr() -> *const u8 {
    OUT.with(|o| o.borrow().as_ptr())
}

#[no_mangle]
pub extern "C" fn rc_out_len() -> usize {
    OUT.with(|o| o.borrow().len())
}

#[no_mangle]
pub extern "C" fn rc_core_version() {
    set_out(rules_core::core_version().to_string());
}

/// # Safety
/// 见 `input`。
#[no_mangle]
pub unsafe extern "C" fn rc_load_pack(ptr: *const u8, len: usize) -> u32 {
    match rules_core::load_pack(input(ptr, len)) {
        Ok(pack) => {
            let handle = NEXT.with(|n| {
                let mut n = n.borrow_mut();
                let h = *n;
                *n += 1;
                h
            });
            PACKS.with(|p| p.borrow_mut().insert(handle, pack));
            set_out(String::new());
            handle
        }
        Err(message) => {
            set_out(rules_core::failure_json("PACK_INVALID", &message));
            0
        }
    }
}

/// # Safety
/// 见 `input`。
#[no_mangle]
pub unsafe extern "C" fn rc_evaluate(handle: u32, ptr: *const u8, len: usize) {
    let request = String::from_utf8_lossy(input(ptr, len)).into_owned();
    let out = PACKS.with(|p| match p.borrow().get(&handle) {
        Some(pack) => rules_core::evaluate(pack, &request),
        None => rules_core::failure_json("PACK_INVALID", "规则包没有加载"),
    });
    set_out(out);
}

#[no_mangle]
pub extern "C" fn rc_dispose(handle: u32) {
    PACKS.with(|p| p.borrow_mut().remove(&handle));
}

#[no_mangle]
pub extern "C" fn rc_compile_count() -> u64 {
    rules_core::compile_count()
}

/// # Safety
/// 见 `input`。
#[no_mangle]
pub unsafe extern "C" fn rc_compare_json(a_ptr: *const u8, a_len: usize, b_ptr: *const u8, b_len: usize) {
    let a = String::from_utf8_lossy(input(a_ptr, a_len)).into_owned();
    let b = String::from_utf8_lossy(input(b_ptr, b_len)).into_owned();
    let out = match rules_core::compare_json_text(&a, &b) {
        Ok(diffs) => serde_json::to_string(&diffs).unwrap_or_default(),
        Err(e) => serde_json::to_string(&[e]).unwrap_or_default(),
    };
    set_out(out);
}
