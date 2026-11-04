"""
net.py - downloads with resume, retry and digest checks; GitHub release lookup

Every download in the app goes through download(). It writes <dest>.part
and renames on success. A failed attempt keeps the part file and the next
attempt resumes it with a Range request, which is what makes a retry cheap
on multi-gigabyte files. A stream that ends short of Content-Length is a
failure, not a success.
"""

import hashlib
import json
import os
import re
import time
import urllib.request

import identity
from .files import CHUNK, multipart_sort_key
from .log import get_logger

_log = get_logger(__name__)

# Some CDNs refuse urllib's default agent; a browser UA is the safe default.
BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
}
# Polite identification for APIs and manifests (GitHub requires a UA).
APP_UA = {"User-Agent": f"{identity.APP_ID}/{getattr(identity, 'VERSION', 'dev')}", "Accept": "*/*"}

UPDATE_HZ = 4

# url -> local file the user picked after a failed download. download() uses
# it instead of the network, wherever the installer wants the file. (Asking
# the user to drop the file somewhere and then retrying into a fresh temp
# folder silently ignores their file; this way the retry always sees it.)
MANUAL = {}


class DownloadError(RuntimeError):
    """
    A download failed after every retry. Carries what the UI needs for a
    manual fallback: the URL to open, the file name expected, and the path
    the installer will read it from (dest).
    """
    def __init__(self, url: str, dest: str, label: str, cause: Exception):
        self.url, self.dest, self.label, self.cause = url, dest, label, cause
        super().__init__(f"{label or os.path.basename(dest)} download failed: {cause}")


def _fmt_size(n: int) -> str:
    for unit, step in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} B"


def _detail(label, done, total, rate):
    size = f"{_fmt_size(done)} / {_fmt_size(total)}" if total else _fmt_size(done)
    out = f"{label or 'Downloading'}  {size}"
    return f"{out}  ·  {_fmt_size(int(rate))}/s" if rate else out


def download(url: str, dest: str, on_progress=None, label: str = "", timeout: int = 60,
             headers: dict = None, digest: str = None, tries: int = 3):
    """
    Download url to dest.

    on_progress -- callback(percent, message), at most UPDATE_HZ per second
    digest      -- "algo:hex" (any hashlib name, e.g. GitHub's "sha256:...");
                   a mismatch deletes the part file and counts as a failed try
    tries       -- 1 for quick checks that must never hold up a game launch
    Raises DownloadError after the last try.
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    if url in MANUAL:
        # The user downloaded this one by hand (pipeline's Manual button)
        import shutil
        shutil.copyfile(MANUAL[url], part)
        if digest:
            try:
                _check_digest(part, digest)
            except IOError as ex:
                MANUAL.pop(url, None)
                raise DownloadError(url, dest, label, ex) from ex
        os.replace(part, dest)
        return dest
    for attempt in range(tries):
        try:
            resume = os.path.getsize(part) if os.path.exists(part) else 0
            hdrs = dict(headers or BROWSER_UA)
            if resume:
                hdrs["Range"] = f"bytes={resume}-"
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=timeout) as r:
                # Only 206 honours the range; a 200 is the whole file again
                if resume and getattr(r, "status", None) != 206:
                    resume = 0
                length = int(r.headers.get("Content-Length", 0) or 0)
                total = resume + length if length else 0
                done, t0, last = resume, time.monotonic(), 0.0
                with open(part, "ab" if resume else "wb") as f:
                    while chunk := r.read(CHUNK):
                        f.write(chunk)
                        done += len(chunk)
                        now = time.monotonic()
                        if on_progress and now - last >= 1.0 / UPDATE_HZ:
                            last = now
                            on_progress(int(done * 100 / total) if total else 0,
                                        _detail(label, done, total, (done - resume) / max(now - t0, 0.001)))
            if total and done < total:
                raise IOError(f"incomplete download: {done} of {total} bytes")
            if digest:
                _check_digest(part, digest)
            os.replace(part, dest)
            if on_progress:
                on_progress(100, _detail(label, done, total or done, 0))
            return dest
        except Exception as ex:
            if attempt == tries - 1:
                raise DownloadError(url, dest, label, ex) from ex
            _log.debug("download retry %d for %s: %s", attempt + 1, url, ex)
            time.sleep(2 ** attempt)


def _check_digest(path: str, digest: str):
    algo, want = digest.split(":", 1)
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    if h.hexdigest().lower() != want.lower():
        os.remove(path)
        raise IOError(f"{algo} mismatch for {os.path.basename(path)}")


def fetch(url: str, timeout: int = 15, headers: dict = None) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or APP_UA), timeout=timeout) as r:
        return r.read()


def fetch_json(url: str, timeout: int = 15, headers: dict = None):
    return json.loads(fetch(url, timeout, headers))


# --- GitHub releases

def github_release(repo: str, tag: str = "latest", timeout: int = 30) -> dict:
    path = "latest" if tag == "latest" else f"tags/{tag}"
    return fetch_json(f"https://api.github.com/repos/{repo}/releases/{path}", timeout,
                      {**APP_UA, "Accept": "application/vnd.github+json"})


def github_assets(repo: str, pattern: str, tag: str = "latest", timeout: int = 30) -> list:
    """
    [(name, url, digest)] of release assets whose name matches the regex
    pattern, sorted so multi-part archives come in volume order
    (x.part1.rar, x.part2.rar, ...). digest is GitHub's "sha256:..." or None.

    Match every part: a single-asset matcher once picked part3.rar of a new
    three-part release and every install failed.
    """
    rel = github_release(repo, tag, timeout)
    rx = re.compile(pattern)
    hits = [(a["name"], a["browser_download_url"], a.get("digest"))
            for a in rel.get("assets", []) if rx.search(a["name"])]
    if not hits:
        raise RuntimeError(f"no asset matching {pattern!r} in {repo} {rel.get('tag_name')}")
    return sorted(hits, key=lambda h: multipart_sort_key(h[0]))


def github_asset(repo: str, suffix: str, fallback: str = None, timeout: int = 30):
    """
    (url, digest) of the newest release asset ending in suffix. If the API
    fails and fallback is given, returns (fallback, None): a rate limit
    should skip verification, not block the install. Pre-launch callers
    pass a short timeout and no fallback.
    """
    try:
        name, url, digest = github_assets(repo, re.escape(suffix) + "$", timeout=timeout)[0]
        return url, digest
    except Exception as ex:
        if fallback is None:
            raise
        _log.warning("GitHub lookup for %s failed, downloading unverified: %s", repo, ex)
        return fallback, None


def online(host: str = "api.github.com", port: int = 443, timeout: int = 5) -> bool:
    import socket
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False
