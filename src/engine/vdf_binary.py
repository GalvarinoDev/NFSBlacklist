"""
vdf_binary.py - Valve binary KeyValues (shortcuts.vdf)

A full parser and encoder: load() gives nested dicts, dump() writes them
back byte for byte. Parsing the whole tree is safer than splitting the file
on byte patterns: entry headers ("\\0<n>\\0") also occur inside strings and
numbers, and a splitter that guesses wrong can drop the user's shortcuts.

Type bytes: 0x00 dict, 0x01 string, 0x02 int32, 0x03 float32, 0x04 pointer,
0x05 wide string, 0x06 color, 0x07 uint64, 0x08 end of dict, 0x0A int64.
Values keep their type through Typed so a round trip changes nothing.
"""

import struct

T_DICT, T_STR, T_INT32, T_FLOAT, T_PTR, T_WSTR, T_COLOR, T_UINT64, T_END, T_INT64 = (
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0A)
_FIXED = {T_INT32: "<i", T_FLOAT: "<f", T_PTR: "<I", T_COLOR: "<I", T_UINT64: "<Q", T_INT64: "<q"}


class Typed:
    """A value with an explicit type byte, for anything that is not str / int32 / dict."""
    __slots__ = ("t", "v")

    def __init__(self, t: int, v):
        self.t, self.v = t, v

    def __eq__(self, other):
        return isinstance(other, Typed) and (self.t, self.v) == (other.t, other.v)

    def __repr__(self):
        return f"Typed({self.t:#x}, {self.v!r})"


def _cstr(buf: bytes, pos: int):
    end = buf.index(b"\x00", pos)
    return buf[pos:end].decode("utf-8", "surrogateescape"), end + 1


def _parse(buf: bytes, pos: int):
    node = {}
    while True:
        t = buf[pos]; pos += 1
        if t == T_END:
            return node, pos
        key, pos = _cstr(buf, pos)
        if t == T_DICT:
            val, pos = _parse(buf, pos)
        elif t == T_STR:
            val, pos = _cstr(buf, pos)
        elif t == T_WSTR:
            end = pos
            while buf[end:end + 2] != b"\x00\x00":
                end += 2
            val, pos = Typed(t, buf[pos:end].decode("utf-16-le")), end + 2
        elif t in _FIXED:
            fmt = _FIXED[t]
            n = struct.calcsize(fmt)
            (v,) = struct.unpack_from(fmt, buf, pos); pos += n
            val = v if t == T_INT32 else Typed(t, v)
        else:
            raise ValueError(f"unknown binary VDF type {t:#x} at {pos - 1}")
        node[key] = val


def loads(data: bytes) -> dict:
    if not data:
        return {}
    node, pos = _parse(data, 0)
    # Some writers add a trailing 0x08 after the root dict
    if data[pos:].strip(b"\x08"):
        raise ValueError(f"trailing data after binary VDF at {pos}")
    return node


def _enc(node: dict) -> bytes:
    out = bytearray()
    for k, v in node.items():
        kb = k.encode("utf-8", "surrogateescape") + b"\x00"
        if isinstance(v, dict):
            out += bytes([T_DICT]) + kb + _enc(v)
        elif isinstance(v, str):
            out += bytes([T_STR]) + kb + v.encode("utf-8", "surrogateescape") + b"\x00"
        elif isinstance(v, bool) or isinstance(v, int):
            out += bytes([T_INT32]) + kb + struct.pack("<i", int(v))
        elif isinstance(v, Typed):
            out += bytes([v.t]) + kb
            out += (v.v.encode("utf-16-le") + b"\x00\x00") if v.t == T_WSTR else struct.pack(_FIXED[v.t], v.v)
        else:
            raise TypeError(f"cannot encode {type(v).__name__} for key {k!r}")
    out.append(T_END)
    return bytes(out)


def dumps(node: dict) -> bytes:
    """Encode the root mapping. {"shortcuts": {...}} gives the file Steam writes, ending 0x08 0x08."""
    return _enc(node)


def load(path: str) -> dict:
    with open(path, "rb") as f:
        return loads(f.read())


def to_signed32(n: int) -> int:
    return n - (1 << 32) if n > 0x7FFFFFFF else n


def to_unsigned32(n: int) -> int:
    return n + (1 << 32) if n < 0 else n
