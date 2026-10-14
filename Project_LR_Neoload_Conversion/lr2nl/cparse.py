"""Lightweight parser for LoadRunner C scripts.

It does not try to be a full C compiler front-end. It understands what
LoadRunner HTTP/HTML scripts actually contain: function definitions,
API calls with string-literal arguments, declarations, preprocessor lines
and the control-flow statements if/else, for, while, do/while and switch.
Anything it cannot classify is kept as an ``expr`` statement so that the
mapper can flag it instead of dropping it.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


class ParseError(Exception):
    def __init__(self, message: str, line: int = 0):
        super().__init__(f"line {line}: {message}" if line else message)
        self.line = line


@dataclass
class Stmt:
    kind: str                 # call | assign_call | decl | expr | if | for | while | do | switch | label | block | func | pre
    line: int
    text: str = ""
    name: str = ""            # called function / defined function
    args: List[str] = field(default_factory=list)
    lhs: str = ""
    cond: str = ""
    params: str = ""
    body: List["Stmt"] = field(default_factory=list)
    orelse: List["Stmt"] = field(default_factory=list)
    src_file: str = ""


CONTROL_WORDS = {"if", "for", "while", "switch", "do"}
TYPE_WORDS = ("int", "char", "long", "short", "float", "double", "unsigned", "signed",
              "static", "const", "void", "size_t", "struct", "extern", "typedef", "bool")
_IDENT = re.compile(r"[A-Za-z_]\w*")
_FUNC_HEAD = re.compile(r"^(?:[A-Za-z_][\w\s\*]*?[\s\*])?([A-Za-z_]\w*)\s*\((.*)\)\s*$", re.S)
_DECL = re.compile(r"^(?:%s)\b" % "|".join(TYPE_WORDS))
_STRING_SEQ = re.compile(r'^(?:\s*"(?:\\.|[^"\\])*")+\s*$', re.S)
_STRING_PART = re.compile(r'"((?:\\.|[^"\\])*)"', re.S)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0"}


def strip_comments(src: str) -> str:
    """Blank out comments while keeping offsets and line numbers intact."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            i = _skip_quoted(src, i)
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _skip_quoted(src: str, i: int) -> int:
    """Return index just after the string/char literal starting at i."""
    q = src[i]
    i += 1
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == q:
            return i + 1
        if c == "\n" and q == "'":
            return i
        i += 1
    return n


def split_args(text: str) -> List[str]:
    """Split a C argument list on top-level commas."""
    args, depth, start, i, n = [], 0, 0, 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            i = _skip_quoted(text, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            args.append(text[start:i].strip())
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail or args:
        args.append(tail)
    return args


def decode_c_string(body: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), "\\" + m.group(1)), body, flags=re.S)


def literal_value(arg: str) -> Optional[str]:
    """Value of an argument made only of (adjacent) string literals, else None."""
    if not _STRING_SEQ.match(arg):
        return None
    return "".join(decode_c_string(p) for p in _STRING_PART.findall(arg))


