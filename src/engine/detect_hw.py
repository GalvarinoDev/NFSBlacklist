"""
detect_hw.py - OS, device and CPU detection, plus the device table

Reads DMI, the ARM device tree and os-release. Everything is best effort:
a missing sysfs node or unknown string gives None, never an exception.
Leaf module (stdlib only).

DEVICES is the one table the rest of the engine reads for per-device
choices: resolution for game configs, which controller templates to
install, which configset file Steam reads for the built-in controller,
and whether the device has a gyro.
"""

import os
import platform

# controller: template family for the built-in controller
#   neptune           Steam Deck style (4 back buttons, 2 trackpads)
#   neptune_legion    Legion Go 1 (4 paddles, no left trackpad)
#   neptune_2btn      ROG Ally / MSI Claw (2 back buttons, no trackpads)
#   steamos_handheld  Legion Go 2 under SteamOS
#   triton            Steam Machine (Steam Controller 2)
# configset: name Steam uses for the built-in controller's configset file
DEVICES = {
    "sd_lcd":        {"label": "Steam Deck LCD",     "resolution": "1280x800",  "controller": "neptune",          "configset": "neptune",          "gyro": True,  "deck": True},
    "sd_oled":       {"label": "Steam Deck OLED",    "resolution": "1280x800",  "controller": "neptune",          "configset": "neptune",          "gyro": True,  "deck": True},
    "steam_machine": {"label": "Steam Machine",      "resolution": "1920x1080", "controller": "triton",           "configset": "triton",           "gyro": True,  "deck": False},
    "legion_go":     {"label": "Lenovo Legion Go",   "resolution": "1920x1200", "controller": "neptune_legion",   "configset": "neptune",          "gyro": True,  "deck": False},
    "legion_go_s":   {"label": "Lenovo Legion Go S", "resolution": "1920x1200", "controller": "neptune",          "configset": "neptune",          "gyro": True,  "deck": False},
    "legion_go_2":   {"label": "Lenovo Legion Go 2", "resolution": "1920x1200", "controller": "steamos_handheld", "configset": "steamos_handheld", "gyro": True,  "deck": False},
    "rog_ally":      {"label": "ROG Ally",           "resolution": "1920x1080", "controller": "neptune_2btn",     "configset": "neptune",          "gyro": True,  "deck": False},
    "rog_ally_x":    {"label": "ROG Ally X",         "resolution": "1920x1080", "controller": "neptune_2btn",     "configset": "neptune",          "gyro": True,  "deck": False},
    "xbox_ally_x":   {"label": "ROG Xbox Ally X",    "resolution": "1920x1080", "controller": "neptune_2btn",     "configset": "neptune",          "gyro": True,  "deck": False},
    "msi_claw_8":    {"label": "MSI Claw 8",         "resolution": "1920x1200", "controller": "neptune_2btn",     "configset": "neptune",          "gyro": True,  "deck": False},
    "rp6":           {"label": "Retroid Pocket 6",   "resolution": "1920x1080", "controller": "neptune",          "configset": "neptune",          "gyro": False, "deck": False},
    "general_pc":    {"label": "PC",                 "resolution": "1920x1080", "controller": "neptune",          "configset": "neptune",          "gyro": True,  "deck": False},
}

OS_LABELS = {"steamos": "SteamOS", "bazzite": "Bazzite", "cachyos": "CachyOS", "armada": "Armada", "other": "Linux"}

# product_name -> key. Lenovo uses opaque model codes.
_DMI_EXACT = {
    "Jupiter": "sd_lcd", "Galileo": "sd_oled", "Fremont": "steam_machine",
    "83E1": "legion_go", "83L3": "legion_go_s", "83N0": "legion_go_2", "83N1": "legion_go_2",
}
# ASUS repeats the model code (RC71L_RC71L), so prefix match
_DMI_PREFIX = [("RC71L", "rog_ally"), ("RC72LA", "rog_ally_x"),
               ("RC73YA", "xbox_ally_x"), ("RC73XA", "xbox_ally_x"), ("RC74XA", "xbox_ally_x")]
# MSI board_name is more reliable than product_name
_DMI_BOARD = {"MS-1T8K": "msi_claw_8", "MS-1T41": "msi_claw_8"}
# ARM handhelds have no DMI; device-tree model strings
_DT_MODEL = {"Retroid Pocket 6": "rp6", "Retroid Pocket 6 TOP-DPAD": "rp6"}

_OS_IDS = {"steamos": "steamos", "bazzite": "bazzite", "cachyos": "cachyos", "armada": "armada"}


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip("\0\n ")
    except OSError:
        return ""


def os_release() -> dict:
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path) as f:
                return {k: v.strip('"') for k, _, v in (l.strip().partition("=") for l in f) if k}
        except OSError:
            continue
    return {}


def detect_os() -> str | None:
    """steamos, bazzite, cachyos, armada, or None for anything else."""
    rel = os_release()
    hit = _OS_IDS.get(rel.get("ID", "").lower())
    if hit:
        return hit
    for like in rel.get("ID_LIKE", "").lower().split():
        if like in _OS_IDS:
            return _OS_IDS[like]
    return None


def detect_device() -> str | None:
    """A DEVICES key, or None when the hardware is unknown (callers use general_pc)."""
    product = _read("/sys/class/dmi/id/product_name")
    if product in _DMI_EXACT:
        return _DMI_EXACT[product]
    for prefix, key in _DMI_PREFIX:
        if product.startswith(prefix):
            return key
    hit = _DMI_BOARD.get(_read("/sys/class/dmi/id/board_name"))
    return hit or _DT_MODEL.get(_read("/sys/firmware/devicetree/base/model"))


def deck_serial_dmi() -> str | None:
    """The Deck's own serial (matches Steam's configset_<serial>.vdf). Decks only."""
    if not DEVICES.get(detect_device() or "", {}).get("deck"):
        return None
    return _read("/sys/class/dmi/id/product_serial") or None


def detect_arch() -> str:
    """x86_64 or aarch64. Pick release assets with this (GE-Proton has both)."""
    m = platform.machine()
    return "aarch64" if m == "arm64" else m


def is_arm() -> bool:
    return detect_arch() == "aarch64"


def is_flatpak_steam() -> bool:
    return os.path.isdir(os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam"))


def in_game_mode() -> bool:
    """True inside the gamescope session (Game Mode / Big Picture session)."""
    return bool(os.environ.get("GAMESCOPE_WAYLAND_DISPLAY")) or os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "gamescope"


if __name__ == "__main__":
    print("os:", detect_os(), "| device:", detect_device(), "| arch:", detect_arch(), "| game mode:", in_game_mode())
