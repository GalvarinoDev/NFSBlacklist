"""
config.py - the app's JSON settings file

Thread-safe, mtime-cached, and every load() returns a deep copy so callers
can never share nested dicts by accident (a shared default dict once kept
games marked as set up after a config reset).

save() is atomic (temp file + rename). A file that does not parse is moved
aside to <name>.corrupt-<time> and defaults are returned, so the next save
cannot silently overwrite the user's setup.

Projects add their own keys with identity.CONFIG_DEFAULTS (optional).
"""

import copy
import json
import os
import re
import threading
from datetime import datetime

import identity
from .files import write_json
from .log import get_logger

_log = get_logger(__name__)

CONFIG_PATH = identity.CONFIG_PATH

DEFAULTS = {
    "first_run_complete": False,
    "os_type": None,              # detect_hw OS key: steamos, bazzite, cachyos, armada, other
    "device": None,               # detect_hw.DEVICES key, e.g. sd_oled, rog_ally, general_pc
    "gyro_mode": None,            # on (aim/ADS), hold, toggle, off
    "play_mode": None,            # handheld or docked
    "external_controller": None,  # playstation, xbox, steamcontroller, other
    "docked_resolution": None,    # e.g. 1920x1080, or "own" (user sets it in game)
    "player_name": None,
    "steam_root": None,
    "ge_proton_version": None,    # whatever was downloaded or found; never hardcoded
    "setup_games": {},            # {key: {client, source, setup_at, ...}}
    "launch_menus": {},           # engine.appinfo: {appid: [entries]} re-applied when Steam closes
    "mods": {},                   # engine.mods: {mod_id: {version, digest, options, installed_at}}
    "music_enabled": True,
}
DEFAULTS.update(getattr(identity, "CONFIG_DEFAULTS", {}))

_lock = threading.Lock()
_cache = None
_mtime = 0.0


def load() -> dict:
    global _cache, _mtime
    with _lock:
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            return copy.deepcopy(DEFAULTS)
        if _cache is not None and mtime == _mtime:
            return copy.deepcopy(_cache)
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("config root is not an object")
        except ValueError:
            bad = f"{CONFIG_PATH}.corrupt-{datetime.now():%Y%m%d-%H%M%S}"
            try: os.replace(CONFIG_PATH, bad); _log.warning("config unreadable, moved to %s", bad)
            except OSError as ex: _log.warning("config unreadable and not moved aside: %s", ex)
            return copy.deepcopy(DEFAULTS)
        except OSError:
            return copy.deepcopy(DEFAULTS)
        merged = copy.deepcopy(DEFAULTS)
        merged.update(data)
        _cache, _mtime = merged, mtime
        return copy.deepcopy(_cache)


def save(config: dict):
    global _cache, _mtime
    with _lock:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        write_json(CONFIG_PATH, config)
        _cache, _mtime = None, 0.0


def get(key: str, default=None):
    v = load().get(key)
    return default if v is None else v


def put(key: str, value):
    c = load(); c[key] = value; save(c)


def update(**fields):
    c = load(); c.update(fields); save(c)


def reset():
    """Delete the config. Callers decide what else a reset clears."""
    global _cache, _mtime
    with _lock:
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
        _cache, _mtime = None, 0.0


# --- setup state

def mark_game_setup(key: str, client: str, source: str = "steam", **extra):
    c = load()
    c["setup_games"][key] = {"client": client, "source": source,
                             "setup_at": datetime.now().isoformat(), **extra}
    save(c)


def unmark_game_setup(keys):
    keys = [keys] if isinstance(keys, str) else list(keys)
    c = load()
    if [c["setup_games"].pop(k) for k in keys if k in c["setup_games"]]:
        save(c)


def setup_games() -> dict:
    return load().get("setup_games", {})


def is_first_run() -> bool:
    return not load().get("first_run_complete")


def complete_first_run(steam_root: str):
    update(first_run_complete=True, steam_root=steam_root)


# --- device helpers (the device table lives in detect_hw)

def device() -> dict:
    """The DEVICES entry for the saved device, general_pc if unset."""
    from .detect_hw import DEVICES
    return DEVICES.get(load().get("device") or "general_pc", DEVICES["general_pc"])


def resolution() -> str:
    """Resolution game configs should target: the docked choice, else the device's own."""
    c = load()
    if c.get("play_mode") == "docked" and c.get("docked_resolution") not in (None, "own"):
        return c["docked_resolution"]
    return device()["resolution"]


def steam_display_name(steam_root: str = None) -> str | None:
    """PersonaName of the most recent Steam login, used to pre-fill the player name."""
    path = os.path.join(steam_root or os.path.expanduser("~/.local/share/Steam"), "config", "loginusers.vdf")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    first = recent = None
    for block in re.split(r'"\d{17}"\s*\{', text)[1:]:
        m = re.search(r'"PersonaName"\s+"([^"]*)"', block)
        if not m:
            continue
        first = first or m.group(1)
        if re.search(r'"MostRecent"\s+"1"', block):
            recent = m.group(1)
    return recent or first
