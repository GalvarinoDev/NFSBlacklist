"""
vdf.py - Valve text KeyValues (localconfig.vdf, config.vdf, configsets, .acf)

Two ways in:
  loads()/dumps()   full parse to nested dicts, for reading and for small
                    files the engine owns
  find_block() etc. surgical edits that keep the rest of a big file byte
                    for byte as Steam wrote it (localconfig.vdf)

Brace matching is always quote-aware. Launch options contain literal { and }
(bash "${@/a.exe/b.exe}"); a plain depth counter cuts blocks short and
corrupts localconfig.vdf. Do not simplify that away.
"""

import re

from .files import backup_file, write_bytes
from .log import get_logger

_log = get_logger(__name__)


# --- full parser

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|(//[^\n]*)|([^\s{}"]+)')


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def loads(text: str) -> dict:
    """Parse text VDF into nested dicts. Repeated values: the last wins; repeated blocks merge. Keys keep their case."""
    root, stack, key = {}, [], None
    cur = root
    for m in _TOKEN.finditer(text):
        quoted, brace, comment, bare = m.groups()
        if comment:
            continue
        if brace == "{":
            k = key if key is not None else ""
            # A repeated block key (Steam writes some twice) merges instead of replacing
            new = cur[k] if isinstance(cur.get(k), dict) else {}
            cur[k] = new
            stack.append(cur); cur = new; key = None
        elif brace == "}":
            cur = stack.pop() if stack else root
            key = None
        else:
            tok = _unescape(quoted) if quoted is not None else bare
            if key is None:
                key = tok
            else:
                cur[key] = tok; key = None
    return root


def dumps(obj: dict, depth: int = 0) -> str:
    out, tabs = [], "\t" * depth
    for k, v in obj.items():
        if isinstance(v, dict):
            out.append(f'{tabs}"{_escape(k)}"\n{tabs}{{\n{dumps(v, depth + 1)}{tabs}}}\n')
        else:
            out.append(f'{tabs}"{_escape(k)}"\t\t"{_escape(str(v))}"\n')
    return "".join(out)


def get_ci(d: dict, *path):
    """Walk nested keys case-insensitively (Steam mixes "Steam"/"steam", "Apps"/"apps")."""
    for p in path:
        if not isinstance(d, dict):
            return None
        low = p.lower()
        d = next((v for k, v in d.items() if k.lower() == low), None)
    return d


# --- surgical editing

def block_end(text: str, open_brace: int) -> int:
    """Index of the } that closes the { at open_brace, skipping quoted strings. -1 if unbalanced."""
    depth, quote, i = 0, False, open_brace
    while i < len(text):
        c = text[i]
        if c == "\\" and quote:
            i += 2
            continue
        if c == '"':
            quote = not quote
        elif not quote:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def find_block(text: str, key: str, start: int = 0, end: int = None):
    """(open, close) brace offsets of the first "key" { ... } in text[start:end], or None."""
    m = re.compile(r'"' + re.escape(key) + r'"\s*\{', re.I).search(text, start, len(text) if end is None else end)
    if not m:
        return None
    close = block_end(text, m.end() - 1)
    return None if close == -1 else (m.end() - 1, close)


def find_path(text: str, *keys):
    """Nested find_block: find_path(t, "Software", "Valve", "Steam", "apps", "12210")."""
    start, end, span = 0, None, None
    for k in keys:
        span = find_block(text, k, start, end)
        if not span:
            return None
        start, end = span[0] + 1, span[1]
    return span


def split_flat(inner: str):
    """
    (flat keys, sub-blocks) of a block body, split at the first sub-block.
    Edits go into the flat part only. Steam reads an app's LaunchOptions
    from the flat keys; a same-named key inside a cloud sub-block is
    ignored by the Properties dialog.
    """
    sub = re.search(r'"[^"]+"\s*\{', inner)
    return (inner[:sub.start()], inner[sub.start():]) if sub else (inner, "")


def value_re(key: str):
    """Matches "key" "value" with groups (prefix, value, closing quote)."""
    return re.compile(r'("' + re.escape(key) + r'"\s*")((?:[^"\\]|\\.)*)(")', re.I)


def set_flat_value(block_inner: str, key: str, value: str, append: bool = False) -> str:
    """Set (or append to) key in the flat part of a block body. value is already VDF-escaped."""
    flat, rest = split_flat(block_inner)
    rx = value_re(key)
    m = rx.search(flat)
    if m:
        old = m.group(2)
        if append:
            if value in old:
                return block_inner
            value = (old.strip() + " " + value).strip()
        flat = flat[:m.start(2)] + value + flat[m.end(2):]
    else:
        # New key goes before the whitespace that indents what follows (a sub-block
        # or the closing brace), at the indent of the existing keys
        tail = re.search(r"[ \t]*$", flat).group(0)
        flat = flat[:len(flat) - len(tail)]
        ind = re.search(r'\n([ \t]+)"', flat)
        indent = ind.group(1) if ind else (tail if rest else tail + "\t")
        if not flat.endswith("\n"):
            flat += "\n"
        flat += f'{indent}"{key}"\t\t"{value}"\n' + tail
    return flat + rest


def balanced(text: str) -> bool:
    depth, quote, i = 0, False, 0
    while i < len(text):
        c = text[i]
        if c == "\\" and quote:
            i += 2
            continue
        if c == '"':
            quote = not quote
        elif not quote:
            depth += c == "{"
            depth -= c == "}"
            if depth < 0:
                return False
        i += 1
    return depth == 0 and not quote


def write_checked(path: str, text: str) -> bool:
    """
    Back up, check the braces balance, then write atomically. An unbalanced
    result is refused before Steam ever sees it.
    """
    if not balanced(text):
        _log.error("refusing to write %s: braces do not balance", path)
        return False
    backup_file(path)
    write_bytes(path, text.encode("utf-8", "surrogateescape"))
    return True


def read(path: str) -> str:
    # surrogateescape: localconfig.vdf can hold non-UTF-8 bytes; they survive the round trip
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def escape(s: str) -> str:
    return _escape(s)
