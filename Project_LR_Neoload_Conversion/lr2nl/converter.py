"""Batch orchestration: discover scripts, convert each one, write reports."""
from __future__ import annotations

import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional

from .generator import write_neoload_commands, write_project
from .lrproject import is_script_dir, load_script
from .mapper import map_script
from .model import FAILED, Issue, ScriptResult, decide_status
from .report import write_reports

LogFn = Callable[[str], None]
ResultFn = Callable[[ScriptResult], None]


def discover_scripts(source: str) -> List[str]:
    """A folder that is a script, or every script folder below it (sorted)."""
    source = os.path.abspath(source)
    if is_script_dir(source):
        return [source]
    found = []
    for root, dirs, _files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in ("data", "result1", "results"))
        if root != source and is_script_dir(root):
            found.append(root)
            dirs[:] = []  # a script folder is never nested in another one
    return sorted(found, key=str.lower)


def convert_script(path: str, out_dir: str, users: int = 1, duration: str = "5m") -> ScriptResult:
    name = os.path.basename(os.path.normpath(path))
    try:
        script = load_script(path)
        model = map_script(script)
        fatal = bool(script.parse_errors) and not script.files
        outputs = write_project(model, out_dir, path, users, duration)
        status = decide_status(model.tally, model.issues, fatal)
        return ScriptResult(name, path, status, model.tally.pct, model.tally.total,
                            sum(1 for i in model.issues if i.severity == "REVIEW"),
                            dict(model.stats), model.issues, outputs,
                            error="; ".join(script.parse_errors))
    except Exception as exc:  # one broken script must not stop the batch
        return ScriptResult(name, path, FAILED, 0.0, 0, 1, {},
                            [Issue("REVIEW", "", 0, "converter", f"Conversion crashed: {exc}")], [],
                            error=traceback.format_exc(limit=3))


def convert_batch(source: str, out_dir: str, users: int = 1, duration: str = "5m", workers: int = 4,
                  log: Optional[LogFn] = None, on_result: Optional[ResultFn] = None) -> List[ScriptResult]:
    log = log or (lambda _m: None)
    scripts = discover_scripts(source)
    os.makedirs(out_dir, exist_ok=True)
    log(f"Found {len(scripts)} LoadRunner script(s) under {source}")
    if not scripts:
        log("Nothing to convert: a script folder must contain Action.c, vuser_init.c or a .usr file.")
        return []
    results: List[ScriptResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(convert_script, p, out_dir, users, duration) for p in scripts]
        for idx, fut in enumerate(futures, 1):
            r = fut.result()
            results.append(r)
            log(f"[{idx}/{len(scripts)}] {r.name}: {r.status} {r.pct:.1f}% ({r.review_items} to review)")
            if on_result:
                on_result(r)
    yamls = [r.outputs[0] for r in results if r.outputs]
    write_neoload_commands(out_dir, yamls)
    for p in write_reports(results, out_dir):
        log(f"Report: {p}")
    return results
