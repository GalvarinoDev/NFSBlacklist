"""
selfupdate.py - update the app itself from its GitHub repo

Same rules as shell/launcher.sh (keep the two in sync):
  - compare the local commit (VERSION file) with the branch head
  - download only the files the compare API lists, into a staging folder
  - never overwrite protected paths (config, logs, user-provided files)
  - byte-compile staged .py files first; refuse an update that does not compile
  - files that 404 at the new head were deleted or renamed upstream: delete them
  - a never-updated install (VERSION "0") gets the full repo zip

Updates only copy files. Anything else the new version needs (a new pip
package, a moved folder) must be done by the app itself on its next start.
"""

import compileall
import os
import shutil
import sys
import tempfile
import zipfile

import identity
from .log import get_logger
from .net import APP_UA, download, fetch_json

_log = get_logger(__name__)

VERSION_FILE = os.path.join(identity.PROJECT_ROOT, "VERSION")
PROTECTED = ("logs/", os.path.basename(identity.CONFIG_PATH), ".venv/") + tuple(getattr(identity, "PROTECTED_PATHS", ()))
BRANCH = getattr(identity, "GITHUB_BRANCH", "main")


def _api(path):
    return fetch_json(f"https://api.github.com/repos/{identity.GITHUB_USER}/{identity.GITHUB_REPO}/{path}", 15,
                      {**APP_UA, "Accept": "application/vnd.github+json"})


def local_sha() -> str:
    try:
        return open(VERSION_FILE).read().strip() or "0"
    except OSError:
        return "0"


def check() -> tuple:
    """(local_sha, remote_sha, [changed files]) ; files None means a full download is needed."""
    loc = local_sha()
    remote = _api(f"commits/{BRANCH}")["sha"]
    if loc == remote:
        return loc, remote, []
    if loc == "0":
        return loc, remote, None
    cmp = _api(f"compare/{loc}...{remote}")
    files = []
    for f in cmp.get("files", []):
        files.append(f["filename"])
        if f.get("previous_filename"):
            files.append(f["previous_filename"])
    return loc, remote, files


def _protected(rel: str) -> bool:
    return any(rel == p or rel.startswith(p) for p in PROTECTED)


def apply(remote: str, files, on_progress=None) -> list:
    """Download and install the update. Returns changed paths. Raises on failure (nothing applied)."""
    prog = on_progress or (lambda *a: None)
    raw = f"https://raw.githubusercontent.com/{identity.GITHUB_USER}/{identity.GITHUB_REPO}/{remote}"
    stage = tempfile.mkdtemp(prefix=f"{identity.APP_ID}_upd_")
    removed = []
    try:
        if files is None:
            z = os.path.join(stage, "repo.zip")
            download(f"https://github.com/{identity.GITHUB_USER}/{identity.GITHUB_REPO}/archive/{remote}.zip", z, prog, "Update")
            with zipfile.ZipFile(z) as zf:
                zf.extractall(stage)
            os.remove(z)
            top = next(os.path.join(stage, d) for d in os.listdir(stage) if os.path.isdir(os.path.join(stage, d)))
            files = [os.path.relpath(os.path.join(d, n), top) for d, _, ns in os.walk(top) for n in ns]
            src = top
        else:
            src = os.path.join(stage, "files")
            for i, rel in enumerate(files):
                if _protected(rel):
                    continue
                prog(int(i * 90 / max(len(files), 1)), f"Downloading {rel}")
                try:
                    download(f"{raw}/{rel}", os.path.join(src, rel), timeout=30, headers=APP_UA, tries=2)
                except Exception as ex:
                    if getattr(getattr(ex, "cause", None), "code", None) == 404:
                        removed.append(rel)
                        continue
                    raise
        if not compileall.compile_dir(src, quiet=1, force=True):
            raise RuntimeError("update does not compile; not applied")
        changed = []
        for rel in files:
            if _protected(rel) or rel in removed:
                continue
            s = os.path.join(src, rel)
            if os.path.isfile(s):
                d = os.path.join(identity.PROJECT_ROOT, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
                changed.append(rel)
        for rel in removed:
            if not _protected(rel):
                try: os.remove(os.path.join(identity.PROJECT_ROOT, rel)); changed.append(rel)
                except OSError: pass
        for sh in ("launcher.sh", "install.sh", "uninstall.sh", "prelaunch.sh"):
            p = os.path.join(identity.PROJECT_ROOT, sh)
            if os.path.exists(p):
                os.chmod(p, 0o755)
        with open(VERSION_FILE, "w") as f:
            f.write(remote + "\n")
        prog(100, f"Updated {len(changed)} file(s)")
        return changed
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def reset_recommended(changed: list) -> bool:
    """Same rule as launcher.sh: the config module or many source files changed."""
    src = [f for f in changed if f.startswith("src/")]
    return any(f.endswith("/config.py") for f in src) or len(src) > 3


def relaunch():
    py = sys.executable
    os.execv(py, [py, os.path.join(identity.PROJECT_ROOT, "src", "main.py")])
