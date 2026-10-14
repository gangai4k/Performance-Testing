"""Minimal, dependency-free YAML writer.

Scalars are written as JSON strings (valid YAML double-quoted scalars), which
avoids any escaping ambiguity. Two marker keys are understood inside lists:
``{"__comment__": text}`` -> ``# text`` and ``{"__commented__": [items]}`` ->
the items rendered as YAML and commented out.
"""
from __future__ import annotations

import json
import re
from typing import Any, List

_PLAIN_KEY = re.compile(r"^[A-Za-z_][\w\-]*$")


def _scalar(v: Any) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v), ensure_ascii=False)


def _key(k: str) -> str:
    return k if _PLAIN_KEY.match(k) else json.dumps(k, ensure_ascii=False)


def _is_marker(item: Any) -> bool:
    return isinstance(item, dict) and len(item) == 1 and next(iter(item)) in ("__comment__", "__commented__")


def _emit(obj: Any, indent: int, out: List[str]) -> None:
    pad = " " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{_key(k)}:")
                _emit(v, indent + 2, out)
            elif isinstance(v, (dict, list)):
                out.append(f"{pad}{_key(k)}: {'{}' if isinstance(v, dict) else '[]'}")
            else:
                out.append(f"{pad}{_key(k)}: {_scalar(v)}")
    elif isinstance(obj, list):
        for item in obj:
            if _is_marker(item):
                kind, val = next(iter(item.items()))
                if kind == "__comment__":
                    for ln in str(val).splitlines() or [""]:
                        out.append(f"{pad}# {ln}")
                else:
                    sub: List[str] = []
                    _emit(val, indent, sub)
                    out.extend(f"{pad}# {ln[indent:]}" if ln.startswith(pad) else f"{pad}# {ln}" for ln in sub)
                continue
            if isinstance(item, (dict, list)) and item:
                sub = []
                _emit(item, indent + 2, sub)
                first = sub[0]
                if first.lstrip().startswith("#"):
                    out.append(f"{pad}-")
                    out.extend(sub)
                else:
                    out.append(f"{pad}- {first[indent + 2:]}")
                    out.extend(sub[1:])
            else:
                out.append(f"{pad}- {_scalar(item) if not isinstance(item, (dict, list)) else '{}'}")
    else:
        out.append(pad + _scalar(obj))


def dump(obj: Any, header: str = "") -> str:
    out: List[str] = [f"# {ln}" for ln in header.splitlines()] if header else []
    _emit(obj, 0, out)
    return "\n".join(out) + "\n"
