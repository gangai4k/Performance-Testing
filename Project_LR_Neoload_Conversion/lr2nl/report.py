"""CSV / HTML / JSON reporting of a conversion batch."""
from __future__ import annotations

import csv
import html
import json
import os
from dataclasses import asdict
from datetime import datetime
from typing import List

from . import __version__
from .model import ScriptResult

STAT_KEYS = ("requests", "transactions", "extractors", "assertions", "think_times")
COLORS = {"SUCCESS": "#1e7d32", "PARTIAL": "#b26a00", "FAILED": "#b71c1c"}


def write_reports(results: List[ScriptResult], out_dir: str) -> List[str]:
    rdir = os.path.join(out_dir, "reports")
    os.makedirs(rdir, exist_ok=True)
    paths = [os.path.join(rdir, n) for n in
             ("conversion_summary.csv", "manual_review.csv", "conversion_report.html", "conversion_summary.json")]

    with open(paths[0], "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Script", "Status", "SuccessPct", "Constructs", "ManualReviewItems",
                    *[k.title().replace("_", "") for k in STAT_KEYS], "Output", "Error"])
        for r in results:
            w.writerow([r.name, r.status, f"{r.pct:.1f}", r.constructs, r.review_items,
                        *[r.stats.get(k, 0) for k in STAT_KEYS], ";".join(r.outputs[:1]), r.error])

    with open(paths[1], "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Script", "Severity", "File", "Line", "Construct", "Message"])
        for r in results:
            for i in r.issues:
                w.writerow([r.name, i.severity, i.file, i.line or "", i.construct, i.message])

    with open(paths[2], "w", encoding="utf-8") as fh:
        fh.write(_html(results))

    with open(paths[3], "w", encoding="utf-8") as fh:
        json.dump({"generated": datetime.now().isoformat(timespec="seconds"), "tool": f"lr2nl {__version__}",
                   "results": [asdict(r) for r in results]}, fh, indent=2)
    return paths


def _html(results: List[ScriptResult]) -> str:
    e = html.escape
    total = len(results)
    counts = {s: sum(1 for r in results if r.status == s) for s in COLORS}
    avg = sum(r.pct for r in results) / total if total else 0.0
    rows, details = [], []
    for r in results:
        color = COLORS.get(r.status, "#333")
        rows.append(
            f"<tr><td><a href='#s-{e(r.name)}'>{e(r.name)}</a></td>"
            f"<td><span class='badge' style='background:{color}'>{r.status}</span></td>"
            f"<td class='num'>{r.pct:.1f}%<div class='bar'><div style='width:{r.pct:.0f}%;background:{color}'></div></div></td>"
            f"<td class='num'>{r.constructs}</td><td class='num'>{r.review_items}</td>"
            + "".join(f"<td class='num'>{r.stats.get(k, 0)}</td>" for k in STAT_KEYS) + "</tr>")
        items = "".join(
            f"<tr class='{i.severity.lower()}'><td>{i.severity}</td><td>{e(i.file)}</td><td class='num'>{i.line or ''}</td>"
            f"<td>{e(i.construct)}</td><td>{e(i.message)}</td></tr>" for i in r.issues)
        details.append(
            f"<details id='s-{e(r.name)}'{' open' if r.status != 'SUCCESS' else ''}><summary><b>{e(r.name)}</b> - "
            f"{r.status} {r.pct:.1f}% - {r.review_items} item(s) to review</summary>"
            f"<p>Source: <code>{e(r.source)}</code>{'<br>Error: ' + e(r.error) if r.error else ''}</p>"
            + (f"<table><tr><th>Severity</th><th>File</th><th>Line</th><th>Construct</th><th>Message</th></tr>{items}</table>"
               if items else "<p>No issues.</p>") + "</details>")
    head = "".join(f"<th>{k.replace('_', ' ').title()}</th>" for k in STAT_KEYS)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>LoadRunner to NeoLoad conversion report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}} h1{{font-size:22px}}
table{{border-collapse:collapse;width:100%;margin:8px 0 16px}} th,td{{border:1px solid #ddd;padding:6px 8px;font-size:13px;vertical-align:top}}
th{{background:#f3f4f6;text-align:left}} .num{{text-align:right;white-space:nowrap}}
.badge{{color:#fff;border-radius:4px;padding:2px 8px;font-size:12px}} .bar{{background:#eee;height:4px;margin-top:3px}} .bar div{{height:4px}}
.cards{{display:flex;gap:12px;margin:12px 0}} .card{{border:1px solid #ddd;border-radius:6px;padding:10px 16px;min-width:120px}}
.card b{{font-size:22px;display:block}} tr.review td:first-child{{color:#b26a00;font-weight:600}} tr.info td:first-child{{color:#555}}
details{{margin:6px 0;border:1px solid #eee;border-radius:6px;padding:6px 10px}}
</style></head><body>
<h1>LoadRunner to NeoLoad conversion report</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M} by lr2nl {__version__}</p>
<div class="cards"><div class="card"><b>{total}</b>scripts</div>
<div class="card"><b style="color:{COLORS['SUCCESS']}">{counts['SUCCESS']}</b>success</div>
<div class="card"><b style="color:{COLORS['PARTIAL']}">{counts['PARTIAL']}</b>partial</div>
<div class="card"><b style="color:{COLORS['FAILED']}">{counts['FAILED']}</b>failed</div>
<div class="card"><b>{avg:.1f}%</b>average match</div></div>
<table><tr><th>Script</th><th>Status</th><th>Success %</th><th>Constructs</th><th>Review items</th>{head}</tr>
{''.join(rows)}</table>
<h2>Details</h2>{''.join(details)}
</body></html>"""
