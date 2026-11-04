"""
manifest.py - keep a folder in sync with a remote file list

Most community clients publish what their updater downloads: a JSON list
of files with sizes and hashes. Syncing against that list is the best
install and update path there is: headless, verified, incremental, and the
same code installs and updates.

Formats parse() understands (all normalised to Entry):
    [[path, size, hash], ...]                          list rows
    [[path, size, hash, component], ...]               rows with a component tag
    {"files": [...rows or dicts...], ...}              wrapped
    [{"path"|"name", "size", "hash"|"sha1"|"sha256"|..., "url"?}, ...]
    {"path": {"size":..., "sha256":...}, ...}          mapping

sync() downloads only what is missing or different, into <file>.new, and
swaps everything in only after every download succeeded: a failed update
never leaves a half-old, half-new client. Files a running game holds open
are fine to replace on Linux (the old inode lives until the game exits).
"""

import os
import posixpath
from collections import namedtuple

from .files import file_digest, guess_algo, matches, safe_join
from .log import get_logger
from .net import download, fetch_json

_log = get_logger(__name__)

Entry = namedtuple("Entry", "path size digest url component")

_HASH_KEYS = ("sha256", "sha1", "sha512", "md5", "xxh64", "hash", "digest", "checksum")


def _digest(raw) -> str | None:
    if not raw:
        return None
    raw = str(raw).lower()
    if ":" in raw:
        return raw
    algo = guess_algo(raw)
    return f"{algo}:{raw}" if algo else None


def _from_dict(d: dict, path=None) -> Entry:
    p = path or d.get("path") or d.get("name") or d.get("file")
    h = next((f"{k}:{d[k]}" if k in ("sha256", "sha1", "sha512", "md5", "xxh64") else d[k]
              for k in _HASH_KEYS if d.get(k)), None)
    return Entry(p, d.get("size"), _digest(h), d.get("url"), d.get("component"))


def parse(data) -> list:
    """Normalise any supported manifest shape into [Entry]."""
    if isinstance(data, dict) and "files" in data:
        data = data["files"]
    out = []
    if isinstance(data, dict):
        for p, v in data.items():
            out.append(_from_dict(v if isinstance(v, dict) else {"hash": v}, p))
    else:
        for row in data:
            if isinstance(row, dict):
                out.append(_from_dict(row))
            else:
                row = list(row) + [None] * 4
                out.append(Entry(row[0], row[1], _digest(row[2]), None, row[3]))
    for e in out:
        if not e.path:
            raise ValueError("manifest entry without a path")
        safe_join("/tmp", e.path)  # rejects ../ and absolute paths early
    return out


def load(url: str, timeout: int = 15) -> list:
    return parse(fetch_json(url, timeout))


def changed(entries: list, root: str, remap=None) -> list:
    """Entries whose file under root is missing or differs. remap(path) -> local relative path."""
    out = []
    for e in entries:
        dest = safe_join(root, remap(e.path) if remap else e.path)
        if not matches(dest, e.size, e.digest):
            out.append(e)
    return out


def sync(entries: list, root: str, base_url: str = None, remap=None, components: set = None,
         on_progress=None, headers: dict = None, tries: int = 3, url_for=None) -> list:
    """
    Make root match entries. Returns the relative paths that were updated.

    base_url   -- file URL = base_url + "/" + path (entries may carry their own url)
    url_for    -- url_for(entry) -> URL, for CDNs with odd layouts (?hash suffix etc.)
    remap      -- remap(path) -> local relative path (manifest "dest" fields, case fixes)
    components -- only entries whose component is in this set (None = all)
    Raises net.DownloadError on a failed file; nothing is swapped in then.
    """
    prog = on_progress or (lambda *a: None)
    todo = [e for e in changed(entries, root, remap) if components is None or e.component in (None, *components)]
    if not todo:
        prog(100, "Up to date")
        return []
    total = sum(int(e.size or 0) for e in todo) or len(todo)
    done, staged = 0, []
    try:
        for e in todo:
            rel = remap(e.path) if remap else e.path
            dest = safe_join(root, rel)
            url = (url_for(e) if url_for else None) or e.url or posixpath.join(base_url.rstrip("/"), e.path.lstrip("/"))
            part_base = done

            def p(pc, msg, _b=part_base, _s=int(e.size or 0)):
                prog(int((_b + _s * pc / 100) * 100 / total) if _s else int(done * 100 / total), msg)

            download(url, dest + ".new", p, os.path.basename(rel), headers=headers,
                     digest=e.digest if e.digest and not e.digest.startswith("xxh") else None, tries=tries)
            if e.digest and e.digest.startswith("xxh") and not matches(dest + ".new", e.size, e.digest):
                raise IOError(f"hash mismatch for {rel}")
            staged.append((dest + ".new", dest, rel))
            done += int(e.size or 0) or 1
    except Exception:
        for new, _, _ in staged:
            try: os.remove(new)
            except OSError: pass
        raise
    for new, dest, _ in staged:
        os.replace(new, dest)
    prog(100, f"Updated {len(staged)} file(s)")
    return [rel for _, _, rel in staged]


def snapshot(root: str, algo: str = "sha256", skip=lambda rel: False) -> list:
    """Make a manifest of a folder (for publishing your own CDN or for receipts)."""
    out = []
    for d, _, names in os.walk(root):
        for n in names:
            full = os.path.join(d, n)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if not skip(rel):
                out.append([rel, os.path.getsize(full), file_digest(full, algo)])
    return sorted(out)
