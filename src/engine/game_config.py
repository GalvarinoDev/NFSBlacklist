"""
game_config.py - put tuned config files in place and edit ini/cfg settings

Bundled configs live in assets/configs/ and are picked per device, per
resolution, or as a default (first match wins):

    assets/configs/<device key>/<game key>/<file>    e.g. sd_oled/mygame/settings.ini
    assets/configs/<WxH>/<game key>/<file>           e.g. 1280x800/mygame/settings.ini
    assets/configs/default/<game key>/<file>

games.GAMES[key]["configs"] lists what to deploy:

    "configs": [
        {"src": "settings.ini", "dest": "{game}/settings.ini"},
        {"src": "user.cfg", "dest": "{documents}/My Games/MyGame/user.cfg", "if_missing": True},
    ]

dest tokens: {game} {home} {prefix} (drive_c) {appdata} {localappdata}
{documents} {savedgames}. Prefix tokens need the game's compatdata.
Inside text files, %PLAYER_NAME% %WIDTH% %HEIGHT% %REFRESH% are filled in.
"""

import os
import re
import shutil

import identity
from . import config, proton, steam
from .files import ci_path, write_text
from .log import get_logger

_log = get_logger(__name__)

ASSETS = os.path.join(identity.PROJECT_ROOT, "assets", "configs")
_TEXT_EXT = {".ini", ".cfg", ".txt", ".xml", ".json", ".conf", ".lua", ".yaml", ".yml", ".toml"}


def _find_asset(key: str, src: str) -> str | None:
    dev = config.get("device") or "general_pc"
    for folder in (dev, config.resolution(), "default"):
        p = os.path.join(ASSETS, folder, key, src)
        if os.path.isfile(p):
            return p
    return None


def tokens(game: dict, compat: str = None) -> dict:
    t = {"game": game["install_dir"], "home": steam.HOME}
    if compat:
        t.update(prefix=proton.drive_c(compat), appdata=proton.appdata_roaming(compat),
                 localappdata=proton.appdata_local(compat), documents=proton.documents(compat),
                 savedgames=proton.user_dir(compat, "Saved Games"))
    return t


def fill(text: str) -> str:
    w, _, h = config.resolution().partition("x")
    h, _, hz = h.partition("_")
    return (text.replace("%PLAYER_NAME%", config.get("player_name") or "Player")
                .replace("%WIDTH%", w).replace("%HEIGHT%", h).replace("%REFRESH%", hz.rstrip("hz") or "60"))


def apply(key: str, game: dict, compat: str = None, on_progress=None) -> int:
    """Deploy every config listed for this game. Returns how many files were written."""
    prog = on_progress or (lambda *a: None)
    tok = tokens(game, compat)
    n = 0
    for c in game.get("configs", []):
        src = _find_asset(key, c["src"])
        if not src:
            _log.debug("no %s config for %s on this device", c["src"], key)
            continue
        try:
            dest = c["dest"].format(**tok)
        except KeyError as ex:
            prog(f"  {c['src']}: needs {ex} (no prefix yet), skipped")
            continue
        if c.get("if_missing") and os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.splitext(src)[1].lower() in _TEXT_EXT:
            with open(src, encoding="utf-8", errors="surrogateescape") as f:
                write_text(dest, fill(f.read()))
        else:
            shutil.copy2(src, dest)
        n += 1
        prog(f"  config: {os.path.basename(dest)}")
    return n


# --- ini / cfg editing

def set_ini(path: str, values: dict, section: str = None, sep: str = "=", create: bool = True):
    """
    Set keys in an ini-style file without disturbing the rest: comments,
    order, casing and unknown keys stay. Keys and sections match
    case-insensitively. section None means keys before the first [section].
    """
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            lines = f.read().rstrip("\n").split("\n")
    except FileNotFoundError:
        if not create:
            return
        lines = []
    sec_rx = re.compile(r"^\s*\[(.+?)\]\s*$")
    want = section.lower() if section else None
    todo = {k.lower(): (k, v) for k, v in values.items()}
    cur, found = None, section is None
    at = next((i for i, l in enumerate(lines) if sec_rx.match(l)), len(lines)) if section is None else None
    for i, line in enumerate(lines):
        m = sec_rx.match(line)
        if m:
            cur = m.group(1).lower()
            if cur == want:
                found, at = True, i + 1
            continue
        if cur != want:
            continue
        if section and line.strip():
            at = i + 1
        k = line.split(sep, 1)[0].strip()
        if sep in line and k.lower() in todo:
            _, val = todo.pop(k.lower())
            lines[i] = f"{k}{sep}{val}"
    if todo:
        new = [f"{k}{sep}{v}" for k, v in todo.values()]
        if not found:
            lines += ([""] if lines and lines[-1].strip() else []) + [f"[{section}]"] + new
        else:
            lines[at:at] = new
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    write_text(path, "\n".join(lines) + "\n")


def set_cfg(path: str, values: dict, command: str = "seta"):
    """
    id Tech / Quake-style cfg files: seta name "value". Replaces existing
    lines for each name (any of set/seta/sets/setu), appends missing ones.
    """
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            lines = f.read().split("\n")
    except FileNotFoundError:
        lines = []
    todo = dict(values)
    for i, line in enumerate(lines):
        m = re.match(r'^\s*(set[asu]?)\s+(\S+)\s', line + " ", re.I)
        if m and m.group(2).lower() in {k.lower() for k in todo}:
            name = next(k for k in todo if k.lower() == m.group(2).lower())
            lines[i] = f'{m.group(1)} {m.group(2)} "{todo.pop(name)}"'
    lines += [f'{command} {k} "{v}"' for k, v in todo.items()]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    write_text(path, "\n".join(l for l in lines if l is not None).rstrip("\n") + "\n")


def find_ci(root: str, rel: str) -> str:
    """Case-insensitive path under root (config folders differ in case between stores)."""
    return ci_path(root, rel)
