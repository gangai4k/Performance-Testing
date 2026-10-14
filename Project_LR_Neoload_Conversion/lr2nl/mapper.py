"""Mapping engine: LoadRunner statements -> NeoLoad as-code model.

Every construct found in the source is scored (see model.py weights) and any
approximation or unsupported item is recorded as an Issue, never dropped.
"""
from __future__ import annotations

import base64
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from .cparse import Stmt, literal_value
from .jstranslate import c_to_js, function_to_js
from .lrproject import STANDARD_INCLUDES, LrScript
from .model import OK, PARTIAL, TRANSLATED, UNSUPPORTED, Issue, ScriptModel, neoload_ref

PARAM_RX = re.compile(r"\{([A-Za-z_]\w*)\}")
EVAL_RX = re.compile(r'^lr_eval_string\s*\(\s*("(?:\\.|[^"\\])*")\s*\)$', re.S)
REQUEST_FUNCS = {"web_url", "web_custom_request", "web_submit_data", "web_submit_form", "web_link",
                 "web_image", "web_rest", "web_request"}
IGNORED_ATTRS = {"snapshot", "mode", "resource", "targetframe", "reccontenttype", "recordedtargetframe",
                 "tag", "ordinal", "userdatarequestid", "url_type", "preservecontenttype", "itemdata"}
INFO_ONLY = {
    "web_set_max_html_param_len": "Buffer size setting not needed in NeoLoad.",
    "web_set_sockets_option": "Socket option: configure in NeoLoad project settings if required.",
    "web_set_timeout": "Timeout: configure in NeoLoad runtime / server settings.",
    "lr_set_debug_message": "Debug logging level is a runtime option in NeoLoad.",
    "web_cache_cleanup": "NeoLoad browser cache is configured on the population (new user/cache per VU).",
    "web_enable_ip_spoofing": "IP spoofing is configured on the NeoLoad load generator.",
    "web_reg_add_cookie": "Cookie recording directive; NeoLoad manages cookies automatically.",
    "web_concurrent_start": "Concurrent groups are replayed sequentially; NeoLoad fetches resources in parallel.",
    "web_concurrent_end": "End of concurrent group.",
}


