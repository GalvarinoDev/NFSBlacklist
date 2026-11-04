"""
steam.py - Steam install layout, libraries, accounts and the Steam process

Leaf-ish module (stdlib, log, files, detect_hw). Everything that only needs
to know where Steam keeps things lives here, so any other module can use
it without import cycles.
"""

import binascii
import glob
import os
import re
import subprocess
import time

from .log import get_logger

_log = get_logger(__name__)

HOME = os.path.expanduser("~")
STEAM_ROOTS = [
    os.path.join(HOME, ".local/share/Steam"),
    os.path.join(HOME, ".steam/steam"),
    os.path.join(HOME, ".steam/root"),
    os.path.join(HOME, ".steam/debian-installation"),
    os.path.join(HOME, ".var/app/com.valvesoftware.Steam/data/Steam"),  # Flatpak Steam
]
# Removable drives: SteamOS mounts under /run/media/deck/<label>, Bazzite and
# CachyOS under /run/media/<login>/<label>, old SteamOS under /run/media/<label>
MEDIA_GLOBS = ["/run/media/*/*", "/run/media/*"]

# Steam user folders below this are system placeholders (0, anonymous), not accounts
MIN_UID = 10000

# Steam process match. pkill on this asks the client to shut down cleanly.
_STEAM_PROC = "ubuntu12_32/steam"


def find_steam_root() -> str | None:
    for p in STEAM_ROOTS:
        if os.path.isdir(os.path.join(p, "steamapps")):
            return os.path.normpath(p)  # not realpath: keep /home and /var/home forms from mixing
    return None


STEAM_ROOT = find_steam_root() or STEAM_ROOTS[0]


def userdata(steam_root: str = None) -> str:
    return os.path.join(steam_root or STEAM_ROOT, "userdata")


def config_vdf(steam_root: str = None) -> str:
    return os.path.join(steam_root or STEAM_ROOT, "config", "config.vdf")


def find_uids(steam_root: str = None) -> list:
    """Every real account folder in userdata/, symlinked duplicates removed."""
    base = userdata(steam_root)
    if not os.path.isdir(base):
        return []
    seen, out = set(), []
    for e in sorted(os.listdir(base)):
        if not e.isdigit() or int(e) < MIN_UID:
            continue
        real = os.path.realpath(os.path.join(base, e))
        if real not in seen:
            seen.add(real); out.append(e)
    return out


# --- libraries

def library_dirs(steam_root: str = None) -> list:
    """
    Every steamapps/ folder: the main one, every path in libraryfolders.vdf,
    plus any removable drive that has one (the vdf can lag behind a card
    that was just inserted). Deduplicated by real path.
    """
    root = steam_root or STEAM_ROOT
    seen, out = set(), []

    def add(p):
        real = os.path.realpath(p)
        if os.path.isdir(p) and real not in seen:
            seen.add(real); out.append(os.path.normpath(p))

    add(os.path.join(root, "steamapps"))
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, encoding="utf-8", errors="replace") as f:
            for p in re.findall(r'"path"\s+"([^"]+)"', f.read()):
                p = p.replace("\\\\", "\\")
                add(os.path.join(p, "steamapps"))
                add(os.path.join(p, "SteamLibrary", "steamapps"))
    except OSError:
        pass
    for pattern in MEDIA_GLOBS:
        for m in glob.glob(pattern):
            add(os.path.join(m, "steamapps"))
            add(os.path.join(m, "SteamLibrary", "steamapps"))
    return out


def read_acf(path: str) -> dict:
    """Flat key/values of an appmanifest_*.acf (installdir, StateFlags, buildid, name...)."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for k, v in re.findall(r'^\s*"([^"]+)"\s+"([^"]*)"', f.read(), re.M):
                out.setdefault(k, v)
    except OSError:
        pass
    return out


# StateFlags bit 4 = fully installed. Anything else is downloading, updating
# or a stale manifest left by an uninstalled game.
FULLY_INSTALLED = 4


def find_app(appid, steam_root: str = None) -> dict | None:
    """
    {appid, install_dir, library, acf} of a fully installed Steam app, or None.
    install_dir must exist; a manifest without its folder is ignored.
    """
    for lib in library_dirs(steam_root):
        acf = os.path.join(lib, f"appmanifest_{appid}.acf")
        if not os.path.isfile(acf):
            continue
        info = read_acf(acf)
        if not info.get("installdir"):
            continue
        if info.get("StateFlags") != str(FULLY_INSTALLED):
            _log.debug("app %s StateFlags %s, skipped", appid, info.get("StateFlags"))
            continue
        d = os.path.join(lib, "common", info["installdir"])
        if os.path.isdir(d):
            return {"appid": str(appid), "install_dir": d, "library": lib, "acf": info}
    return None


def owned_dlc(appid, steam_root: str = None) -> set:
    """DLC appids listed as installed in the game's appmanifest."""
    for lib in library_dirs(steam_root):
        acf = os.path.join(lib, f"appmanifest_{appid}.acf")
        if os.path.isfile(acf):
            with open(acf, encoding="utf-8", errors="replace") as f:
                text = f.read()
            m = re.search(r'"InstalledDepots"\s*\{(.*?)\n\t\}', text, re.S)
            return set(re.findall(r'"dlcappid"\s+"(\d+)"', m.group(1) if m else text))
    return set()


