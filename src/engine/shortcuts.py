"""
shortcuts.py - non-Steam shortcuts in shortcuts.vdf, with artwork

Steam must be closed. Every shortcut this app writes carries the tag
identity.SHORTCUT_TAG, which is how remove_ours() and the uninstaller find
them without touching anything the user added.

The shortcut appid is crc32(Exe + AppName) (steam.shortcut_appid). Keep a
shortcut's Exe and name stable across versions: a new appid means a new
prefix, lost artwork, lost controller config and lost play time. When the
real exe must change, keep pointing Exe at the original and swap the exe in
the launch option instead (see engine.launch).
"""

import glob
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

import identity
from . import steam, vdf_binary as bvdf
from .files import backup_file, write_bytes
from .log import get_logger
from .net import download

_log = get_logger(__name__)

TAG = getattr(identity, "SHORTCUT_TAG", identity.APP_TITLE)

# Steam's grid file names per artwork kind; the extension comes from the URL
ART_NAMES = {"grid": "{id}p", "wide": "{id}", "hero": "{id}_hero", "logo": "{id}_logo", "icon": "{id}_icon"}


def _path(uid: str, steam_root=None) -> str:
    return os.path.join(steam.userdata(steam_root), uid, "config", "shortcuts.vdf")


def read(uid: str, steam_root=None) -> list:
    """The shortcut dicts of one account, in order. Missing file = []."""
    p = _path(uid, steam_root)
    if not os.path.isfile(p):
        return []
    root = bvdf.load(p)
    sc = next((v for k, v in root.items() if k.lower() == "shortcuts"), {})
    return [sc[k] for k in sorted(sc, key=lambda k: int(k) if k.isdigit() else 1 << 30)]


def write(uid: str, entries: list, steam_root=None):
    """
    Write entries back, reindexed from 0 (Steam stops reading at a gap).
    read() parses the whole file or raises, so a file we cannot understand
    is never rewritten with entries missing.
    """
    p = _path(uid, steam_root)
    backup_file(p)
    write_bytes(p, bvdf.dumps({"shortcuts": {str(i): e for i, e in enumerate(entries)}}))


def _get(e: dict, key: str, default=None):
    low = key.lower()
    return next((v for k, v in e.items() if k.lower() == low), default)


def appid_of(e: dict) -> int:
    return bvdf.to_unsigned32(_get(e, "appid", 0))


def is_ours(e: dict) -> bool:
    tags = _get(e, "tags", {}) or {}
    return TAG in tags.values()


def find(name: str, steam_root=None) -> int | None:
    """Appid of the first shortcut named name in any account (what Steam really uses)."""
    for uid in steam.find_uids(steam_root):
        for e in read(uid, steam_root):
            if _get(e, "AppName") == name:
                return appid_of(e)
    return None


def quote(path: str) -> str:
    return f'"{path}"'


def make_entry(name: str, exe: str, start_dir: str = None, launch_options: str = "",
               icon: str = "", tags: list = (), appid: int = None, hidden: bool = False) -> dict:
    """
    exe and start_dir are file paths; they are quoted here the way Steam
    quotes them. appid defaults to Steam's own formula.
    """
    q_exe = quote(exe) if not exe.startswith('"') else exe
    q_dir = quote(start_dir or os.path.dirname(exe.strip('"')))
    aid = appid or steam.shortcut_appid(q_exe, name)
    return {
        "appid": bvdf.to_signed32(aid), "AppName": name, "Exe": q_exe, "StartDir": q_dir,
        "icon": icon, "ShortcutPath": "", "LaunchOptions": launch_options,
        "IsHidden": int(hidden), "AllowDesktopConfig": 1, "AllowOverlay": 1, "OpenVR": 0,
        "Devkit": 0, "DevkitGameID": "", "DevkitOverrideAppID": 0, "LastPlayTime": 0,
        "FlatpakAppID": "", "sortas": "",
        "tags": {str(i): t for i, t in enumerate([TAG, *tags])},
    }