class Mapper:
    def __init__(self, script: LrScript):
        self.s = script
        self.m = ScriptModel(name=script.name)
        self.helper_names = set()
        self.file = ""
        self.cur: List[dict] = []
        self.tx_stack: List[Tuple[str, List[dict], int]] = []
        self.pending_extractors: List[dict] = []
        self.pending_assertions: List[dict] = []
        self.global_assertions: List[dict] = []
        self.next_headers: Dict[str, str] = {}
        self.auto_headers: Dict[str, str] = {}
        self.cookies: Dict[str, str] = {}
        self.last_server: Optional[str] = None
        self.known_vars = set(script.params)
        self.used_vars = set()
        self.refmap: Dict[str, str] = {}
        self.js_logic: List[str] = []

    # -- helpers ---------------------------------------------------------
    def issue(self, sev: str, line: int, construct: str, msg: str) -> None:
        self.m.issues.append(Issue(sev, self.file, line, construct, msg))

    def score(self, kind: str, weight: float, line: int = 0, msg: str = "", sev: Optional[str] = None) -> None:
        self.m.tally.add(kind, weight)
        if msg:
            self.issue(sev or ("INFO" if weight >= OK else "REVIEW"), line, kind, msg)

    def emit(self, step: dict) -> None:
        self.cur.append(step)

    def comment(self, text: str) -> None:
        self.cur.append({"__comment__": text})

    def nl(self, text: str) -> str:
        """Convert LoadRunner {param} references to NeoLoad ${param}."""
        def repl(mm):
            self.used_vars.add(mm.group(1))
            return neoload_ref(self.refmap.get(mm.group(1), mm.group(1)))
        return PARAM_RX.sub(repl, text)

    def value(self, arg: str) -> Tuple[Optional[str], bool]:
        """(value, is_static). Accepts literals and lr_eval_string("literal")."""
        lit = literal_value(arg)
        if lit is not None:
            return lit, True
        mm = EVAL_RX.match(arg.strip())
        if mm:
            return literal_value(mm.group(1)), True
        return None, False

    # -- entry -----------------------------------------------------------
    def run(self) -> ScriptModel:
        s = self.s
        for err in s.parse_errors:
            self.m.issues.append(Issue("REVIEW", err.split(":", 1)[0], 0, "parse", "Parse error: " + err))
        funcs: Dict[str, Stmt] = {}
        for fname, stmts in s.files.items():
            for st in stmts:
                if st.kind == "func":
                    funcs.setdefault(st.name, st)
        entry_names = {"vuser_init", "vuser_end"}
        action_files = [f for f in s.files if f.lower() not in ("vuser_init.c", "vuser_end.c") and f.lower().endswith(".c")]
        actions = []
        for fname in action_files:
            stem = os.path.splitext(fname)[0]
            fn = next((st for st in s.files[fname] if st.kind == "func" and st.name in (stem, "Action")), None)
            if fn is not None:
                actions.append((stem, fn))
                entry_names.add(fn.name)
        order = [a.lower() for a in s.runtime.action_order]
        actions.sort(key=lambda a: (order.index(a[0].lower()) if a[0].lower() in order else
                                    (-1 if a[0].lower() == "action" else len(order)), a[0].lower()))
        self.helper_names = {n for n in funcs if n not in entry_names}

        self._map_globals()
        self._map_params()
        if "vuser_init" in funcs:
            self._section("init", [("vuser_init", funcs["vuser_init"])])
        self._section("actions", actions)
        if not actions:
            self.m.issues.append(Issue("REVIEW", "", 0, "actions", "No Action function found in the script."))
        if len(actions) > 1:
            self.m.issues.append(Issue("INFO", "", 0, "run-logic", "Action order used: " + ", ".join(a[0] for a in actions)
                                       + " (verify against the LoadRunner Run Logic)."))
        self._apply_pacing()
        if "vuser_end" in funcs:
            self._section("end", [("vuser_end", funcs["vuser_end"])])
        self._map_helpers(funcs)
        for name in sorted(self.used_vars - self.known_vars):
            self.m.issues.append(Issue("REVIEW", "", 0, "parameter", f"{{{name}}} is used but never defined (no .prm "
                                       f"entry, correlation or lr_save_string). Define a NeoLoad variable named '{name}'."))
        for note in s.runtime.notes:
            self.m.issues.append(Issue("INFO", "default.cfg/default.usp", 0, "runtime", note))
        return self.m

    def _section(self, section: str, funcs: List[Tuple[str, Stmt]]) -> None:
        self.cur = self.m.sections[section]
        for label, fn in funcs:
            self.file = fn.src_file
            if section == "actions" and len(funcs) > 1:
                self.comment(f"LoadRunner action: {label} ({fn.src_file})")
            self.stmts(fn.body)
            while self.tx_stack:
                name, prev, line = self.tx_stack.pop()
                self.cur = prev
                self.issue("REVIEW", line, "transaction", f"Transaction '{name}' is never ended in {label}; "
                           "it was closed at the end of the action.")
        for ex in self.pending_extractors:
            self.issue("REVIEW", 0, "correlation", f"Correlation '{ex['name']}' is registered but no request follows it.")
        for a in self.pending_assertions:
            self.issue("REVIEW", 0, "check", f"Check {a} is registered but no request follows it.")
        self.pending_extractors, self.pending_assertions = [], []

    # -- statements ------------------------------------------------------
    def stmts(self, stmts: List[Stmt]) -> None:
        for st in stmts:
            self.stmt(st)

    def stmt(self, st: Stmt) -> None:
        k = st.kind
        if k in ("call", "assign_call"):
            self.call(st)
        elif k == "block":
            self.stmts(st.body)
        elif k in ("if", "for", "while", "do", "switch"):
            self.control(st)
        elif k == "decl":
            pass  # declarations carry no runtime behaviour; they are kept in translated JS blocks
        elif k == "pre":
            self.preproc(st)
        elif k == "label":
            pass
        elif k == "func":
            self.score("nested-function", UNSUPPORTED, st.line, f"Nested function '{st.name}' is not supported.")
        else:
            self.expr(st)

    def expr(self, st: Stmt) -> None:
        text = st.text.strip()
        if not text or text in ("break", "continue") or re.fullmatch(r"return\s*(\(\s*0\s*\)|0)?", text):
            return
        if text.startswith("return"):
            self.score("return", PARTIAL, st.line, f"'{text}' ends the action early in LoadRunner. "
                       "Use a NeoLoad 'Stop virtual user' / 'Go to next iteration' action.")
            return
        self._logic(st, text + ";")

    def _logic(self, st: Stmt, ccode: str, kind: str = "custom-logic") -> None:
        js, left = c_to_js(ccode)
        weight = TRANSLATED if not left else PARTIAL
        tag = f"{self.file}:{st.line}"
        self.js_logic.append(f"// {tag}  (LoadRunner: {' '.join(ccode.split())[:120]})\n{js.strip()}\n")
        self.comment(f"[LR logic {tag}] -> JavaScript in custom_js; add a NeoLoad JavaScript action here")
        msg = "C logic translated to JavaScript; add it as a JavaScript action at this position"
        if left:
            msg += ". Not translated: " + "; ".join(left)
        self.score(kind, weight, st.line, msg + ".")

    def preproc(self, st: Stmt) -> None:
        mm = re.match(r"#\s*include\s*[<\"]([^>\"]+)[>\"]", st.text)
        if mm:
            if mm.group(1).lower() not in STANDARD_INCLUDES and mm.group(1) not in self.s.files:
                self.score("include", PARTIAL, st.line, f"Included file '{mm.group(1)}' was not found in the script folder.")
            return
        if re.match(r"#\s*(ifndef|ifdef|endif|else|pragma|undef)\b|#\s*define\s+\w+\s*$", st.text):
            return  # include guards and compiler pragmas have no runtime behaviour
        mm = re.match(r"#\s*define\s+([A-Za-z_]\w*)\s+(.+)$", st.text, re.S)
        if mm:
            self.m.js_chunks.append(f"var {mm.group(1)} = {mm.group(2).strip()};  // from #define\n")
            self.score("define", TRANSLATED, st.line, f"#define {mm.group(1)} moved to custom_js as a JavaScript variable.")
            return
        self.score("preprocessor", PARTIAL, st.line, f"Preprocessor directive '{st.text[:60]}' needs review.")

    def _has_request(self, stmts: List[Stmt]) -> bool:
        for st in stmts:
            if st.kind in ("call", "assign_call") and (st.name in REQUEST_FUNCS or st.name in self.helper_names):
                return True
            if self._has_request(st.body) or self._has_request(st.orelse):
                return True
        return False

    def control(self, st: Stmt) -> None:
        cond_js, _ = c_to_js(st.cond)
        if not (self._has_request(st.body) or self._has_request(st.orelse)):
            raw = self.s.raw.get(st.src_file, "")
            snippet = _source_of(raw, st)
            self._logic(st, snippet, kind=f"{st.kind}-logic")
            return
        neo = {"if": "NeoLoad 'If' logical action", "switch": "NeoLoad 'If' actions (one per case)",
               "for": "NeoLoad 'Loop' logical action", "while": "NeoLoad 'While' logical action",
               "do": "NeoLoad 'While' logical action"}[st.kind]
        self.comment(f"[LR {st.kind} ({st.cond})] BEGIN - rebuild as {neo}; JS condition: {cond_js}")
        if st.kind == "switch":
            groups, cur = [], None
            for s2 in st.body:
                if s2.kind == "label":
                    cur = (s2.text, [])
                    groups.append(cur)
                elif cur is not None:
                    cur[1].append(s2)
            for idx, (label, body) in enumerate(groups):
                self.comment(f"[LR {label}]")
                self._branch(body, active=(idx == 0))
        else:
            self._branch(st.body, active=True)
            if st.orelse:
                self.comment("[LR else] branch below is commented out (both branches cannot run in sequence)")
                self._branch(st.orelse, active=False)
        self.comment(f"[LR {st.kind}] END")
        msg = (f"'{st.kind} ({st.cond})' contains requests. Steps of the first branch are emitted inline, "
               f"other branches are kept as comments. Rebuild as {neo} with condition: {cond_js}")
        if st.kind in ("for", "while", "do"):
            count = _loop_count(st.cond) if st.kind == "for" else None
            msg = (f"Loop '{st.kind} ({st.cond})' contains requests; the body is emitted once. "
                   + (f"Wrap it in a {neo} with {count} iterations." if count else
                      f"Wrap it in a {neo} (condition: {cond_js})."))
        self.score(f"{st.kind}-flow", PARTIAL, st.line, msg)

    def _branch(self, body: List[Stmt], active: bool) -> None:
        if active:
            self.stmts(body)
            return
        saved = self.cur
        self.cur = []
        self.stmts(body)
        steps, self.cur = self.cur, saved
        if steps:
            self.emit({"__commented__": steps})

    # -- calls -----------------------------------------------------------
    def call(self, st: Stmt) -> None:
        name = st.name
        handler = getattr(self, "h_" + name, None)
        if handler is not None:
            handler(st)
        elif name in REQUEST_FUNCS:
            self.request(st)
        elif name in INFO_ONLY:
            self.score(name, OK, st.line, INFO_ONLY[name], sev="INFO")
        elif name in self.helper_names:
            self.comment(f"[LR call {st.text[:100]}] -> JavaScript function {name}() in custom_js")
            weight = PARTIAL if self._has_request(self._func_body(name)) else TRANSLATED
            self.score("custom-function-call", weight, st.line,
                       f"Call to custom C function {name}(): add a JavaScript action calling {name}() "
                       "(see custom_js)" + (" - the function sends requests, rebuild them as NeoLoad requests."
                                            if weight == PARTIAL else "."))
        elif name.startswith(("lr_", "web_", "soap_", "sapgui_", "tc_", "ctrx_", "mms_", "smtp_")):
            self.score(name, UNSUPPORTED, st.line, f"LoadRunner API {name}() has no automatic NeoLoad mapping.")
        else:
            self._logic(st, st.text + ";")

    def _func_body(self, name: str) -> List[Stmt]:
        for stmts in self.s.files.values():
            for st in stmts:
                if st.kind == "func" and st.name == name:
                    return st.body
        return []

    def args_kv(self, st: Stmt, skip: int = 0) -> Tuple[Dict[str, str], List[str]]:
        """Parse "Key=Value" literal arguments (stops at LAST)."""
        kv, dynamic = {}, []
        for a in st.args[skip:]:
            if a.strip() == "LAST":
                break
            v, static = self.value(a)
            if not static:
                dynamic.append(a)
                continue
            key, sep, val = v.partition("=")
            if sep:
                kv[key.strip().lower()] = val
        return kv, dynamic

    # transactions
    def h_lr_start_transaction(self, st: Stmt) -> None:
        name, static = self.value(st.args[0]) if st.args else (None, False)
        if not static:
            name = f"TX_line_{st.line}"
            self.score("transaction", PARTIAL, st.line, f"Dynamic transaction name {st.args[:1]} replaced by '{name}'.")
        else:
            self.m.tally.add("transaction", OK)
        tx = {"transaction": {"name": self.nl(name), "steps": []}}
        self.emit(tx)
        self.tx_stack.append((name, self.cur, st.line))
        self.cur = tx["transaction"]["steps"]
        self.m.bump("transactions")

    h_lr_start_sub_transaction = h_lr_start_transaction

    def h_lr_end_transaction(self, st: Stmt) -> None:
        name, _ = self.value(st.args[0]) if st.args else (None, False)
        status = st.args[1].strip() if len(st.args) > 1 else "LR_AUTO"
        idx = next((i for i in range(len(self.tx_stack) - 1, -1, -1) if self.tx_stack[i][0] == name), None)
        if idx is None:
            self.score("transaction-end", UNSUPPORTED, st.line, f"lr_end_transaction('{name}') has no matching start.")
            return
        if idx != len(self.tx_stack) - 1:
            self.issue("REVIEW", st.line, "transaction", f"Transactions overlap at '{name}'; NeoLoad containers must "
                       "nest, inner transactions were closed here.")
        self.cur = self.tx_stack[idx][1]
        del self.tx_stack[idx:]
        if status in ("LR_AUTO", "LR_PASS"):
            self.m.tally.add("transaction-end", OK)
        else:
            self.score("transaction-end", PARTIAL, st.line, f"Transaction '{name}' ends with status {status}; "
                       "NeoLoad sets transaction status from its requests/assertions. Add an assertion or "
                       "a JavaScript 'context.fail()' equivalent if this status was forced on purpose.")

    h_lr_end_sub_transaction = h_lr_end_transaction

    def h_lr_set_transaction_status(self, st: Stmt) -> None:
        self.score("transaction-status", PARTIAL, st.line, f"{st.text[:80]}: forced status must be rebuilt with an "
                   "assertion or JavaScript in NeoLoad.")

    h_lr_set_transaction_status_by_name = h_lr_set_transaction_status
    h_lr_set_transaction = h_lr_set_transaction_status

    # think time
    def h_lr_think_time(self, st: Stmt) -> None:
        rt = self.s.runtime
        try:
            secs = float(st.args[0])
        except (ValueError, IndexError):
            v, _ = self.value(st.args[0]) if st.args else (None, False)
            self.emit({"delay": self.nl(v) if v else "1s"})
            self.score("think-time", PARTIAL, st.line, f"Dynamic think time {st.args[:1]}: set the delay manually.")
            return
        note = ""
        if rt.think_mode == "ignore":
            self.comment(f"[LR lr_think_time({secs:g})] ignored: run-time settings ignore think time")
            self.score("think-time", OK, st.line, "Think time ignored per run-time settings.", sev="INFO")
            return
        if rt.think_mode == "multiply":
            secs *= rt.think_factor
            note = f"multiplied by {rt.think_factor:g}"
        elif rt.think_mode == "random":
            note = f"LoadRunner randomises {rt.think_min_pct:g}-{rt.think_max_pct:g}%; use NeoLoad think-time randomisation"
        if rt.think_limit is not None and secs > rt.think_limit:
            secs = rt.think_limit
            note = f"limited to {rt.think_limit:g}s"
        self.emit({"delay": _secs(secs)})
        self.m.bump("think_times")
        if rt.think_mode == "random":
            self.score("think-time", PARTIAL, st.line, note + ".")
        else:
            self.score("think-time", OK, st.line, ("Think time " + note + ".") if note else "", sev="INFO")

    # parameters
    def h_lr_save_string(self, st: Stmt) -> None:
        val, vstatic = self.value(st.args[0]) if st.args else (None, False)
        name, nstatic = self.value(st.args[1]) if len(st.args) > 1 else (None, False)
        if nstatic:
            self.known_vars.add(name)
        if vstatic and nstatic and not PARAM_RX.search(val):
            if not any(v.get("constant", {}).get("name") == name for v in self.m.variables):
                self.m.variables.append({"constant": {"name": name, "value": val}})
            self.score("lr_save_string", OK, st.line, f"lr_save_string -> NeoLoad constant variable '{name}'.", sev="INFO")
            return
        self._logic(st, st.text + ";", kind="lr_save_string")

    h_lr_save_int = h_lr_save_string

    # logging / errors
    def h_lr_error_message(self, st: Stmt) -> None:
        self._logic(st, st.text + ";", kind="error-handling")

    h_lr_output_message = h_lr_error_message
    h_lr_log_message = h_lr_error_message
    h_lr_message = h_lr_error_message
    h_lr_vuser_status_message = h_lr_error_message

    def h_lr_exit(self, st: Stmt) -> None:
        self.score("lr_exit", PARTIAL, st.line, f"{st.text[:80]}: use NeoLoad 'Stop virtual user' or "
                   "'Go to next iteration' logical action at this point.")
        self.comment(f"[LR {st.text[:100]}] -> NeoLoad Stop/Next-iteration action")

    h_lr_abort = h_lr_exit

    def h_lr_continue_on_error(self, st: Stmt) -> None:
        self.score("continue-on-error", PARTIAL, st.line, "lr_continue_on_error: set the NeoLoad population/runtime "
                   "'on error' policy (continue / stop iteration).")

    def h_lr_rendezvous(self, st: Stmt) -> None:
        self.comment(f"[LR {st.text}] -> NeoLoad Rendezvous action")
        self.score("rendezvous", PARTIAL, st.line, "Add a NeoLoad Rendezvous logical action at this point.")

    # headers & cookies
    def h_web_add_header(self, st: Stmt, auto: bool = False) -> None:
        k, ks = self.value(st.args[0]) if st.args else (None, False)
        v, vs = self.value(st.args[1]) if len(st.args) > 1 else (None, False)
        if not (ks and vs):
            self.score("header", PARTIAL, st.line, f"Dynamic header {st.text[:80]}: set the value manually.")
            return
        (self.auto_headers if auto else self.next_headers)[k] = self.nl(v)
        self.m.tally.add("header", OK)

    def h_web_add_auto_header(self, st: Stmt) -> None:
        self.h_web_add_header(st, auto=True)

    def h_web_revert_auto_header(self, st: Stmt) -> None:
        k, _ = self.value(st.args[0]) if st.args else (None, False)
        self.auto_headers = {h: v for h, v in self.auto_headers.items() if h.lower() != (k or "").lower()}
        self.m.tally.add("header", OK)

    h_web_remove_auto_header = h_web_revert_auto_header

    def h_web_cleanup_auto_headers(self, st: Stmt) -> None:
        self.auto_headers = {}
        self.m.tally.add("header", OK)

    def h_web_add_cookie(self, st: Stmt) -> None:
        v, static = self.value(st.args[0]) if st.args else (None, False)
        if not static:
            self.score("cookie", PARTIAL, st.line, f"Dynamic cookie {st.text[:80]}: add it manually.")
            return
        first = v.split(";")[0]
        cname, _, cval = first.partition("=")
        self.cookies[cname.strip()] = self.nl(cval.strip())
        domain = re.search(r"domain\s*=\s*([^;]+)", v, re.I)
        self.score("cookie", OK, st.line, f"Cookie '{cname.strip()}' is sent as a Cookie header on later requests"
                   + (f" (LR domain {domain.group(1).strip()})" if domain else "")
                   + ". NeoLoad also manages server cookies automatically.", sev="INFO")

    def h_web_remove_cookie(self, st: Stmt) -> None:
        v, _ = self.value(st.args[0]) if st.args else ("", False)
        self.cookies.pop((v or "").split("=")[0].split(";")[0].strip(), None)
        self.m.tally.add("cookie", OK)

    def h_web_cleanup_cookies(self, st: Stmt) -> None:
        self.cookies = {}
        self.comment("[LR web_cleanup_cookies()] -> enable 'clear cookies' (new user session) in NeoLoad")
        self.score("cookie-cleanup", PARTIAL, st.line, "web_cleanup_cookies: NeoLoad clears cookies per new virtual "
                   "user; for a mid-iteration reset add a JavaScript action.")

    def h_web_set_user(self, st: Stmt) -> None:
        vals = [self.value(a) for a in st.args[:3]]
        if len(vals) >= 2 and all(s for _, s in vals[:2]) and not PARAM_RX.search(vals[0][0] + vals[1][0]):
            token = base64.b64encode(f"{vals[0][0]}:{vals[1][0]}".encode()).decode()
            self.auto_headers["Authorization"] = "Basic " + token
            self.score("authentication", PARTIAL, st.line, "web_set_user mapped to a Basic Authorization header. "
                       "If the server uses NTLM/Negotiate, configure authentication on the NeoLoad server instead. "
                       "The credential is now in the YAML - move it to a protected variable.")
        else:
            self.score("authentication", PARTIAL, st.line, "web_set_user: configure server authentication in NeoLoad.")

    # correlation
    def _extractor(self, st: Stmt, name: str, base: dict, kv: Dict[str, str], line: int) -> None:
        notes = []
        search = kv.get("search", "body").lower()
        if search.startswith("header"):
            base["from"] = "header"
        elif search == "all":
            base["from"] = "body"
            notes.append("Search=All -> body only; add a header extractor if the value can be in headers")
        else:
            base["from"] = "body"
        ordv = kv.get("ord", kv.get("ordinal", "1"))
        if ordv.lower() == "all":
            base["match_number"] = -1
            notes.append("Ord=All -> match_number -1 (all); LoadRunner creates name_1..name_count arrays")
        else:
            try:
                base["match_number"] = int(ordv)
            except ValueError:
                notes.append(f"Ordinal '{ordv}' not understood")
        nf = kv.get("notfound", "error").lower()
        if nf in ("warning", "ignore"):
            base["default"] = "NOT_FOUND"
        for key in ("saveoffset", "savelen", "convert", "relframeid", "lb/bin", "rb/bin", "ignoreredirections"):
            if key in kv:
                notes.append(f"{key}={kv[key]} is not mapped")
        self.known_vars.add(name)
        self.pending_extractors.append(base)
        self.m.bump("extractors")
        if notes:
            self.score("correlation", PARTIAL, line, f"Correlation '{name}': " + "; ".join(notes) + ".")
        else:
            self.m.tally.add("correlation", OK)

    def h_web_reg_save_param(self, st: Stmt) -> None:
        name, static = self.value(st.args[0]) if st.args else (None, False)
        kv, _ = self.args_kv(st, 1)
        if not static:
            self.score("correlation", UNSUPPORTED, st.line, f"Dynamic correlation name in {st.text[:80]}.")
            return
        self._boundary_extractor(st, name, kv)

    def _boundary_extractor(self, st: Stmt, name: str, kv: Dict[str, str]) -> None:
        flags, lb, rb = "", None, None
        for k, v in kv.items():
            if k.startswith("lb"):
                lb = v
                flags = "(?i)" if "/ic" in k else flags
            elif k.startswith("rb"):
                rb = v
                flags = "(?i)" if "/ic" in k else flags
        if lb is None and rb is None:
            self.score("correlation", UNSUPPORTED, st.line, f"Correlation '{name}' has no LB/RB boundaries.")
            return
        rx = "(?s)" + flags + java_escape(lb or "") + "(.*?)" + (java_escape(rb) if rb else "$")
        if not lb or not rb:
            self.issue("REVIEW", st.line, "correlation", f"Correlation '{name}' has an empty "
                       f"{'LB' if not lb else 'RB'}; verify the generated regexp {rx}.")
        self._extractor(st, name, {"name": name, "regexp": rx}, kv, st.line)

    def h_web_reg_save_param_ex(self, st: Stmt) -> None:
        kv, _ = self.args_kv(st)
        name = kv.get("paramname")
        if not name:
            self.score("correlation", UNSUPPORTED, st.line, f"Missing ParamName in {st.text[:80]}.")
            return
        self._boundary_extractor(st, name, kv)

    def h_web_reg_save_param_regexp(self, st: Stmt) -> None:
        kv, _ = self.args_kv(st)
        name, rx = kv.get("paramname"), kv.get("regexp")
        if not (name and rx):
            self.score("correlation", UNSUPPORTED, st.line, f"Incomplete regexp correlation {st.text[:80]}.")
            return
        base = {"name": name, "regexp": rx}
        if kv.get("group", "1") not in ("1", ""):
            base["group"] = kv["group"]
            self.issue("REVIEW", st.line, "correlation", f"Correlation '{name}' uses Group={kv['group']}: verify "
                       "the NeoLoad extractor uses the same capture group.")
        self._extractor(st, name, base, kv, st.line)

    def h_web_reg_save_param_json(self, st: Stmt) -> None:
        kv, _ = self.args_kv(st)
        name, q = kv.get("paramname"), kv.get("querystring")
        if not (name and q):
            self.score("correlation", UNSUPPORTED, st.line, f"Incomplete JSON correlation {st.text[:80]}.")
            return
        if kv.get("selectall", "no").lower() == "yes":
            kv["ord"] = "all"
        self._extractor(st, name, {"name": name, "jsonpath": q}, kv, st.line)

    def h_web_reg_save_param_xpath(self, st: Stmt) -> None:
        kv, _ = self.args_kv(st)
        name, q = kv.get("paramname"), kv.get("querystring")
        if not (name and q):
            self.score("correlation", UNSUPPORTED, st.line, f"Incomplete XPath correlation {st.text[:80]}.")
            return
        if kv.get("selectall", "no").lower() == "yes":
            kv["ord"] = "all"
        self._extractor(st, name, {"name": name, "xpath": q}, kv, st.line)

    def h_web_reg_save_param_attrib(self, st: Stmt) -> None:
        self.score("correlation", UNSUPPORTED, st.line, f"{st.text[:80]}: HTML attribute correlation - rebuild with "
                   "a NeoLoad XPath/regexp extractor.")

    # checks
    def _assertion(self, kv: Dict[str, str], line: int) -> Optional[dict]:
        text, ic = None, False
        for k, v in kv.items():
            if k.startswith("text"):
                text, ic = v, "/ic" in k
        if text is None:
            self.score("check", UNSUPPORTED, line, "Text check without 'Text=' attribute.")
            return None
        fail_found = kv.get("fail", "notfound").lower() == "found"
        notes = []
        if ic:
            a = {"regexp": "(?i)" + java_escape(self.nl(text))}
            if fail_found:
                notes.append("case-insensitive 'Fail=Found' -> negate the regexp assertion in NeoLoad")
        else:
            a = {"not_contains" if fail_found else "contains": self.nl(text)}
        if kv.get("search", "body").lower().startswith("header"):
            notes.append("Search=Headers: set the assertion scope to response headers")
        if "savecount" in kv:
            notes.append(f"SaveCount={kv['savecount']} (match count) is not mapped")
        self.m.bump("assertions")
        if notes:
            self.score("check", PARTIAL, line, "; ".join(notes) + ".")
        else:
            self.m.tally.add("check", OK)
        return a

    def h_web_reg_find(self, st: Stmt) -> None:
        kv, _ = self.args_kv(st)
        a = self._assertion(kv, st.line)
        if a:
            self.pending_assertions.append(a)

    def h_web_global_verification(self, st: Stmt) -> None:
        kv, _ = self.args_kv(st)
        a = self._assertion(kv, st.line)
        if a:
            self.global_assertions.append(a)
            self.issue("INFO", st.line, "check", "Global verification is applied to every following request.")

    # requests
    def server_for(self, scheme: str, hostport: str, line: int) -> str:
        host, _, port = hostport.partition(":")
        p: Optional[int] = int(port) if port.isdigit() else None
        if p in (80, 443) and p == (443 if scheme == "https" else 80):
            p = None
        key = (scheme, self.nl(host), p)
        if key not in self.m.servers:
            base = re.sub(r"\W+", "_", host).strip("_") or "server"
            name = base
            taken = set(self.m.servers.values())
            if name in taken:
                name = f"{base}_{scheme}{p or ''}"
            self.m.servers[key] = name
            if PARAM_RX.search(host):
                self.issue("INFO", line, "server", f"Host '{host}' is parameterised; check the NeoLoad server definition.")
        return self.m.servers[key]

    def request(self, st: Stmt) -> None:
        fn = st.name
        if fn in ("web_link", "web_image"):
            self.score(fn, UNSUPPORTED, st.line, f"{fn}() follows a link/image from the previous page; record its "
                       "target URL and add it as a NeoLoad request (no URL in the source).")
            return
        step_name, _ = self.value(st.args[0]) if st.args else (None, False)
        attrs: Dict[str, str] = {}
        items: List[Dict[str, str]] = []
        extras: List[str] = []
        unknown, dynamic = [], []
        mode, cur_item = "attrs", {}
        for a in st.args[1:]:
            tok = a.strip()
            if tok == "LAST":
                break
            if tok in ("ITEMDATA", "EXTRARES"):
                mode = tok
                continue
            if tok == "ENDITEM":
                if cur_item and mode == "ITEMDATA":
                    items.append(cur_item)
                cur_item = {}
                continue
            v, static = self.value(a)
            if not static:
                dynamic.append(tok[:60])
                continue
            k, _, val = v.partition("=")
            key = k.strip().lower()
            if mode == "ITEMDATA":
                cur_item[key] = val
            elif mode == "EXTRARES":
                if key == "url":
                    extras.append(val)
            else:
                attrs[key] = val
        if cur_item and mode == "ITEMDATA":
            items.append(cur_item)

        url = attrs.get("url") or attrs.get("action")
        weight, notes = OK, []
        if fn == "web_submit_form":
            weight = PARTIAL
            notes.append("web_submit_form relies on the previous page's form; action URL and hidden fields must be verified")
        if not url:
            if fn != "web_submit_form":
                self.score(fn, UNSUPPORTED, st.line, f"{fn}('{step_name}') has no URL/Action.")
                return
            url = "/TODO_FORM_ACTION"
        if dynamic:
            weight = PARTIAL
            notes.append("dynamic argument(s) not converted: " + ", ".join(dynamic))
        method = attrs.get("method", "POST" if fn in ("web_submit_data", "web_submit_form") else "GET").upper()
        headers = dict(self.auto_headers)
        headers.update(self.next_headers)
        self.next_headers = {}
        if attrs.get("referer"):
            headers.setdefault("Referer", self.nl(attrs["referer"]))
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        body = None
        enctype = attrs.get("enctype")
        if "body" in attrs:
            body = self.nl(attrs["body"])
        elif "bodybinary" in attrs:
            body = self.nl(attrs["bodybinary"])
            weight = PARTIAL
            notes.append("BodyBinary escapes (\\x..) must be checked in NeoLoad")
        elif "bodyfilepath" in attrs:
            weight = PARTIAL
            notes.append(f"BodyFilePath={attrs['bodyfilepath']}: attach the file as the request body")
        if items:
            if any("file" in it or it.get("type", "").lower() == "file" for it in items):
                weight = PARTIAL
                notes.append("file upload field(s): configure a multipart body in NeoLoad")
            if (enctype or "").lower().startswith("multipart"):
                weight = PARTIAL
                notes.append("multipart/form-data form converted to a URL-encoded body; switch the NeoLoad body to multipart")
            body = "&".join(f"{_form_encode(self.nl(it.get('name', '')))}={_form_encode(self.nl(it.get('value', '')))}"
                            for it in items)
            enctype = enctype or "application/x-www-form-urlencoded"
        if enctype and body is not None and not any(h.lower() == "content-type" for h in headers):
            headers["Content-Type"] = enctype
        for k in attrs:
            if k not in IGNORED_ATTRS | {"url", "action", "method", "body", "bodybinary", "bodyfilepath", "enctype", "referer"}:
                unknown.append(k)
        if unknown:
            weight = min(weight, PARTIAL)
            notes.append("attribute(s) not mapped: " + ", ".join(sorted(unknown)))

        req = self._request_dict(step_name, url, method, headers, body, st.line)
        if req is None:
            return
        self.emit({"request": req})
        self.m.bump("requests")
        for extra in extras:
            er = self._request_dict(None, extra, "GET", dict(self.auto_headers), None, st.line, attach=False)
            if er:
                self.emit({"request": er})
                self.m.bump("requests")
        if extras:
            self.issue("INFO", st.line, fn, f"{len(extras)} EXTRARES resource(s) emitted as separate GET requests.")
        self.score(fn, weight, st.line, "; ".join(notes) + "." if notes else "")

    def _request_dict(self, name, url, method, headers, body, line, attach=True) -> Optional[dict]:
        url = self.nl(url)
        mm = re.match(r"^(https?)://([^/?#]+)(.*)$", url, re.I)
        if mm:
            server = self.server_for(mm.group(1).lower(), mm.group(2), line)
            path = mm.group(3) or "/"
        else:
            server = self.last_server
            path = url if url.startswith("/") else "/" + url
            if server is None:
                server = self.server_for("http", "TODO_HOST", line)
                self.issue("REVIEW", line, "server", f"Relative URL '{url}' with no previous host: set server TODO_HOST.")
        self.last_server = server
        req: dict = {}
        if name:
            req["name"] = self.nl(name)
        req["url"] = path
        req["server"] = server
        req["method"] = method
        if headers:
            req["headers"] = [{k: v} for k, v in headers.items()]
        if body is not None:
            req["body"] = body
        if attach:
            if self.pending_extractors:
                req["extractors"] = self.pending_extractors
                self.pending_extractors = []
            asserts = self.pending_assertions + list(self.global_assertions)
            if asserts:
                req["assertions"] = asserts
                self.pending_assertions = []
        return req

    # -- parameters, globals, helpers ------------------------------------
    def _map_params(self) -> None:
        sel = {"sequential": "sequential", "random": "random", "unique": "unique"}
        upd = {"eachiteration": "each_iteration", "each iteration": "each_iteration",
               "eachoccurrence": "each_use", "each occurrence": "each_use", "once": "each_vu"}
        oor = {"continuecyclic": "cycle", "continuewithlastvalue": "no_value", "abortvuser": "stop"}
        tables: Dict[str, dict] = {}
        self.file = "parameters (.prm)"
        for p in self.s.params.values():
            ptype = p.type.lower().replace(" ", "")
            props = {k.lower(): v for k, v in p.props.items()}
            if ptype in ("table", "file"):
                table = props.get("table") or props.get("filename") or (p.name + ".dat")
                src = os.path.join(self.s.path, table)
                stem = re.sub(r"\W+", "_", os.path.splitext(os.path.basename(table))[0])
                target = f"data/{stem}.csv"
                delim = props.get("delimiter", ",")
                delim = {"tab": "\t", "space": " "}.get(delim.lower(), delim)
                header = _header(src, delim)
                if header is None:
                    self.score("parameter", PARTIAL, 0, f"Data file '{table}' for parameter {p.name} not found; "
                               f"copy it to {target}.")
                    header = []
                elif (src, target) not in self.m.data_files:
                    self.m.data_files.append((src, target))
                column = props.get("columnname") or props.get("column") or p.name
                cm = re.fullmatch(r"col\s*(\d+)", column.strip(), re.I)
                if cm and header and int(cm.group(1)) <= len(header):
                    column = header[int(cm.group(1)) - 1]
                select = props.get("selectnextrow", "Sequential")
                upd_key = props.get("updatevalueonoccurrence", props.get("generatenewval", "EachIteration")).lower()
                settings = {"order": sel.get(select.lower(), "sequential"),
                            "change_policy": upd.get(upd_key, "each_iteration"),
                            "scope": "unique" if select.lower() == "unique" else "global",
                            "out_of_value": oor.get(props.get("outofrangepolicy", "ContinueCyclic").lower(), "cycle")}
                if target not in tables:
                    var = {"name": stem, "path": target, "delimiter": delim, "is_first_line_column_names": True}
                    if header:
                        var["column_names"] = header
                    var.update(settings)
                    tables[target] = {"var": var, "params": []}
                    self.m.variables.append({"file": var})
                entry = tables[target]
                entry["params"].append(p.name)
                self.refmap[p.name] = f"{stem}.{column}"
                if header and column not in header:
                    self.score("parameter", PARTIAL, 0, f"Column '{column}' of {p.name} not in {table} header {header}.")
                elif not select.lower().startswith("same line") and any(
                        entry["var"][k] != v for k, v in settings.items()):
                    self.score("parameter", PARTIAL, 0, f"{p.name} shares {table} with different selection/update "
                               f"settings ({settings}); NeoLoad uses one policy per file variable.")
                else:
                    self.m.tally.add("parameter", OK)
                if settings["out_of_value"] == "no_value":
                    self.issue("REVIEW", 0, "parameter", f"{p.name}: 'continue with last value' has no exact NeoLoad "
                               "equivalent; check the out-of-values policy.")
            elif ptype in ("uniquenumber", "iterationnumber", "vuserid"):
                start = int(_num(props.get("startvalue") or props.get("start")) or 1)
                self.m.variables.append({"counter": {"name": p.name, "start": start, "end": 2147483647, "increment": 1}})
                weight = OK if ptype == "uniquenumber" else PARTIAL
                self.score("parameter", weight, 0, "" if weight == OK else f"{p.type} parameter {p.name} approximated "
                           "with a counter; NeoLoad has built-in ${NL-VirtualUserId}/${NL-CurrentIteration} variables.")
            elif ptype == "randomnumber":
                lo = int(_num(props.get("min")) or 0)
                hi = int(_num(props.get("max")) or 100)
                self.m.variables.append({"random_number": {"name": p.name, "min": lo, "max": hi}})
                self.score("parameter", OK, 0, f"Random number {p.name} [{lo}..{hi}].", sev="INFO")
            else:
                self.score("parameter", UNSUPPORTED, 0, f"Parameter {p.name} of type '{p.type}' needs a NeoLoad "
                           "JavaScript or built-in variable (e.g. date/time format, group name, custom DLL).")
        for target, entry in tables.items():
            if len(entry["params"]) > 1:
                self.issue("INFO", 0, "parameter", f"{', '.join(entry['params'])} read the same row of {target} "
                           f"(NeoLoad file variable '{entry['var']['name']}').")

    def _map_globals(self) -> None:
        for fname, stmts in self.s.files.items():
            self.file = fname
            for st in stmts:
                if st.kind == "decl" or st.kind == "expr" and st.text:
                    js, left = c_to_js(st.text + ";")
                    self.m.js_chunks.append(js.strip() + f"  // {fname}:{st.line}\n")
                    self.score("global", TRANSLATED if not left else PARTIAL, st.line,
                               "Global declaration moved to custom_js." + (" Not translated: " + "; ".join(left) if left else ""))
                elif st.kind == "pre":
                    self.preproc(st)

    def _map_helpers(self, funcs: Dict[str, Stmt]) -> None:
        for name in sorted(self.helper_names):
            fn = funcs[name]
            self.file = fn.src_file
            js, left = function_to_js(name, fn.params, getattr(fn, "raw_body", ""))
            self.m.js_chunks.append(f"// {fn.src_file}:{fn.line}  {fn.text.strip()}\n{js}")
            self.score("custom-function", TRANSLATED if not left else PARTIAL, fn.line,
                       f"C function {name}() translated to JavaScript (custom_js)." +
                       (" Not translated: " + "; ".join(left) if left else " Verify the translation."))
        self.m.js_chunks.extend(self.js_logic)

    def _apply_pacing(self) -> None:
        rt = self.s.runtime
        if rt.pacing_seconds is None:
            return
        self.file = "default.cfg"
        self.cur = self.m.sections["actions"]
        self.comment(f"[LR pacing {rt.pacing_mode} {rt.pacing_seconds:g}s] approximated by an end-of-iteration delay")
        self.emit({"delay": _secs(rt.pacing_seconds)})
        if rt.pacing_mode == "after_previous":
            self.score("pacing", OK, 0, f"Pacing 'after previous iteration ends' {rt.pacing_seconds:g}s -> delay.", sev="INFO")
        else:
            self.score("pacing", PARTIAL, 0, f"Pacing '{rt.pacing_mode}' {rt.pacing_seconds:g}s"
                       + (f"-{rt.pacing_max_seconds:g}s" if rt.pacing_max_seconds else "") +
                       " approximated by a fixed delay; configure NeoLoad pacing on the user path for start-to-start timing.")


