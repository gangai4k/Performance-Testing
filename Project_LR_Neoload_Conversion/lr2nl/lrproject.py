"""Loading of a LoadRunner script folder: C sources, parameters (.prm) and run-time settings."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .cparse import Stmt, parse_c

STANDARD_INCLUDES = {"lrun.h", "web_api.h", "lrw_custom_body.h", "as_web.h"}


def read_text(path: str) -> str:
    with open(path, "rb") as fh:
        data = fh.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def read_ini(path: str) -> Dict[str, Dict[str, str]]:
    """Tolerant INI reader (LoadRunner files have duplicate keys and odd quoting)."""
    sections: Dict[str, Dict[str, str]] = {}
    cur = sections.setdefault("", {})
    for raw in read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = sections.setdefault(line[1:-1].strip(), {})
            continue
        key, sep, val = line.partition("=")
        if sep:
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] == '"':
                val = val[1:-1]
            cur[key.strip()] = val
    return sections


@dataclass
class ParamDef:
    name: str
    type: str
    props: Dict[str, str]


@dataclass
class RuntimeSettings:
    think_mode: str = "as_recorded"     # as_recorded | ignore | multiply | random | limit
    think_factor: float = 1.0
    think_min_pct: float = 100.0
    think_max_pct: float = 100.0
    think_limit: Optional[float] = None
    pacing_mode: str = "none"           # none | after_previous | fixed | random
    pacing_seconds: Optional[float] = None
    pacing_max_seconds: Optional[float] = None
    action_order: List[str] = field(default_factory=list)
    iterations: Optional[int] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class LrScript:
    name: str
    path: str
    files: Dict[str, List[Stmt]] = field(default_factory=dict)   # file name -> top-level stmts
    raw: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, ParamDef] = field(default_factory=dict)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    parse_errors: List[str] = field(default_factory=list)


def is_script_dir(path: str) -> bool:
    try:
        names = {n.lower() for n in os.listdir(path)}
    except OSError:
        return False
    return "action.c" in names or "vuser_init.c" in names or any(n.endswith(".usr") for n in names)


def _num(val: Optional[str]) -> Optional[float]:
    try:
        return float(str(val).strip()) if val not in (None, "") else None
    except ValueError:
        return None


def _find(ini: Dict[str, Dict[str, str]], *keys: str) -> Optional[str]:
    wanted = {k.lower() for k in keys}
    for sec in ini.values():
        for k, v in sec.items():
            if k.lower() in wanted:
                return v
    return None


def load_runtime(path: str) -> RuntimeSettings:
    rt = RuntimeSettings()
    ini: Dict[str, Dict[str, str]] = {}
    for fname in ("default.cfg", "default.usp"):
        fpath = os.path.join(path, fname)
        if os.path.isfile(fpath):
            for sec, vals in read_ini(fpath).items():
                ini.setdefault(sec, {}).update(vals)
    if not ini:
        rt.notes.append("No default.cfg/default.usp found: LoadRunner defaults assumed (think time as recorded, no pacing).")
        return rt

    think_sec = {k.lower(): v for k, v in ini.get("ThinkTime", {}).items()}
    think = (think_sec.get("options") or "RECORDED").upper()
    if "NOTHINK" in think or "IGNORE" in think:
        rt.think_mode = "ignore"
    elif "MULTIPLY" in think:
        rt.think_mode = "multiply"
        rt.think_factor = _num(think_sec.get("factor")) or 1.0
    elif "RANDOM" in think:
        rt.think_mode = "random"
        rt.think_min_pct = _num(think_sec.get("randomlow") or think_sec.get("minpercentage")) or 50.0
        rt.think_max_pct = _num(think_sec.get("randomhigh") or think_sec.get("maxpercentage")) or 150.0
    limit = _num(think_sec.get("limit"))
    if rt.think_mode != "ignore" and str(think_sec.get("limitflag", "0")).strip() == "1" and limit:
        rt.think_limit = limit
        if rt.think_mode == "as_recorded":
            rt.think_mode = "limit"

    it = {k.lower(): v for k, v in ini.get("Iterations", {}).items()}
    rt.iterations = int(_num(it.get("numofiterations")) or 0) or None
    pace = (it.get("iterationpace") or "IterationASAP").lower()
    if "random" in pace:
        rt.pacing_mode = "random"
        rt.pacing_seconds = _num(it.get("randommin"))
        rt.pacing_max_seconds = _num(it.get("randommax"))
    elif "after" in pace or "delay" in pace:
        rt.pacing_mode = "after_previous"
        rt.pacing_seconds = _num(it.get("delayafter") or it.get("startevery"))
    elif "asap" not in pace:
        rt.pacing_mode = "fixed"
        rt.pacing_seconds = _num(it.get("startevery"))

    order = ini.get("RunLogicActionOrder", {}).get("Name") or _find(ini, "RunLogicActionOrder")
    if order:
        rt.action_order = [a.strip() for a in re.split(r"[,;]", order) if a.strip()]
    rt.notes.append("Run-time settings read from default.cfg/default.usp (think-time mode: %s, pacing: %s)."
                    % (rt.think_mode, rt.pacing_mode if rt.pacing_seconds is None else f"{rt.pacing_mode} {rt.pacing_seconds:g}s"))
    return rt


def load_params(path: str) -> Dict[str, ParamDef]:
    params: Dict[str, ParamDef] = {}
    for fname in sorted(os.listdir(path)):
        if not fname.lower().endswith(".prm"):
            continue
        for sec, vals in read_ini(os.path.join(path, fname)).items():
            if not sec.lower().startswith("parameter:"):
                continue
            name = sec.split(":", 1)[1].strip()
            params[name] = ParamDef(name, vals.get("Type", "Table"), vals)
    return params


def load_script(path: str) -> LrScript:
    script = LrScript(name=os.path.basename(os.path.normpath(path)), path=path)
    for fname in sorted(os.listdir(path)):
        low = fname.lower()
        if not (low.endswith(".c") or low.endswith(".h")) or low in STANDARD_INCLUDES or low.startswith("pre_cci"):
            continue
        text = read_text(os.path.join(path, fname))
        script.raw[fname] = text
        try:
            script.files[fname] = parse_c(text, fname)
        except Exception as exc:  # parse errors are reported, not raised
            script.parse_errors.append(f"{fname}: {exc}")
    script.params = load_params(path)
    script.runtime = load_runtime(path)
    return script
