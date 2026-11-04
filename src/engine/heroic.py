"""
heroic.py - run a Windows game through Heroic Games Launcher (Flatpak) instead of Steam's Proton

Useful when a program misbehaves under Steam's launch or should share one
Wine prefix and login across several games. Heroic keeps sideloaded games in
sideload_apps/library.json and per-game settings in GamesConfig/<app>.json.

Rules:
  - app names are deterministic and prefixed (app_name()), so this app finds
    and removes only its own entries and never touches the user's library
  - Heroic's sandbox needs filesystem access to the game and Proton folders
    (grant_access)
  - a Steam shortcut that starts Heroic must have no compat tool: the Steam
    Linux Runtime container hides the flatpak binary (shortcuts.add(..., clear_compat=True))
  - Heroic must not be running while its JSON files are edited
"""

import base64
import hashlib
import json
import os
import subprocess

import identity
from .files import read_json, write_json, write_text
from .log import get_logger

_log = get_logger(__name__)

FLATPAK_ID = "com.heroicgameslauncher.hgl"
CONFIG_DIR = os.path.expanduser(f"~/.var/app/{FLATPAK_ID}/config/heroic")
LIBRARY = os.path.join(CONFIG_DIR, "sideload_apps", "library.json")
GAMES_CONFIG = os.path.join(CONFIG_DIR, "GamesConfig")
PREFIXES = os.path.expanduser("~/Games/Heroic/Prefixes")


def app_name(key: str) -> str:
    """Stable id for a game key. Never change the formula: shortcuts and entries are keyed on it."""
    digest = hashlib.sha256(f"{identity.APP_ID}_{key}".encode()).digest()
    # "." cannot appear in an APP_ID, so one project's prefix never matches another's
    return f"{identity.APP_ID}." + base64.urlsafe_b64encode(digest)[:16].decode()


def is_installed() -> bool:
    try:
        return subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def install(on_progress=None) -> bool:
    """Install Heroic from Flathub for the user (no root)."""
    prog = on_progress or (lambda *a: None)
    if is_installed():
        return True
    prog("Installing Heroic Games Launcher...")
    subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub",
                    "https://dl.flathub.org/repo/flathub.flatpakrepo"], capture_output=True, timeout=60)
    r = subprocess.run(["flatpak", "install", "--user", "--noninteractive", "flathub", FLATPAK_ID],
                       capture_output=True, timeout=1800)
    return r.returncode == 0


def grant_access(paths: list):
    """flatpak override --filesystem for each path (idempotent)."""
    for p in [*paths, os.path.expanduser("~/.local/share/Steam/compatibilitytools.d"), "/run/media"]:
        if p:
            subprocess.run(["flatpak", "override", "--user", FLATPAK_ID, f"--filesystem={p}"], capture_output=True, timeout=15)


def add_game(key: str, title: str, exe: str, folder: str, proton_tool: str, prefix: str = None,
             args: str = "", env: dict = None, art: str = "") -> str:
    """
    Add or update a sideload entry plus its GamesConfig. Returns the app name.
    proton_tool: folder name in compatibilitytools.d (e.g. "GE-Proton10-34").
    prefix: Wine prefix path (default ~/Games/Heroic/Prefixes/<app name>).
    """
    name = app_name(key)
    lib = read_json(LIBRARY, None) or {"games": []}
    entry = {"runner": "sideload", "app_name": name, "title": title,
             "install": {"executable": exe, "platform": "Windows", "is_dlc": False},
             "folder_name": folder, "art_cover": art, "art_square": art, "is_installed": True,
             "canRunOffline": True, "browserUrl": "", "customUserAgent": "", "launchFullScreen": False}
    lib["games"] = [g for g in lib.get("games", []) if g.get("app_name") != name] + [entry]
    os.makedirs(os.path.dirname(LIBRARY), exist_ok=True)
    write_text(LIBRARY, json.dumps(lib, indent="\t"))
    proton_bin = os.path.join(os.path.expanduser("~/.local/share/Steam/compatibilitytools.d"), proton_tool, "proton")
    cfg = {name: {
        "autoInstallDxvk": True, "autoInstallDxvkNvapi": True, "autoInstallVkd3d": True,
        "preferSystemLibs": False, "enableEsync": True, "enableFsync": True, "enableMsync": False,
        "enableWineWayland": False, "enableHDR": False, "enableWoW64": False, "nvidiaPrime": False,
        "enviromentOptions": [{"key": k, "value": str(v)} for k, v in (env or {}).items()],
        "wrapperOptions": [], "showFps": False, "useGameMode": True, "language": "",
        "beforeLaunchScriptPath": "", "afterLaunchScriptPath": "", "launcherArgs": args,
        "verboseLogs": False, "wineVersion": {"bin": proton_bin, "name": proton_tool, "type": "proton"},
        "winePrefix": prefix or os.path.join(PREFIXES, name), "wineCrossoverBottle": "",
    }, "version": "v0", "explicit": True}
    write_json(os.path.join(GAMES_CONFIG, f"{name}.json"), cfg)
    grant_access([folder, os.path.dirname(exe)])
    return name


def remove_ours():
    """Remove every sideload entry and GamesConfig this app created."""
    prefix = f"{identity.APP_ID}."
    lib = read_json(LIBRARY, None)
    if lib:
        lib["games"] = [g for g in lib.get("games", []) if not str(g.get("app_name", "")).startswith(prefix)]
        write_text(LIBRARY, json.dumps(lib, indent="\t"))
    if os.path.isdir(GAMES_CONFIG):
        for f in os.listdir(GAMES_CONFIG):
            if f.startswith(prefix) and f.endswith(".json"):
                os.remove(os.path.join(GAMES_CONFIG, f))


def launch_command(key: str) -> tuple:
    """(exe, launch options) for a Steam shortcut that starts the game through Heroic."""
    return "/usr/bin/flatpak", f"run {FLATPAK_ID} --no-gui --no-sandbox \"heroic://launch?appName={app_name(key)}&runner=sideload\""


def launch(key: str, from_steam_game: bool = False):
    """
    Start the game through Heroic from a script (a Steam game's launch option
    that hands off to Heroic). Electron's single-instance lock can make a new
    flatpak run attach to a stale Heroic and do nothing, so stop it first.
    From a Steam game's launch, Steam's pinned libcurl broke the host flatpak;
    preloading the system libcurl fixed it.
    """
    subprocess.run(["flatpak", "kill", FLATPAK_ID], capture_output=True, timeout=15)
    env = dict(os.environ)
    if from_steam_game and os.path.exists("/usr/lib/libcurl.so.4"):
        env["LD_PRELOAD"] = "/usr/lib/libcurl.so.4"
    subprocess.Popen(["/usr/bin/flatpak", "run", FLATPAK_ID, "--no-gui", "--no-sandbox",
                      f"heroic://launch?appName={app_name(key)}&runner=sideload"],
                     env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