def _loop_count(cond: str) -> Optional[int]:
    """Iterations of `i = A; i < / <= B; i++` loops with literal bounds."""
    mm = re.fullmatch(r"\s*(?:int\s+)?(\w+)\s*=\s*(\d+)\s*;\s*\1\s*(<=?)\s*(\d+)\s*;\s*(?:\1\s*\+\+|\+\+\s*\1|\1\s*\+=\s*1)\s*", cond)
    if not mm:
        return None
    n = int(mm.group(4)) - int(mm.group(2)) + (1 if mm.group(3) == "<=" else 0)
    return max(n, 0)


def _header(path: str, delim: str) -> Optional[List[str]]:
    if not os.path.isfile(path):
        return None
    from .lrproject import read_text
    first = (read_text(path).splitlines() or [""])[0]
    return [c.strip() for c in first.split(delim)] if first.strip() else []


def _secs(v: float) -> str:
    return f"{int(v)}s" if float(v).is_integer() else f"{int(round(v * 1000))}ms"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def java_escape(text: str) -> str:
    out = []
    for ch in text:
        if ch in "\\.[]{}()*+-?^$|/":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def _form_encode(text: str) -> str:
    """URL-encode a form value but keep ${var} references intact."""
    parts = re.split(r"(\$\{[^}]+\})", text)
    return "".join(p if p.startswith("${") else quote_plus(p, safe="") for p in parts)


def _source_of(raw: str, st: Stmt) -> str:
    """Original C text of a control statement (from its first line to the end of its block)."""
    lines = raw.splitlines()
    start = st.line - 1
    depth, seen, out = 0, False, []
    for ln in lines[start:]:
        out.append(ln)
        clean = re.sub(r'"(?:\\.|[^"\\])*"', '""', ln)
        depth += clean.count("{") - clean.count("}")
        seen = seen or "{" in clean
        if (seen and depth <= 0) or (not seen and ";" in clean):
            nxt = lines[start + len(out)] if start + len(out) < len(lines) else ""
            if re.match(r"\s*(else|while)\b", nxt):
                continue
            break
    return "\n".join(out)


def map_script(script: LrScript) -> ScriptModel:
    return Mapper(script).run()
