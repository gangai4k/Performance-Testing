"""Best-effort translation of LoadRunner C logic into NeoLoad JavaScript (ES5 / Rhino).

The generated code relies on ``LR_SHIM_JS`` which re-implements the most common
LoadRunner and C library helpers on top of the NeoLoad JavaScript API
(``context.variableManager`` and ``logger``). Constructs that cannot be
translated mechanically are returned as *leftovers* so they are flagged.
"""
from __future__ import annotations

import re
from typing import List, Tuple

LR_SHIM_JS = r"""// ---- lr2nl shim: LoadRunner / C helpers on the NeoLoad JavaScript API ----
function lr_eval_string(s) {
    return String(s).replace(/\{([A-Za-z_]\w*)\}/g, function (m, n) {
        var v = context.variableManager.getValue(n);
        return v === null || v === undefined ? m : v;
    });
}
function lr_save_string(value, name) { context.variableManager.setValue(name, String(value)); return 0; }
function lr_save_int(value, name) { context.variableManager.setValue(name, String(parseInt(value, 10))); return 0; }
function _lr_fmt(args) {
    var fmt = String(args[0]), i = 1;
    return fmt.replace(/%[-+ 0#]*\d*(?:\.\d+)?[lh]*([sdifuxXc%])/g, function (m, t) {
        if (t === "%") { return "%"; }
        var v = args[i++];
        return (t === "d" || t === "i" || t === "u") ? String(parseInt(v, 10)) : String(v);
    });
}
function sprintf() { return _lr_fmt(arguments); }
function lr_error_message() { logger.error(_lr_fmt(arguments)); return 0; }
function lr_output_message() { logger.info(_lr_fmt(arguments)); return 0; }
function lr_log_message() { logger.debug(_lr_fmt(arguments)); return 0; }
function lr_message() { logger.info(_lr_fmt(arguments)); return 0; }
function atoi(s) { var v = parseInt(s, 10); return isNaN(v) ? 0 : v; }
function atol(s) { return atoi(s); }
function atof(s) { var v = parseFloat(s); return isNaN(v) ? 0 : v; }
function strlen(s) { return String(s).length; }
function strcmp(a, b) { a = String(a); b = String(b); return a === b ? 0 : (a < b ? -1 : 1); }
function stricmp(a, b) { return strcmp(String(a).toLowerCase(), String(b).toLowerCase()); }
function strstr(h, n) { var i = String(h).indexOf(n); return i < 0 ? null : String(h).substring(i); }
function rand() { return Math.floor(Math.random() * 32768); }
function srand(seed) { return 0; }
function itoa(v, buf, radix) { return Number(v).toString(radix || 10); }
// ---- end shim ----
"""

SHIM_FUNCS = {"lr_eval_string", "lr_save_string", "lr_save_int", "sprintf", "lr_error_message",
              "lr_output_message", "lr_log_message", "lr_message", "atoi", "atol", "atof", "strlen",
              "strcmp", "stricmp", "strstr", "rand", "srand", "itoa", "time"}

_TYPES = r"(?:unsigned\s+|signed\s+|static\s+|const\s+|extern\s+)*(?:int|long|short|float|double|char|size_t|bool|void)"
_LEFTOVER = [
    (re.compile(r"\b((?:lr|web)_\w+)\s*\("), "LoadRunner API call"),
    (re.compile(r"\b(str(?:cpy|ncpy|cat|ncat|tok|chr|rchr|ncmp)|mem\w+|sscanf|fopen|fclose|fgets|fprintf|malloc|calloc|realloc|free)\s*\("), "C library call"),
    (re.compile(r"(\bsizeof\b|\bgoto\b|->|\bstruct\b)"), "C-only construct"),
    (re.compile(r"(?<![&\w)\]])&(?!&)\s*[A-Za-z_]"), "address-of operator"),
]


def _translate_calls(code: str) -> str:
    # strcpy(dst, src) -> dst = src ; strcat(dst, src) -> dst += src ; sprintf(buf, fmt, ...) -> buf = sprintf(fmt, ...)
    code = re.sub(r"\bstrn?cpy\s*\(\s*([A-Za-z_]\w*)\s*,\s*(.+?)(?:\s*,\s*\d+)?\s*\)\s*;", r"\1 = \2;", code)
    code = re.sub(r"\bstrn?cat\s*\(\s*([A-Za-z_]\w*)\s*,\s*(.+?)(?:\s*,\s*\d+)?\s*\)\s*;", r"\1 += \2;", code)
    code = re.sub(r"\bs(?:n)?printf\s*\(\s*([A-Za-z_]\w*)\s*,\s*(?:\d+\s*,\s*)?", r"\1 = sprintf(", code)
    return code


def c_to_js(code: str) -> Tuple[str, List[str]]:
    """Translate a C fragment; returns (javascript, leftovers)."""
    js = _translate_calls(code)
    js = re.sub(r"\(\s*(?:const\s+)?(?:char|int|long|double|float)\s*\*?\s*\)", "", js)   # casts
    js = re.sub(r"(^|[;{}(]\s*|\n\s*)%s\s*\**\s*(?=[A-Za-z_])" % _TYPES, r"\1var ", js)    # declarations
    js = re.sub(r"(\bvar\s+[A-Za-z_]\w*)\s*\[[^\]]*\]", r"\1", js)                         # char buf[100]
    js = re.sub(r",\s*\*?\s*([A-Za-z_]\w*)\s*\[[^\]]*\]", r", \1", js)
    js = re.sub(r"\bNULL\b", "null", js)
    js = re.sub(r"\bTRUE\b", "true", js)
    js = re.sub(r"\bFALSE\b", "false", js)
    js = re.sub(r"\blr_exit\s*\([^;]*\)\s*;", "throw new Error('lr_exit');  // TODO review: lr_exit", js)
    leftovers: List[str] = []
    for rx, label in _LEFTOVER:
        for m in rx.finditer(js):
            token = m.group(1) if m.groups() else m.group(0)
            if token.strip() in SHIM_FUNCS:
                continue
            leftovers.append(f"{label}: {token.strip()}")
    return js, sorted(set(leftovers))


def function_to_js(name: str, params: str, body: str) -> Tuple[str, List[str]]:
    names = []
    for p in [p.strip() for p in params.split(",") if p.strip() and p.strip() != "void"]:
        m = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", p)
        if m:
            names.append(m.group(1))
    js_body, leftovers = c_to_js(body)
    return f"function {name}({', '.join(names)}) {{{js_body}}}\n", leftovers
