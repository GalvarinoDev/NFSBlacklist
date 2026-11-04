"""
controller.py - Steam Input templates: install them and make them the default per game

Template files live in the project's assets/controllers/ and follow one
naming scheme so the engine can pick them without per-project code:

    controller_<family>_<APP_ID>_<profile>[_<gyro>].vdf

    family   built-in: neptune, neptune_legion, neptune_2btn, steamos_handheld, triton
             external: ps5, ps4, ps5_edge, xbox360, xboxone, xboxelite, generic
    profile  what the game needs, chosen by the project: "gamepad" for native
             controller support, "kbm" for keyboard/mouse emulation, or any name
    gyro     ads (gyro while aiming), hold, toggle, off; omit for pads without gyro

Lookup falls back: requested gyro, then ads, then off, then no gyro part,
so a family with only ads/off templates still resolves hold/toggle.

Where a default is written, per account (all three, each for a reason):
  1. userdata/<uid>/241100/remote/controller_config/<appid>/  "Your Layouts"
  2. Steam Controller Configs/<uid>/config/<appid>/controller_<cs>.vdf
  3. configset_controller_<cs>.vdf, the file Steam reads the active default from
On a Steam Deck, Game Mode reads configset_<serial>.vdf first. Writing only
the generic file works in Desktop Mode and silently fails in Game Mode. The
serial file also survives Steam Cloud: another device on the same account
can sync its own configset_controller_neptune.vdf over ours, never the
serial one.

Non-Steam shortcuts are looked up in Game Mode by title key, not appid
(steam.shortcut_title_key); write both. Steam must be closed.
"""

import os
import shutil

import identity
from . import config, steam
from .steam_config import patch_configset
from .log import get_logger

_log = get_logger(__name__)

ASSETS = os.path.join(identity.PROJECT_ROOT, "assets", "controllers")
GYRO_SUFFIX = {"on": "ads", "ads": "ads", "hold": "hold", "toggle": "toggle", "off": "off", None: "off"}

# Configsets per external controller choice. PlayStation covers PS4/PS5/Edge:
# Steam matches whichever pad is connected.
EXTERNAL = {
    "playstation":     ["ps5", "ps4", "ps5_edge"],
    "xbox":            ["xbox360", "xboxone", "xboxelite"],
    "steamcontroller": ["neptune", "triton"],
    "other":           ["generic"],
}
_HAS_GYRO = {"neptune", "neptune_legion", "neptune_2btn", "steamos_handheld", "triton", "ps5", "ps4", "ps5_edge"}


def templates_dir(steam_root=None) -> str:
    return os.path.join(steam_root or steam.STEAM_ROOT, "controller_base", "templates")


def template_for(family: str, profile: str, gyro: str = "off") -> str | None:
    """File name of the best matching template in assets/controllers, or None."""
    base = f"controller_{family}_{identity.APP_ID}_{profile}"
    cands = []
    if family in _HAS_GYRO:
        g = GYRO_SUFFIX.get(gyro, "off")
        cands += [f"{base}_{g}.vdf"] + ([f"{base}_ads.vdf"] if g in ("hold", "toggle") else []) + [f"{base}_off.vdf"]
    cands.append(f"{base}.vdf")
    return next((c for c in cands if os.path.isfile(os.path.join(ASSETS, c))), None)


def install_templates(on_progress=None, steam_root=None) -> int:
    """Copy every bundled template into Steam's global template folder (shows under Templates)."""
    prog = on_progress or (lambda *a: None)
    if not os.path.isdir(ASSETS):
        return 0
    dest = templates_dir(steam_root)
    os.makedirs(dest, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(ASSETS)):
        if f.endswith(".vdf"):
            shutil.copy2(os.path.join(ASSETS, f), os.path.join(dest, f)); n += 1
    prog(f"  {n} controller template(s) installed")
    return n


def _write(uid, appid, template, cs, keys, steam_root=None):
    root = steam_root or steam.STEAM_ROOT
    src = os.path.join(ASSETS, template)
    layouts = os.path.join(steam.userdata(root), uid, "241100", "remote", "controller_config", str(appid))
    os.makedirs(layouts, exist_ok=True)
    shutil.copy2(src, os.path.join(layouts, template))
    cfg_root = os.path.join(root, "steamapps", "common", "Steam Controller Configs", uid, "config")
    d = os.path.join(cfg_root, str(appid))
    os.makedirs(d, exist_ok=True)
    shutil.copy2(src, os.path.join(d, f"controller_{cs}.vdf"))
    files = [f"configset_controller_{cs}.vdf"]
    serial = steam.deck_serial(root) if cs == "neptune" else None
    if serial:
        files.append(f"configset_{serial}.vdf")
    for name in files:
        for key in [str(appid), *keys]:
            patch_configset(os.path.join(cfg_root, name), key, template)


def assign(targets: list, gyro: str = None, external: str = None, on_progress=None, steam_root=None):
    """
    Make our templates the default for each target.

    targets  -- dicts: {"appid": "12210" or shortcut appid int,
                        "profile": "gamepad",
                        "title": shortcut title (shortcuts only),
                        "names": [extra name keys Steam uses for the game, lowercase]}
    gyro     -- config gyro_mode (default: saved value)
    external -- also assign for this external controller type (playstation/xbox/...)
    """
    prog = on_progress or (lambda *a: None)
    gyro = gyro or config.get("gyro_mode", "off")
    dev = config.device()
    uids = steam.find_uids(steam_root)
    if not uids:
        prog("  No Steam account found, controller setup skipped")
        return
    if dev.get("deck") and not steam.deck_serial(steam_root):
        prog("  Deck serial not found: Game Mode may show the default layout")
    jobs = [(dev["controller"], dev["configset"])]
    if external:
        jobs += [(f, f) for f in EXTERNAL.get(external, [])]
    for t in targets:
        keys = list(t.get("names", []))
        if t.get("title"):
            keys.append(steam.shortcut_title_key(t["title"]))
        for family, cs in jobs:
            tpl = template_for(family, t.get("profile", "gamepad"), gyro if family in _HAS_GYRO else "off")
            if not tpl:
                _log.debug("no %s template for %s/%s", family, t.get("profile"), gyro)
                continue
            for uid in uids:
                _write(uid, t["appid"], tpl, cs, keys, steam_root)
            prog(f"  [{t.get('title') or t['appid']}] {tpl}")
