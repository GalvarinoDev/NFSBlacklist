"""
linkcopy.py - cheap, isolated copies of a game folder (hard links + real folders)

Use when a mod must not touch the real install: an offline/LAN copy of an
online client, a second variant of the game with different files, a
sandbox for a mod that rewrites game data.

Rules that keep the original safe:
  - every folder in the copy is a real folder (never a symlink to the
    original), so new files land in the copy
  - files are hard links (same drive) or copies (different drive)
  - before writing a file in the copy, call detach() on it: a write through
    a hard link changes the original file too
  - write_file() refuses any path outside the copy root
  - settings, logs and stats the program writes stay real files in the copy

A hard link costs no space until one side is replaced, so a full game copy
is nearly free.
"""

import os
import shutil

from .files import safe_join
from .log import get_logger

_log = get_logger(__name__)


def build(src: str, dst: str, skip=lambda rel: False, copy=lambda rel: False) -> int:
    """
    Mirror src into dst. skip(rel) leaves a path out; copy(rel) makes a real
    copy instead of a link, once (files the program rewrites: settings, stats).
    Re-running refreshes links to files the original replaced since (updates).
    Returns files linked or copied.
    """
    n = 0
    for d, subs, names in os.walk(src):
        rel_d = os.path.relpath(d, src)
        subs[:] = [s for s in subs if not skip(os.path.normpath(os.path.join(rel_d, s)))]
        out_d = os.path.normpath(os.path.join(dst, rel_d))
        if os.path.islink(out_d):
            os.unlink(out_d)
        os.makedirs(out_d, exist_ok=True)
        for name in names:
            rel = os.path.normpath(os.path.join(rel_d, name))
            if skip(rel):
                continue
            s, t = os.path.join(d, name), os.path.join(out_d, name)
            try:
                if os.path.lexists(t):
                    # copy() files belong to the copy once made (settings, stats): never refreshed
                    a, b = os.stat(s), os.lstat(t)
                    if copy(rel) or os.path.samestat(a, b) or (a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime)):
                        continue
                    os.remove(t)
                if copy(rel):
                    shutil.copy2(s, t)
                else:
                    try:
                        os.link(s, t)
                    except OSError:
                        shutil.copy2(s, t)  # other drive: no hard links across filesystems
                n += 1
            except OSError as ex:
                _log.debug("linkcopy %s: %s", rel, ex)
    return n


def detach(path: str):
    """Turn a hard-linked file into its own copy before writing to it."""
    try:
        if os.path.isfile(path) and os.stat(path).st_nlink > 1:
            tmp = path + ".detach"
            shutil.copy2(path, tmp)
            os.replace(tmp, path)
    except OSError:
        pass


def write_file(root: str, rel: str, data: bytes):
    """Write a file inside the copy, never through a link and never outside root."""
    p = safe_join(root, rel)
    if os.path.islink(p):
        os.unlink(p)
    detach(p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def linked_folders(root: str) -> list:
    """Folders inside root that are symlinks; an isolated copy has none."""
    bad = []
    for d, subs, _ in os.walk(root):
        for s in subs:
            if os.path.islink(os.path.join(d, s)):
                bad.append(os.path.join(d, s))
    return bad
