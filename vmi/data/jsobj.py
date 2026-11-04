"""Convert JavaScript object literals (as embedded by SvelteKit / Next pages) into Python objects.

Handles: unquoted keys, single/double-quoted strings, `void 0`/`undefined` → None, `!0`/`!1` → bool,
numbers like `.5`, `-.5`, `1e9`, trailing commas. Tokenizer-based (no regex hacks), so it is safe on
strings that contain colons/commas/braces.
"""
from __future__ import annotations

import json
import re

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def to_json(src: str) -> str:
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            j = i + 1
            buf = []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            s = "".join(buf)
            if c == "'":
                s = s.replace('\\\'', "'").replace('"', '\\"')
            out.append('"' + s + '"')
            i = j + 1
            continue
        if c in "{}[]:,":
            if c in "}]":  # drop trailing commas
                while out and out[-1] == ",":
                    out.pop()
            out.append(c)
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if src.startswith("void 0", i):
            out.append("null")
            i += 6
            continue
        if src.startswith("!0", i):
            out.append("true")
            i += 2
            continue
        if src.startswith("!1", i):
            out.append("false")
            i += 2
            continue
        m = _NUM.match(src, i)
        if m and (c.isdigit() or c in "-."):
            tok = m.group(0)
            if tok.startswith("."):
                tok = "0" + tok
            elif tok.startswith("-."):
                tok = "-0" + tok[1:]
            if tok.endswith("."):
                tok += "0"
            out.append(tok)
            i = m.end()
            continue
        m = _IDENT.match(src, i)
        if m:
            word = m.group(0)
            i = m.end()
            # is it a key?
            k = i
            while k < n and src[k].isspace():
                k += 1
            if k < n and src[k] == ":" and (not out or out[-1] in "{,"):
                out.append(json.dumps(word))
            elif word in ("true", "false", "null"):
                out.append(word)
            elif word in ("undefined", "NaN", "Infinity"):
                out.append("null")
            else:
                out.append(json.dumps(word))  # bare identifier reference → string
            continue
        i += 1  # skip anything unexpected
    return "".join(out)


def parse(src: str):
    return json.loads(to_json(src))


def balanced(h: str, start: int) -> str:
    """Return the balanced {...} or [...] substring beginning at h[start]."""
    open_c = h[start]
    close_c = "}" if open_c == "{" else "]"
    depth, i, n = 0, start, len(h)
    quote = ""
    while i < n:
        c = h[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return h[start:i + 1]
        i += 1
    return h[start:]


def find_objects(h: str, marker: str) -> list:
    """All parsed object literals starting at each occurrence of `marker` (which must begin with { or [)."""
    out = []
    pos = 0
    while True:
        j = h.find(marker, pos)
        if j < 0:
            break
        try:
            out.append(parse(balanced(h, j)))
        except Exception:
            pass
        pos = j + 1
    return out
