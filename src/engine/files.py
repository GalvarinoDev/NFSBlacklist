"""
files.py - safe file helpers: atomic writes, hashes, archives, case-insensitive paths

Leaf module (stdlib + log). Anything an uninstaller or a later run reads
back is written atomically: a sleep or power loss mid-write must never
leave a half file behind.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from .log import get_logger

_log = get_logger(__name__)

CHUNK = 1 << 20


# --- atomic writes

def write_bytes(path: str, data: bytes):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def write_text(path: str, text: str, encoding: str = "utf-8"):
    write_bytes(path, text.encode(encoding))


def write_json(path: str, data, indent: int = 2):
    write_text(path, json.dumps(data, indent=indent))


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def backup_file(path: str, suffix: str = ".bak"):
    """Copy path to path.bak before editing it (Steam config files)."""
    if os.path.exists(path):
        try:
            shutil.copy2(path, path + suffix)
        except OSError:
            _log.debug("backup failed for %s", path, exc_info=True)


# --- hashes

_HEX_ALGOS = {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}


def file_digest(path: str, algo: str = "sha256") -> str:
    if algo in ("xxh64", "xxh3_64"):
        import xxhash  # optional dependency, only for manifests that use it
        h = getattr(xxhash, algo)()
    else:
        h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def guess_algo(hexdigest: str) -> str | None:
    """Hash algorithm from a bare hex digest's length (16 hex = xxh64)."""
    if len(hexdigest) == 16:
        return "xxh64"
    return _HEX_ALGOS.get(len(hexdigest))


def matches(path: str, size: int = None, digest: str = None) -> bool:
    """
    True when path exists and matches the given size and digest.
    digest is "algo:hex" or bare hex (algo guessed from length).
    """
    try:
        if size is not None and os.path.getsize(path) != int(size):
            return False
        if digest:
            algo, _, want = digest.rpartition(":")
            algo = algo or guess_algo(want)
            if not algo:
                return True
            return file_digest(path, algo).lower() == want.lower()
        return os.path.isfile(path)
    except (OSError, ImportError):
        return False


# --- paths

def safe_join(root: str, relpath: str) -> str:
    """
    root/relpath, refusing anything that escapes root (zip slip, "../",
    absolute paths). Every path that comes from a download or a manifest
    goes through this.
    """
    rel = relpath.replace("\\", "/").lstrip("/")
    joined = os.path.normpath(os.path.join(root, rel))
    # Check with real paths (symlinks inside root can point out), but return the
    # path as given: on Bazzite /home is a link to /var/home, and mixing the two
    # forms breaks every later relpath()
    real, base = os.path.realpath(joined), os.path.realpath(root)
    if real != base and not real.startswith(base + os.sep):
        raise ValueError(f"path escapes target folder: {relpath}")
    return joined


def ci_path(root: str, relpath: str) -> str:
    """
    Resolve relpath under root case-insensitively, reusing whatever
    spelling already exists on disk. Windows games and mods mix "Update",
    "update" and "UPDATE"; on Linux those are three folders and the game
    only reads one.
    """
    cur = root
    for part in [p for p in relpath.replace("\\", "/").split("/") if p]:
        hit = None
        if os.path.isdir(cur):
            low = part.lower()
            hit = next((e for e in os.listdir(cur) if e.lower() == low), None)
        cur = os.path.join(cur, hit or part)
    return cur


def remove_empty_dirs(root: str):
    for d, _, _ in sorted(os.walk(root), key=lambda w: -w[0].count(os.sep)):
        if d != root:
            try: os.rmdir(d)
            except OSError: pass


# --- archives

def extract(archive: str, dest: str, case_merge: bool = False, strip: int = 0) -> list:
    """
    Extract a zip, tar.* or rar (first volume of a multi-part set is fine)
    into dest. Returns the relative paths written.

    case_merge -- merge into existing folder spellings (see ci_path)
    strip      -- drop this many leading path parts, like tar --strip-components
    """
    low = archive.lower()
    if low.endswith(".zip"):
        return _extract_zip(archive, dest, case_merge, strip)
    with tempfile.TemporaryDirectory(prefix="engine_x_") as tmp:
        if low.endswith(".rar"):
            # unrar ships with SteamOS and Bazzite; python has no rar reader
            r = subprocess.run(["unrar", "x", "-o+", "-idq", archive, tmp + "/"], capture_output=True)
            if r.returncode != 0:
                raise RuntimeError(f"unrar failed ({r.returncode}): {r.stderr.decode(errors='replace')[:300]}")
        elif ".tar" in low or low.endswith((".tgz", ".txz")):
            r = subprocess.run(["tar", "-xf", archive, "-C", tmp], capture_output=True)
            if r.returncode != 0:
                raise RuntimeError(f"tar failed: {r.stderr.decode(errors='replace')[:300]}")
        elif low.endswith(".7z"):
            r = subprocess.run(["7z", "x", "-y", f"-o{tmp}", archive], capture_output=True)
            if r.returncode != 0:
                raise RuntimeError("7z failed (is p7zip installed?)")
        else:
            raise ValueError(f"unknown archive type: {archive}")
        return merge_tree(tmp, dest, case_merge, strip)


def _extract_zip(archive, dest, case_merge, strip):
    out = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            parts = [p for p in info.filename.replace("\\", "/").split("/") if p][strip:]
            if not parts or info.is_dir():
                continue
            rel = "/".join(parts)
            target = safe_join(dest, os.path.relpath(ci_path(dest, rel), dest)) if case_merge else safe_join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
            out.append(os.path.relpath(target, dest))
    return out


def merge_tree(src: str, dest: str, case_merge: bool = False, strip: int = 0) -> list:
    """Move every file under src into dest (overwrite). Returns relative paths written."""
    out = []
    for d, _, names in os.walk(src):
        for n in names:
            full = os.path.join(d, n)
            parts = os.path.relpath(full, src).split(os.sep)[strip:]
            if not parts:
                continue
            rel = "/".join(parts)
            target = safe_join(dest, os.path.relpath(ci_path(dest, rel), dest)) if case_merge else safe_join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.lexists(target):
                os.remove(target)
            shutil.move(full, target)
            out.append(os.path.relpath(target, dest))
    return out


def multipart_sort_key(name: str):
    """Sort part1/part2/part10 numerically so the first volume comes first."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


# --- PE files

def pe_machine(path: str) -> str | None:
    """'x86', 'x64' or None. Used to tell 32-bit and 64-bit game exes apart."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        off = int.from_bytes(head[0x3C:0x40], "little")
        if head[:2] != b"MZ" or head[off:off + 4] != b"PE\0\0":
            return None
        m = int.from_bytes(head[off + 4:off + 6], "little")
        return {0x14C: "x86", 0x8664: "x64"}.get(m)
    except (OSError, ValueError):
        return None
