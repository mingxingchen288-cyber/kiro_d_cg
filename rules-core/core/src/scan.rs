//! 扫描 ZEN 表达式文本：找出引用的字段（算依赖，RC-09）和除数（判断除以 0，模块说明第 8 节）。
//! 只做词法扫描，不求值；字符串字面量里的内容不算引用。

/// 表达式里出现的名称链，例如 `master.APEX_PL` 为 `["master", "APEX_PL"]`，`#.COST_BATCH` 为 `["#", "COST_BATCH"]`。
/// 函数名（后面紧跟括号）和关键字不算。
pub struct Scan {
    pub chains: Vec<Vec<String>>,
    /// `/`、`%` 右边的操作数文本，例如 `(P_PERPACK * S_PERBACK)`、`master.P_PERPACK`。
    pub divisors: Vec<String>,
}

const KEYWORDS: [&str; 7] = ["true", "false", "null", "and", "or", "not", "in"];

pub fn scan(expr: &str) -> Scan {
    let chars: Vec<char> = expr.chars().collect();
    let mut chains = Vec::new();
    let mut divisors = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '\'' || c == '"' || c == '`' {
            i = skip_string(&chars, i);
        } else if c.is_ascii_digit() {
            i = skip_number(&chars, i);
        } else if is_ident_start(c) {
            let (chain, end) = read_chain(&chars, i);
            if !is_call(&chars, end) && !(chain.len() == 1 && KEYWORDS.contains(&chain[0].as_str())) {
                chains.push(chain);
            }
            i = end;
        } else if c == '/' || c == '%' {
            let start = skip_spaces(&chars, i + 1);
            let end = operand_end(&chars, start);
            if end > start {
                divisors.push(chars[start..end].iter().collect::<String>().trim().to_string());
            }
            i += 1;
        } else {
            i += 1;
        }
    }
    Scan { chains, divisors }
}

fn is_ident_start(c: char) -> bool {
    c.is_ascii_alphabetic() || c == '_' || c == '$' || c == '#'
}

fn is_ident_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_'
}

fn skip_spaces(chars: &[char], mut i: usize) -> usize {
    while i < chars.len() && chars[i].is_whitespace() {
        i += 1;
    }
    i
}

fn skip_string(chars: &[char], start: usize) -> usize {
    let quote = chars[start];
    let mut i = start + 1;
    while i < chars.len() {
        if chars[i] == '\\' {
            i += 2;
            continue;
        }
        if chars[i] == quote {
            return i + 1;
        }
        i += 1;
    }
    i
}

fn skip_number(chars: &[char], mut i: usize) -> usize {
    while i < chars.len() && (chars[i].is_ascii_digit() || chars[i] == '.' || chars[i] == '_') {
        i += 1;
    }
    i
}

fn read_ident(chars: &[char], start: usize) -> (String, usize) {
    let mut i = start + 1;
    while i < chars.len() && is_ident_char(chars[i]) {
        i += 1;
    }
    (chars[start..i].iter().collect(), i)
}

fn read_chain(chars: &[char], start: usize) -> (Vec<String>, usize) {
    let (first, mut i) = read_ident(chars, start);
    let mut chain = vec![first];
    while i + 1 < chars.len() && chars[i] == '.' && is_ident_start(chars[i + 1]) {
        let (seg, end) = read_ident(chars, i + 1);
        chain.push(seg);
        i = end;
    }
    (chain, i)
}

fn is_call(chars: &[char], end: usize) -> bool {
    let i = skip_spaces(chars, end);
    i < chars.len() && chars[i] == '('
}

fn matching_paren(chars: &[char], open: usize) -> usize {
    let mut depth = 0;
    let mut i = open;
    while i < chars.len() {
        match chars[i] {
            '\'' | '"' | '`' => {
                i = skip_string(chars, i);
                continue;
            }
            '(' => depth += 1,
            ')' => {
                depth -= 1;
                if depth == 0 {
                    return i + 1;
                }
            }
            _ => {}
        }
        i += 1;
    }
    i
}

/// 除号右边紧跟的一个操作数：括号、名称链（可带调用）或数字，前面可有一元负号。
fn operand_end(chars: &[char], start: usize) -> usize {
    let mut i = start;
    if i < chars.len() && (chars[i] == '-' || chars[i] == '+') {
        i = skip_spaces(chars, i + 1);
    }
    if i >= chars.len() {
        return start;
    }
    let c = chars[i];
    if c == '(' {
        matching_paren(chars, i)
    } else if is_ident_start(c) {
        let (_, end) = read_chain(chars, i);
        let j = skip_spaces(chars, end);
        if j < chars.len() && chars[j] == '(' {
            matching_paren(chars, j)
        } else {
            end
        }
    } else if c.is_ascii_digit() {
        skip_number(chars, i)
    } else {
        start
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn references_and_divisors() {
        let s = scan("ceil(master.APEX_PL / (master.P_PERPACK * master.S_PERBACK) * (1 + EXADD_MATER / 100))");
        let chains: Vec<String> = s.chains.iter().map(|c| c.join(".")).collect();
        assert_eq!(chains, ["master.APEX_PL", "master.P_PERPACK", "master.S_PERBACK", "EXADD_MATER"]);
        assert_eq!(s.divisors, ["(master.P_PERPACK * master.S_PERBACK)", "100"]);
    }

    #[test]
    fn strings_and_closures() {
        let s = scan("sum(map(filter(COST_MATERIAL, #.DTL_USEFLAG == '原料/辅料'), #.COST_BATCH)) > 0 and matches(GOODSNAME, '桶|瓶')");
        let chains: Vec<String> = s.chains.iter().map(|c| c.join(".")).collect();
        assert_eq!(chains, ["COST_MATERIAL", "#.DTL_USEFLAG", "#.COST_BATCH", "GOODSNAME"]);
        assert!(s.divisors.is_empty());
    }
}
