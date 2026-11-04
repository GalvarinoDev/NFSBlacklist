"""
detect.py - find the project's games: Steam installs and copies the user owns elsewhere

Driven entirely by games.GAMES (see template/src/games.py). Per game:

    appid         Steam appid, or None for games not sold on Steam
    exe           main exe, relative to the game root
    subdir        game root inside the Steam install folder, if not the folder itself
    sentinels     files that prove a folder is this game (relative to the game root);
                  pick files mods and launchers never touch, e.g. a base-game data
                  file, not the exe (mods rename or replace exes)
    own_folders   exact folder names (case-insensitive) of non-Steam copies
    own_keywords  regexes matched against folder names, checked in GAMES order

Steam: appmanifest_<appid>.acf in any library with StateFlags 4 and the exe
or a sentinel present. Own copies: walk ~/Games and Games/ on every drive
(plus folders the user picked), match folder names, then confirm with a
sentinel up to 3 levels down (copies are often nested one folder deeper).
A name match without a sentinel is skipped: incomplete or wrong install.
"""

import glob
import os
import re

from . import steam
from .log import get_logger

_log = get_logger(__name__)

OWN_SCAN = [os.path.join(steam.HOME, "Games"), os.path.join(steam.HOME, "games"),
            "/run/media/*/*/Games", "/run/media/*/*/games", "/run/media/*/Games", "/run/media/*/games"]
MAX_DEPTH = 5
SENTINEL_DEPTH = 3
_SKIP = {".steam", ".local", ".cache", ".config", "__pycache__", "compatdata", "shadercache"}


def _games() -> dict:
    import games
    return games.GAMES


def _has_sentinel(root: str, meta: dict) -> bool:
    sents = meta.get("sentinels") or [meta["exe"]]
    for s in sents:
        if os.path.exists(os.path.join(root, s)):
            return True
        # case-insensitive fallback: copies from discs and other stores vary in casing
        from .files import ci_path
        if os.path.exists(ci_path(root, s)):
            return True
    return False


def _game_root(cand: str, meta: dict) -> str | None:
    if _has_sentinel(cand, meta):
        return cand
    for d, subs, _ in os.walk(cand):
        depth = os.path.relpath(d, cand).count(os.sep) + (d != cand)
        if depth >= SENTINEL_DEPTH:
            subs.clear()
            continue
        subs[:] = [s for s in subs if not s.startswith(".")]
        if d != cand and _has_sentinel(d, meta):
            return d
    return None


def _entry(key, meta, root, source):
    from .files import ci_path
    exe = ci_path(root, meta["exe"])
    if not os.path.exists(exe):
        exe = next((ci_path(root, a) for a in meta.get("exe_alt", []) if os.path.exists(ci_path(root, a))), exe)
    return {**meta, "key": key, "install_dir": root, "exe_path": exe, "source": source}


def find_steam(steam_root: str = None) -> dict:
    found = {}
    for key, meta in _games().items():
        if not meta.get("appid"):
            continue
        app = steam.find_app(meta["appid"], steam_root)
        if not app:
            continue
        root = os.path.join(app["install_dir"], meta["subdir"]) if meta.get("subdir") else app["install_dir"]
        if os.path.isdir(root) and _has_sentinel(root, meta):
            # buildid: the Steam build; mods often support only some builds
            found[key] = {**_entry(key, meta, root, "steam"), "library": app["library"],
                          "buildid": app["acf"].get("buildid"), "steam_dir": app["install_dir"]}
    return found


def _match(name: str) -> list:
    low = name.lower()
    hits = [k for k, m in _games().items() if low in (f.lower() for f in m.get("own_folders", []))]
    if hits:
        return hits
    for k, m in _games().items():
        if any(re.search(p, name, re.I) for p in m.get("own_keywords", [])):
            hits.append(k)
    return hits


def scan_dirs(extra: list = None) -> list:
    seen, out = set(), []
    for pattern in OWN_SCAN + list(extra or []):
        for p in glob.glob(pattern):
            real = os.path.realpath(p)
            if os.path.isdir(p) and real not in seen:
                seen.add(real); out.append(os.path.normpath(p))
    return out


def find_own(extra: list = None, on_progress=None) -> dict:
    prog = on_progress or (lambda *a: None)
    found = {}
    for base in scan_dirs(extra):
        prog(f"Scanning {base}...")
        for d, subs, _ in os.walk(base):
            depth = os.path.relpath(d, base).count(os.sep) + (d != base)
            if depth >= MAX_DEPTH:
                subs.clear()
                continue
            subs[:] = [s for s in subs if not s.startswith(".") and s not in _SKIP]
            keys = [k for k in _match(os.path.basename(d)) if k not in found]
            confirmed = False
            for k in keys:
                root = _game_root(d, _games()[k])
                if root:
                    found[k] = _entry(k, _games()[k], root, "own")
                    prog(f"  found {_games()[k]['name']} at {root}")
                    confirmed = True
            if confirmed:
                subs.clear()  # don't descend into a confirmed game
    return found


def find_all(steam_root: str = None, extra: list = None, on_progress=None) -> dict:
    """Steam and own copies in one dict. A Steam install wins when both exist."""
    out = find_own(extra, on_progress)
    out.update(find_steam(steam_root))
    return out
