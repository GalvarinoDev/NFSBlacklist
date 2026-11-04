"""
uninstall.py - undo everything the app did to Steam and the games

Run by shell/uninstall.sh after it closed Steam and before it deletes the
app folder:

    python3 -m engine.uninstall [--backup-saves] [--keep-mods]

Doing the undo in Python, with the same modules that made the changes,
means one implementation. (A bash uninstaller that re-implements binary
VDF parsing and the shortcut CRC in embedded snippets drifts from the
real code with every change.) The app folder is deleted last by the shell
script, so a failed run can simply be run again.

Order: project hook, mods (restores original files), launch menus,
shortcuts, launch options / compat tools / configsets (ledger), templates.
Steam game prefixes and save folders are never deleted.
"""

import glob
import os
import sys

from . import appinfo, config, mods, shortcuts, steam, steam_config
from .controller import templates_dir
from .log import get_logger, setup_logging

_log = get_logger("uninstall")


def say(msg):
    print(msg, flush=True)
    _log.info(msg)


def main(argv):
    setup_logging()
    if steam.is_running():
        say("Steam is running. Close Steam first.")
        return 2
    root = config.get("steam_root") or steam.STEAM_ROOT
    try:
        import games
        from . import detect
        found = detect.find_all(root)
    except Exception as ex:
        games, found = None, {}
        say(f"games.py unavailable ({ex}); project-specific cleanup skipped")

    if "--backup-saves" in argv and games:
        from . import save_backup
        for key, g in found.items():
            compat = steam.find_compatdata(g["appid"], root) if g.get("appid") else None
            save_backup.backup(key, g, compat, say)

    if games and hasattr(games, "uninstall"):
        try:
            games.uninstall(found, say)
        except Exception as ex:
            say(f"project uninstall step failed: {ex}")

    if "--keep-mods" not in argv:
        for rec in glob.glob(os.path.join(mods.RECEIPTS, "*.json")):
            key = os.path.basename(rec)[:-5]
            g = found.get(key)
            if not g:
                say(f"{key}: game not found, its mod files stay")
                continue
            mods.remove_all(g["install_dir"], key, on_progress=say)

    try:
        appinfo.remove_all(root); say("Launch menus removed")
    except Exception as ex:
        say(f"Launch menus: {ex}")
    try:
        n = shortcuts.remove_ours(root); say(f"{n} shortcut(s) removed")
    except Exception as ex:
        say(f"Shortcuts: {ex}")
    try:
        steam_config.undo_all(root, say); say("Steam settings restored")
    except Exception as ex:
        say(f"Steam settings: {ex}")
    # Exactly the names this project ships: a glob on APP_ID could match another project's
    from .controller import ASSETS
    for f in os.listdir(ASSETS) if os.path.isdir(ASSETS) else []:
        try: os.remove(os.path.join(templates_dir(root), f))
        except OSError: pass
    say("Done. The shell script removes the app folder next.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
