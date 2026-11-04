"""
mods.py - mods as ordered layers with receipts, updates and clean removal

A Mod knows where its latest version comes from and how to put its files
into a staging folder. The engine does the rest:

  deploy    copy staged files into the game, recording every file in a
            receipt (owner mod, size, hash) and backing up any original
            game file it replaces
  layers    a mod's `layer` (int) is its priority: higher layers win
            conflicts. Updating a lower layer replays every layer above it,
            so priority never depends on install or update order
  updates   latest() is compared with what the receipt says is installed;
            file-only updates never need Steam closed
  remove    deletes only files the receipt lists (and that still match what
            we wrote), restores originals, prunes empty folders

Overlay loaders (folder-priority loaders, ASI/plugin folders, mod managers
that read alphabetically) load by folder name, not install time: use
load_order_name() to give folders sortable prefixes.

    class FixPack(mods.GitHubMod):
        id, name, layer = "fixpack", "Fix Pack", 10
        repo, pattern = "someone/fixpack", r"\\.zip$"

    mods.install_all(game_dir, [FixPack(), Textures()], key="mygame", on_progress=cb)
"""

import os
import shutil
import tempfile
from datetime import datetime

import identity
from . import config
from .files import ci_path, extract, file_digest, read_json, safe_join, write_json
from .log import get_logger
from .files import multipart_sort_key
from .net import download

_log = get_logger(__name__)

RECEIPTS = os.path.join(identity.DATA_DIR, "receipts")
ORIGINALS = os.path.join(identity.DATA_DIR, "originals")


class Mod:
    id = ""            # stable slug; receipts and config are keyed on it
    name = ""
    layer = 50         # priority: higher wins conflicts and installs later
    dest = ""          # sub folder of the game dir the staged files go into
    case_merge = True  # merge into existing folder spellings (Windows games)
    optional = True
    options = {}       # {option_id: label} the UI can offer; saved per mod

    def latest(self) -> str:
        """Newest version string (tag, date, manifest hash). Network allowed, keep it quick."""
        return "0"

    def stage(self, workdir: str, staging: str, option: str, prog) -> str:
        """Download and unpack into staging. Return the version actually staged."""
        raise NotImplementedError

    def after_deploy(self, game_dir: str, option: str, prog):
        """Optional: config edits, ini tweaks, DLL overrides. Runs after files land."""

    def removable_paths(self, game_dir: str) -> list:
        """Extra paths the mod creates at run time (logs, caches) to delete on removal."""
        return []


class UrlMod(Mod):
    """One archive or file at a fixed URL (pin a digest when you can)."""
    url = ""
    digest = None
    version = "1"
    strip = 0

    def latest(self):
        return self.version

    def stage(self, workdir, staging, option, prog):
        f = os.path.join(workdir, os.path.basename(self.url.split("?")[0]))
        download(self.url, f, prog, self.name, digest=self.digest)
        _unpack(f, staging, self.strip)
        return self.version


class GitHubMod(Mod):
    """Latest GitHub release; every asset matching `pattern` (multi-part archives work)."""
    repo = ""
    pattern = r"\.zip$"
    strip = 0

    def _release(self):
        # One API call per object: GitHub allows 60 unauthenticated calls an hour
        if getattr(self, "_rel", None) is None:
            from .net import github_release
            self._rel = github_release(self.repo)
        return self._rel

    def latest(self):
        return self._release()["tag_name"]

    def stage(self, workdir, staging, option, prog):
        import re
        rx = re.compile(self.pattern)
        assets = sorted([(a["name"], a["browser_download_url"], a.get("digest")) for a in self._release().get("assets", [])
                         if rx.search(a["name"])], key=lambda a: multipart_sort_key(a[0]))
        if not assets:
            raise RuntimeError(f"no asset matching {self.pattern!r} in {self.repo} {self.latest()}")
        files = []
        for i, (name, url, digest) in enumerate(assets):
            f = os.path.join(workdir, name)
            download(url, f, lambda p, m, i=i: prog(int((i + p / 100) * 100 / len(assets)), m), name, digest=digest)
            files.append(f)
        # Multi-part rar: extracting the first volume reads the rest
        for f in files:
            if not _is_later_volume(f):
                _unpack(f, staging, self.strip)
        return self.latest()


