"""
save_backup.py - copy player saves out before uninstall/reinstall, put them back after

Backups live in identity.DATA_DIR/save_backup/<key>/<n>/, outside the app
folder, so they survive an uninstall. Restore is always user initiated
(never silent) and the current save folder is first copied to
<folder>.pre-restore.

games.GAMES[key]["saves"] lists save folders with the same tokens as
game_config ({game} {documents} {appdata} {localappdata} {savedgames} {home}):

    "saves": ["{game}/players", "{documents}/My Games/MyGame/Saves"]

Saves under a Proton prefix are only found when the prefix exists; the
caller passes compatdata.
"""

import json
import os
import shutil
from datetime import datetime

import identity
from .game_config import tokens
from .log import get_logger

_log = get_logger(__name__)

ROOT = os.path.join(identity.DATA_DIR, "save_backup")


def _sources(game: dict, compat: str = None) -> list:
    tok = tokens(game, compat)
    out = []
    for s in game.get("saves", []):
        try:
            out.append(s.format(**tok))
        except KeyError:
            continue
    return out


def backup(key: str, game: dict, compat: str = None, on_progress=None) -> int:
    prog = on_progress or (lambda *a: None)
    n = 0
    for i, src in enumerate(_sources(game, compat)):
        if not os.path.isdir(src) or not os.listdir(src):
            continue
        dst = os.path.join(ROOT, key, str(i))
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=True)
        n += 1
        prog(f"  backed up {src}")
    if n:
        info_path = os.path.join(ROOT, "backup_info.json")
        try:
            info = json.load(open(info_path))
        except (OSError, ValueError):
            info = {}
        info[key] = {"at": datetime.now().isoformat(timespec="seconds"), "sources": _sources(game, compat)}
        os.makedirs(ROOT, exist_ok=True)
        from .files import write_json
        write_json(info_path, info)
    return n


def restore(key: str, game: dict, compat: str = None, on_progress=None) -> int:
    prog = on_progress or (lambda *a: None)
    n = 0
    for i, dst in enumerate(_sources(game, compat)):
        src = os.path.join(ROOT, key, str(i))
        if not os.path.isdir(src):
            continue
        if os.path.isdir(dst) and os.listdir(dst):
            keep = dst + ".pre-restore"
            shutil.rmtree(keep, ignore_errors=True)
            shutil.copytree(dst, keep)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        n += 1
        prog(f"  restored {dst}")
    return n


def has_backup(key: str = None) -> bool:
    d = os.path.join(ROOT, key) if key else ROOT
    return os.path.isdir(d) and any(os.scandir(d))


def clear(key: str = None):
    shutil.rmtree(os.path.join(ROOT, key) if key else ROOT, ignore_errors=True)