class _Parser:
    def __init__(self, src: str, filename: str):
        self.raw = src
        self.src = strip_comments(src)
        self.file = filename
        self.n = len(self.src)
        self._starts = [0] + [m.end() for m in re.finditer(r"\n", self.src)]

    def line_of(self, pos: int) -> int:
        return bisect.bisect_right(self._starts, pos)

    def skip_ws(self, pos: int, end: int) -> int:
        while pos < end and self.src[pos].isspace():
            pos += 1
        return pos

    def match(self, pos: int, open_c: str, close_c: str) -> int:
        """pos points at open_c; returns index of the matching close_c."""
        depth, i = 0, pos
        while i < self.n:
            c = self.src[i]
            if c in "\"'":
                i = _skip_quoted(self.src, i)
                continue
            if c == open_c:
                depth += 1
            elif c == close_c:
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        raise ParseError(f"unbalanced '{open_c}'", self.line_of(pos))

    def word_at(self, pos: int) -> str:
        m = _IDENT.match(self.src, pos)
        return m.group(0) if m else ""

    # -- statements ------------------------------------------------------
    def parse_stmts(self, pos: int, end: int) -> List[Stmt]:
        out: List[Stmt] = []
        while True:
            pos = self.skip_ws(pos, end)
            if pos >= end:
                return out
            stmt, pos = self.parse_one(pos, end)
            if stmt is not None:
                out.append(stmt)

    def parse_one(self, pos: int, end: int) -> Tuple[Optional[Stmt], int]:
        src = self.src
        line = self.line_of(pos)
        c = src[pos]
        if c == ";":
            return None, pos + 1
        if c == "#":
            j = pos
            while True:
                k = src.find("\n", j)
                k = end if k < 0 or k > end else k
                if src[pos:k].rstrip().endswith("\\") and k < end:
                    j = k + 1
                    continue
                return Stmt("pre", line, src[pos:k].strip(), src_file=self.file), k
        if c == "{":
            close = self.match(pos, "{", "}")
            return Stmt("block", line, body=self.parse_stmts(pos + 1, close), src_file=self.file), close + 1
        if c == "}":
            raise ParseError("unexpected '}'", line)
        word = self.word_at(pos)
        if word in ("if", "while", "for", "switch"):
            p = self.skip_ws(pos + len(word), end)
            if p >= end or src[p] != "(":
                raise ParseError(f"expected '(' after {word}", line)
            close = self.match(p, "(", ")")
            cond = src[p + 1:close].strip()
            body, nxt = self.parse_body(close + 1, end)
            st = Stmt(word, line, text=f"{word} ({cond})", cond=cond, body=body, src_file=self.file)
            if word == "if":
                q = self.skip_ws(nxt, end)
                if self.word_at(q) == "else":
                    st.orelse, nxt = self.parse_body(q + 4, end)
            return st, nxt
        if word == "do":
            body, nxt = self.parse_body(pos + 2, end)
            q = self.skip_ws(nxt, end)
            if self.word_at(q) != "while":
                raise ParseError("expected 'while' after do-block", self.line_of(q))
            p = self.skip_ws(q + 5, end)
            close = self.match(p, "(", ")")
            semi = self.skip_ws(close + 1, end)
            if semi < end and src[semi] == ";":
                semi += 1
            cond = src[p + 1:close].strip()
            return Stmt("do", line, text=f"do-while ({cond})", cond=cond, body=body, src_file=self.file), semi
        if word in ("case", "default"):
            j = pos
            while j < end and src[j] != ":":
                if src[j] in "\"'":
                    j = _skip_quoted(src, j)
                    continue
                j += 1
            return Stmt("label", line, src[pos:j].strip(), src_file=self.file), j + 1
        return self.parse_simple(pos, end)

    def parse_body(self, pos: int, end: int) -> Tuple[List[Stmt], int]:
        pos = self.skip_ws(pos, end)
        if pos < end and self.src[pos] == "{":
            close = self.match(pos, "{", "}")
            return self.parse_stmts(pos + 1, close), close + 1
        stmt, nxt = self.parse_one(pos, end)
        return ([stmt] if stmt else []), nxt

    def parse_simple(self, pos: int, end: int) -> Tuple[Stmt, int]:
        src, line = self.src, self.line_of(pos)
        paren = bracket = brace = 0
        i = pos
        while i < end:
            c = src[i]
            if c in "\"'":
                i = _skip_quoted(src, i)
                continue
            if c == "(":
                paren += 1
            elif c == ")":
                paren -= 1
            elif c == "[":
                bracket += 1
            elif c == "]":
                bracket -= 1
            elif c == "{":
                head = src[pos:i].strip()
                if paren == 0 and bracket == 0 and brace == 0 and "=" not in head:
                    close = self.match(i, "{", "}")
                    m = _FUNC_HEAD.match(head)
                    if not m:
                        raise ParseError(f"cannot parse block header '{head[:60]}'", line)
                    st = Stmt("func", line, text=head, name=m.group(1), params=m.group(2).strip(),
                              body=self.parse_stmts(i + 1, close), src_file=self.file)
                    st.raw_body = self.raw[i + 1:close]  # type: ignore[attr-defined]
                    return st, close + 1
                brace += 1
            elif c == "}":
                brace -= 1
            elif c == ";" and paren == 0 and brace == 0:
                return classify(src[pos:i].strip(), line, self.file), i + 1
            i += 1
        text = src[pos:end].strip()
        if text:
            raise ParseError(f"missing ';' after '{text[:60]}'", line)
        return Stmt("expr", line, "", src_file=self.file), end


def _call_parts(text: str, start: int) -> Optional[Tuple[str, List[str]]]:
    """If text[start:] is exactly `name(args)`, return (name, args)."""
    m = _IDENT.match(text, start)
    if not m:
        return None
    p = m.end()
    while p < len(text) and text[p].isspace():
        p += 1
    if p >= len(text) or text[p] != "(":
        return None
    depth, i = 0, p
    while i < len(text):
        c = text[i]
        if c in "\"'":
            i = _skip_quoted(text, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if text[i + 1:].strip():
        return None
    return m.group(0), split_args(text[p + 1:i])


def classify(text: str, line: int, filename: str) -> Stmt:
    if not text:
        return Stmt("expr", line, "", src_file=filename)
    parts = _call_parts(text, 0)
    if parts and parts[0] not in CONTROL_WORDS and parts[0] != "return":
        return Stmt("call", line, text, name=parts[0], args=parts[1], src_file=filename)
    m = re.match(r"^(.*?[^=!<>+\-*/%&|^])=(?!=)\s*", text, re.S)
    if m and not text.startswith(("return", "==")):
        parts = _call_parts(text, m.end())
        if parts:
            return Stmt("assign_call", line, text, name=parts[0], args=parts[1],
                        lhs=m.group(1).strip(), src_file=filename)
    if _DECL.match(text):
        return Stmt("decl", line, text, src_file=filename)
    return Stmt("expr", line, text, src_file=filename)


def parse_c(src: str, filename: str = "") -> List[Stmt]:
    """Parse a C source file into top-level statements (func, decl, pre, ...)."""
    p = _Parser(src, filename)
    return p.parse_stmts(0, p.n)