def add(name: str, exe: str, start_dir: str = None, launch_options: str = "", art: dict = None,
        compat_tool: str = None, clear_compat: bool = False, appid_exe: str = None,
        on_progress=None, steam_root=None) -> int:
    """
    Add or replace (by name) a shortcut in every account. Returns its appid.

    art          -- {"grid"|"wide"|"hero"|"logo"|"icon": url}
    compat_tool  -- Proton folder name to run it with (Windows exe)
    clear_compat -- remove any mapping (native scripts, flatpak launches)
    appid_exe    -- exe path used for the appid instead of exe, so the appid
                    stays the same when the real exe changes
    Replacing keeps LastPlayTime.
    """
    prog = on_progress or (lambda *a: None)
    q_exe = quote(appid_exe or exe)
    aid = steam.shortcut_appid(q_exe, name)
    uids = steam.find_uids(steam_root)
    if not uids:
        prog("  No Steam account found, shortcut skipped")
        return aid
    for uid in uids:
        entries = read(uid, steam_root)
        old = [e for e in entries if _get(e, "AppName") == name]
        entries = [e for e in entries if _get(e, "AppName") != name]
        icon = _art_path(uid, aid, "icon", (art or {}).get("icon"), steam_root) if art and art.get("icon") else ""
        e = make_entry(name, exe, start_dir, launch_options, icon, appid=aid)
        if old:
            e["LastPlayTime"] = _get(old[0], "LastPlayTime", 0)
        entries.append(e)
        write(uid, entries, steam_root)
        prog(f"  {'Updated' if old else 'Added'} shortcut: {name}")
        if art:
            download_art(uid, aid, art, steam_root=steam_root)
    from . import steam_config
    try:
        if clear_compat:
            steam_config.clear_compat_tool([aid], steam_root)
        elif compat_tool:
            steam_config.set_compat_tool([aid], compat_tool, steam_root)
    except Exception as ex:
        prog(f"  Could not set the compat tool: {ex}")
    return aid


def remove(name: str = None, appid: int = None, steam_root=None, remove_art: bool = True) -> int:
    """Remove shortcuts by name or appid from every account. Returns how many went."""
    n = 0
    for uid in steam.find_uids(steam_root):
        entries = read(uid, steam_root)
        keep = [e for e in entries if not ((name and _get(e, "AppName") == name) or (appid and appid_of(e) == appid))]
        gone = [e for e in entries if e not in keep]
        if gone:
            write(uid, keep, steam_root)
            n += len(gone)
            if remove_art:
                for e in gone:
                    delete_art(uid, appid_of(e), steam_root)
    return n


def remove_ours(steam_root=None, keep: set = frozenset()) -> int:
    """Remove every shortcut tagged with TAG except names in keep (uninstall, repair)."""
    n = 0
    for uid in steam.find_uids(steam_root):
        entries = read(uid, steam_root)
        keep_e = [e for e in entries if not is_ours(e) or _get(e, "AppName") in keep]
        gone = [e for e in entries if e not in keep_e]
        if gone:
            write(uid, keep_e, steam_root)
            for e in gone:
                delete_art(uid, appid_of(e), steam_root)
            n += len(gone)
    return n


def ours(steam_root=None) -> list:
    """[(uid, entry)] of every shortcut this app made."""
    return [(uid, e) for uid in steam.find_uids(steam_root) for e in read(uid, steam_root) if is_ours(e)]


# --- artwork

def _grid(uid, steam_root=None):
    return os.path.join(steam.userdata(steam_root), uid, "config", "grid")


def _art_path(uid, appid, kind, url, steam_root=None):
    ext = os.path.splitext(url.split("?")[0])[1] or ".png"
    return os.path.join(_grid(uid, steam_root), ART_NAMES[kind].format(id=appid) + ext)


def download_art(uid: str, appid: int, art: dict, force: bool = False, steam_root=None):
    """
    Download grid/wide/hero/logo/icon art for an appid (a shortcut, or a real
    Steam game to replace its art). Stale files with another extension are
    removed first, or Steam may keep showing the old one.
    """
    jobs = []
    for kind, url in art.items():
        if kind not in ART_NAMES or not url:
            continue
        dest = _art_path(uid, appid, kind, url, steam_root)
        if os.path.exists(dest) and not force:
            continue
        for old in glob.glob(os.path.join(_grid(uid, steam_root), ART_NAMES[kind].format(id=appid) + ".*")):
            if old != dest:
                try: os.remove(old)
                except OSError: pass
        jobs.append((url, dest))
    if not jobs:
        return
    def get(job):
        try:
            download(job[0], job[1], timeout=30, tries=2)
        except Exception as ex:
            _log.debug("artwork %s failed: %s", job[0], ex)
    with ThreadPoolExecutor(max_workers=min(5, len(jobs))) as ex:
        list(ex.map(get, jobs))


def copy_art(uid: str, appid: int, files: dict, steam_root=None):
    """Use bundled artwork: files = {kind: local path}."""
    os.makedirs(_grid(uid, steam_root), exist_ok=True)
    for kind, src in files.items():
        if kind in ART_NAMES and os.path.isfile(src):
            shutil.copy2(src, os.path.join(_grid(uid, steam_root), ART_NAMES[kind].format(id=appid) + os.path.splitext(src)[1]))


def delete_art(uid: str, appid: int, steam_root=None):
    for kind in ART_NAMES.values():
        for f in glob.glob(os.path.join(_grid(uid, steam_root), kind.format(id=appid) + ".*")):
            try: os.remove(f)
            except OSError: pass