def _is_later_volume(f: str) -> bool:
    import re
    low = f.lower()
    m = re.search(r"\.part(\d+)\.rar$", low)
    if m:
        return int(m.group(1)) > 1
    return bool(re.search(r"\.r\d\d$", low))  # old-style .rar + .r00, .r01...


def _unpack(f: str, staging: str, strip: int):
    low = f.lower()
    if low.endswith((".zip", ".rar", ".7z", ".tar.gz", ".tgz", ".tar.xz", ".tar")):
        extract(f, staging, strip=strip)
    else:
        os.makedirs(staging, exist_ok=True)
        shutil.copy2(f, os.path.join(staging, os.path.basename(f)))


# --- receipts

def _receipt_path(key: str) -> str:
    return os.path.join(RECEIPTS, f"{key}.json")


def receipt(key: str) -> dict:
    """{"files": {rel: {"mod", "size", "sha256", "original"}}, "mods": {id: {version, option, layer}}}"""
    return read_json(_receipt_path(key), None) or {"files": {}, "mods": {}}


def _save(key: str, r: dict):
    os.makedirs(RECEIPTS, exist_ok=True)
    write_json(_receipt_path(key), r)


def installed(key: str) -> dict:
    return receipt(key)["mods"]


# --- deploy / remove

def _deploy(key, game_dir, mod, staging, version, option, r, prog):
    base = os.path.join(game_dir, mod.dest) if mod.dest else game_dir
    count = 0
    for d, _, names in os.walk(staging):
        for n in names:
            src = os.path.join(d, n)
            rel_in = os.path.relpath(src, staging).replace(os.sep, "/")
            target = ci_path(base, rel_in) if mod.case_merge else safe_join(base, rel_in)
            rel = os.path.relpath(target, game_dir).replace(os.sep, "/")
            safe_join(game_dir, rel)
            prev = r["files"].get(rel)
            if os.path.isfile(target) and not prev:
                # An original game file: keep a copy to restore on removal
                bak = os.path.join(ORIGINALS, key, rel)
                if not os.path.exists(bak):
                    os.makedirs(os.path.dirname(bak), exist_ok=True)
                    shutil.copy2(target, bak)
            parent, made = os.path.dirname(target), []
            while not os.path.isdir(parent) and parent.startswith(game_dir + os.sep):
                made.append(os.path.relpath(parent, game_dir).replace(os.sep, "/")); parent = os.path.dirname(parent)
            r.setdefault("dirs", {}).update({m: mod.id for m in made if m not in r.get("dirs", {})})
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.lexists(target):
                os.remove(target)
            shutil.copy2(src, target)
            r["files"][rel] = {"mod": mod.id, "size": os.path.getsize(target), "sha256": file_digest(target),
                               "original": bool((prev or {}).get("original")) or os.path.exists(os.path.join(ORIGINALS, key, rel))}
            count += 1
    r["mods"][mod.id] = {"version": version, "option": option, "layer": mod.layer,
                         "installed_at": datetime.now().isoformat(timespec="seconds")}
    prog(f"  {mod.name}: {count} file(s)")


def _remove_files(key, game_dir, r, mod_id, prog):
    gone = 0
    for rel, info in list(r["files"].items()):
        if info["mod"] != mod_id:
            continue
        path = os.path.join(game_dir, rel)
        try:
            # A file the user or another tool changed since is left alone
            if os.path.isfile(path) and os.path.getsize(path) == info["size"] and file_digest(path) == info["sha256"]:
                os.remove(path)
                gone += 1
        except OSError:
            pass
        bak = os.path.join(ORIGINALS, key, rel)
        if os.path.isfile(bak) and not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.move(bak, path)
        del r["files"][rel]
    # Only folders this mod created, deepest first, and only when empty
    for rel in sorted([k for k, v in r.get("dirs", {}).items() if v == mod_id], key=lambda k: -k.count("/")):
        try:
            os.rmdir(os.path.join(game_dir, rel))
            del r["dirs"][rel]
        except OSError:
            pass
    r["mods"].pop(mod_id, None)
    prog(f"  removed {gone} file(s) of {mod_id}")


