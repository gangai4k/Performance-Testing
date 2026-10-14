"""Command line entry point: `python -m lr2nl convert ...` or `python -m lr2nl ui`."""
from __future__ import annotations

import argparse
import sys

from . import __version__


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lr2nl", description="Convert LoadRunner HTTP/HTML scripts to NeoLoad as-code projects.")
    ap.add_argument("--version", action="version", version=f"lr2nl {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("convert", help="convert a script folder or a folder of scripts")
    c.add_argument("-s", "--source", required=True, help="LoadRunner script folder, or a folder containing script folders")
    c.add_argument("-o", "--output", required=True, help="output folder for NeoLoad projects and reports")
    c.add_argument("--users", type=int, default=1, help="virtual users in the generated scenario (default 1)")
    c.add_argument("--duration", default="5m", help="scenario duration, e.g. 5m, 1h (default 5m)")
    c.add_argument("--workers", type=int, default=4, help="parallel conversions (default 4)")
    c.add_argument("--fail-under", type=float, default=None,
                   help="exit code 2 if any script is FAILED or below this success percentage")
    sub.add_parser("ui", help="open the desktop UI (default when no command is given)")
    args = ap.parse_args(argv)

    if args.cmd in (None, "ui"):
        from .ui import run_ui
        run_ui()
        return 0

    from .converter import convert_batch
    results = convert_batch(args.source, args.output, args.users, args.duration, args.workers, log=print)
    if not results:
        return 1
    ok = {s: sum(1 for r in results if r.status == s) for s in ("SUCCESS", "PARTIAL", "FAILED")}
    print(f"Done: {len(results)} script(s) - {ok['SUCCESS']} success, {ok['PARTIAL']} partial, {ok['FAILED']} failed")
    if args.fail_under is not None and any(r.status == "FAILED" or r.pct < args.fail_under for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