def compatdata(appid, steam_root: str = None) -> str:
    """
    Proton prefix path for appid on the internal drive. All prefixes the
    engine manages live there: SD card prefixes are slow and a card swap
    leaves Steam pointing at a missing prefix.
    """
    return os.path.join(steam_root or STEAM_ROOT, "steamapps", "compatdata", str(appid))


def find_compatdata(appid, steam_root: str = None) -> str | None:
    """Existing prefix for appid in any library (Steam may have made it on the card)."""
    for lib in library_dirs(steam_root):
        p = os.path.join(lib, "compatdata", str(appid))
        if os.path.isdir(p):
            return p
    return None


# --- non-Steam shortcut identity

def shortcut_appid(exe: str, name: str) -> int:
    """
    Steam's appid for a non-Steam shortcut: crc32(exe + name) with the top
    bit set. exe is exactly what goes in the shortcut's Exe field, quotes
    included. Artwork, prefixes and controller configs are keyed on this.
    Do not change.
    """
    return (binascii.crc32((exe + name).encode("utf-8")) & 0xFFFFFFFF) | 0x80000000


def shortcut_gameid(appid: int) -> int:
    """64-bit game id for steam://rungameid/<id> links to a shortcut."""
    return (appid << 32) | 0x02000000


def shortcut_title_key(title: str) -> str:
    """
    Configset key Game Mode reads for a non-Steam shortcut's controller
    template: the title lowercased without / \\ ? % * : | " < > .
    Game Mode ignores the numeric appid key for shortcuts.
    """
    return re.sub(r'[/\\?%*:|"<>.]', "", title.lower())


def deck_serial(steam_root: str = None) -> str | None:
    """
    Steam Deck serial for configset_<serial>.vdf, or None. config.vdf's
    SteamDeckRegisteredSerialNumber first (absent on at least some stock
    OLEDs), then the DMI product serial on a Deck. Best effort by design:
    callers skip the serial write when this is None.
    """
    try:
        with open(config_vdf(steam_root), encoding="utf-8", errors="replace") as f:
            m = re.search(r'"SteamDeckRegisteredSerialNumber"\s+"([^"]+)"', f.read())
        if m:
            return m.group(1)
    except OSError:
        pass
    from .detect_hw import deck_serial_dmi
    return deck_serial_dmi()


# --- the Steam process

def is_running() -> bool:
    return subprocess.run(["pgrep", "-f", _STEAM_PROC], capture_output=True).returncode == 0


_on_closed = []


def on_closed(fn):
    """Register fn() to run every time kill_steam confirms Steam is closed (launch menu re-apply)."""
    if fn not in _on_closed:
        _on_closed.append(fn)


def _closed():
    for fn in _on_closed:
        try:
            fn()
        except Exception:
            _log.debug("on_closed hook failed", exc_info=True)


def kill_steam(on_progress=None, timeout: int = 120):
    """
    Ask Steam to close and wait for it. Never SIGKILL: a killed Steam can
    leave localconfig.vdf half written, lose the edits made while it was
    closed, or trigger the SteamOS first-run wizard. SIGTERM to the client
    process shuts it down cleanly without the session manager switching to
    Game Mode.

    Raises TimeoutError when Steam is still running after `timeout` seconds.
    """
    if not is_running():
        _closed()
        return
    subprocess.run(["pkill", "-TERM", "-f", _STEAM_PROC], capture_output=True)
    if on_progress:
        on_progress("Waiting for Steam to close safely...")
    deadline = time.time() + timeout
    n = 0
    while time.time() < deadline:
        if not is_running():
            # Steam writes its VDFs during shutdown; let the writes land
            time.sleep(3)
            subprocess.run(["sync"], capture_output=True)
            _closed()
            return
        time.sleep(1)
        n += 1
        if on_progress and n % 10 == 0:
            on_progress("Still waiting for Steam to close...")
    raise TimeoutError(f"Steam did not close within {timeout} seconds. Close Steam and try again.")


def launch_steam(uri: str = None):
    """
    Start Steam, or open a steam:// URI, fully detached: Steam must never be
    a child of the app, or closing the app (or a crash) takes Steam with it.
    """
    cmd = ["xdg-open", uri] if uri else ["steam"]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        _log.info("launched %s (detached)", " ".join(cmd))
    except FileNotFoundError:
        if not uri:
            subprocess.Popen(["gtk-launch", "steam.desktop"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def steam_uri(action: str, appid) -> str:
    """steam://install/<id>, steam://validate/<id>, steam://run/<id>, steam://rungameid/<id>."""
    return f"steam://{action}/{appid}"