def install_all(game_dir: str, mods: list, key: str, options: dict = None, only: set = None,
                on_progress=None, workdir: str = None) -> dict:
    """
    Install (or update) mods into game_dir in layer order.

    options -- {mod_id: option}; default is the saved choice, else the first option
    only    -- mod ids that changed; every mod at or above the lowest changed
               layer is replayed so higher layers still win. None = all.
    Returns {mod_id: version}. Raises on the first failure, leaving the
    receipt consistent with what is on disk.
    """
    prog = on_progress or (lambda *a: None)
    saved = config.get("mods", {}).get(key, {})
    options = {**{k: v.get("option") for k, v in saved.items()}, **(options or {})}
    mods = sorted(mods, key=lambda m: m.layer)
    if only is not None:
        floor = min((m.layer for m in mods if m.id in only), default=None)
        mods = [m for m in mods if floor is not None and m.layer >= floor]
    r = receipt(key)
    out = {}
    tmp_root = workdir or tempfile.mkdtemp(prefix=f"{identity.APP_ID}_mods_")
    try:
        # Remove first, top layer down, so lower layers' files show through correctly
        for m in reversed(mods):
            if m.id in r["mods"]:
                _remove_files(key, game_dir, r, m.id, prog)
        _save(key, r)
        for i, m in enumerate(mods):
            opt = options.get(m.id) or next(iter(m.options), None)
            prog(f"{m.name}...")
            work = os.path.join(tmp_root, m.id); staging = os.path.join(work, "staging")
            os.makedirs(staging, exist_ok=True)
            ver = m.stage(work, staging, opt, lambda p, msg: prog(msg)) or m.latest()
            _deploy(key, game_dir, m, staging, ver, opt, r, prog)
            _save(key, r)
            m.after_deploy(game_dir, opt, prog)
            out[m.id] = ver
            shutil.rmtree(work, ignore_errors=True)
    finally:
        if not workdir:
            shutil.rmtree(tmp_root, ignore_errors=True)
    c = config.load()
    c.setdefault("mods", {}).setdefault(key, {}).update(
        {mid: {"version": v, "option": options.get(mid)} for mid, v in out.items()})
    config.save(c)
    return out


def remove_all(game_dir: str, key: str, mods: list = None, on_progress=None):
    """Remove every mod in the receipt (or the given Mod objects), top layer first."""
    prog = on_progress or (lambda *a: None)
    r = receipt(key)
    ids = [m.id for m in mods] if mods else sorted(r["mods"], key=lambda i: -r["mods"][i].get("layer", 0))
    extra = {m.id: m for m in mods or []}
    for mid in ids:
        if mid in extra:
            for p in extra[mid].removable_paths(game_dir):
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.path.exists(p) and os.remove(p))
        _remove_files(key, game_dir, r, mid, prog)
    _save(key, r)
    if not r["files"]:
        try: os.remove(_receipt_path(key))
        except OSError: pass


def check_updates(key: str, mods: list) -> dict:
    """{mod_id: (installed, latest)} for mods with a newer version. Network errors are skipped."""
    have = installed(key)
    out = {}
    for m in mods:
        if m.id not in have:
            continue
        try:
            new = m.latest()
        except Exception as ex:
            _log.debug("update check %s failed: %s", m.id, ex)
            continue
        if new and new != have[m.id].get("version"):
            out[m.id] = (have[m.id].get("version"), new)
    return out


def verify(key: str, game_dir: str) -> list:
    """Receipt files that are missing or changed (Steam Verify or a game update undid them)."""
    bad = []
    for rel, info in receipt(key)["files"].items():
        p = os.path.join(game_dir, rel)
        if not os.path.isfile(p) or os.path.getsize(p) != info["size"]:
            bad.append(rel)
    return bad


def load_order_name(priority: int, name: str, width: int = 1) -> str:
    """'7 ConsoleVisuals' style folder names for loaders that rank folders alphabetically."""
    return f"{priority:0{width}d} {name}"
