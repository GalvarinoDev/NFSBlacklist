"""
xtended_input.py - XtendedInput installer

Downloads and installs XtendedInput for each NFS game. This mod provides
native XInput support, console button prompts, and proper analog controls.
Essential for controller play on Steam Deck.

Two separate repos by xan1242:
  - NFSU + NFSU2: xan1242/NFSU-XtendedInput (uses NFSU_XtendedInput.asi)
  - NFSMW + NFSC: xan1242/NFS-XtendedInput  (uses NFS_XtendedInput.asi)

Install order: XtendedInput goes after Widescreen Fix and Extra Options.
We skip dinput8.dll since the Widescreen Fix already placed it.

Zip layouts (all flat, verified from actual release zips):

  UG (Release-UG-Pack.zip):
    - dinput8.dll                    (skipped)
    - scripts/NFSU_XtendedInput.asi  -> scripts/
    - scripts/NFSU_XtendedInput.ini  -> scripts/
    - Global/UG_ConsoleButtons.tpk   -> Global/  (capital G, lowercase rest)
    - EventReference.txt             (skipped)
    - README.md                      (skipped)

  UG2 (Release-UG2-Pack.zip):
    - dinput8.dll                    (skipped)
    - scripts/NFSU_XtendedInput.asi  -> scripts/
    - scripts/NFSU_XtendedInput.ini  -> scripts/
    - EventReference.txt             (skipped)
    - README.md                      (skipped)
    (no TPK folder)

  MW (Release-MW-Pack.zip):
    - dinput8.dll                        (skipped)
    - scripts/NFS_XtendedInput.asi       -> scripts/
    - scripts/NFS_XtendedInput.ini       -> scripts/
    - scripts/NFS_XtendedInput.default.ini -> scripts/
    - scripts/nfs_cursor.cur             -> scripts/
    - GLOBAL/XtendedInputButtons.tpk     -> GLOBAL/ (all caps)
    - EventReference.txt                 (skipped)
    - README.md                          (skipped)

  Carbon (Release-Carbon-Pack.zip):
    - same layout as MW

Case sensitivity matters on Linux:
  - NFSU uses Global/ (capital G, lowercase rest)
  - NFSMW and NFSC use GLOBAL/ (all caps)
  - NFSU2 has no TPK folder at all

Usage:
    from xtended_input import install, uninstall, is_installed

    success = install("nfsmw", "/path/to/game", on_progress=callback)
    installed = is_installed("nfsmw", "/path/to/game")
    success = uninstall("nfsmw", "/path/to/game")
"""

import os
import shutil
import tempfile
import zipfile

from log import get_logger
from net import download, DownloadError

_log = get_logger(__name__)

# -- Per-game data -------------------------------------------------------------

_GAMES = {
    "nfsu": {
        "zip_url": "https://github.com/xan1242/NFSU-XtendedInput/releases/download/2.7/Release-UG-Pack.zip",
        "zip_name": "Release-UG-Pack.zip",
        "label": "NFSU XtendedInput",
        "scripts_files": [
            "NFSU_XtendedInput.asi",
            "NFSU_XtendedInput.ini",
        ],
        # TPK folder name and contents - case-sensitive on Linux
        "tpk_folder": "Global",
        "tpk_files": ["UG_ConsoleButtons.tpk"],
    },
    "nfsu2": {
        "zip_url": "https://github.com/xan1242/NFSU-XtendedInput/releases/download/2.7/Release-UG2-Pack.zip",
        "zip_name": "Release-UG2-Pack.zip",
        "label": "NFSU2 XtendedInput",
        "scripts_files": [
            "NFSU_XtendedInput.asi",
            "NFSU_XtendedInput.ini",
        ],
        # UG2 has no TPK folder
        "tpk_folder": None,
        "tpk_files": [],
    },
    "nfsmw": {
        "zip_url": "https://github.com/xan1242/NFS-XtendedInput/releases/download/1.22/Release-MW-Pack.zip",
        "zip_name": "Release-MW-Pack.zip",
        "label": "NFSMW XtendedInput",
        "scripts_files": [
            "NFS_XtendedInput.asi",
            "NFS_XtendedInput.ini",
            "NFS_XtendedInput.default.ini",
            "nfs_cursor.cur",
        ],
        "tpk_folder": "GLOBAL",
        "tpk_files": ["XtendedInputButtons.tpk"],
    },
    "nfsc": {
        "zip_url": "https://github.com/xan1242/NFS-XtendedInput/releases/download/1.22/Release-Carbon-Pack.zip",
        "zip_name": "Release-Carbon-Pack.zip",
        "label": "NFSC XtendedInput",
        "scripts_files": [
            "NFS_XtendedInput.asi",
            "NFS_XtendedInput.ini",
            "NFS_XtendedInput.default.ini",
            "nfs_cursor.cur",
        ],
        "tpk_folder": "GLOBAL",
        "tpk_files": ["XtendedInputButtons.tpk"],
    },
}


# -- Public API ----------------------------------------------------------------

def install(game_key, install_dir, on_progress=None):
    """
    Download and install XtendedInput for a game.

    1. Download the zip from xan1242's GitHub releases
    2. Extract to a temp dir
    3. Copy scripts/ files (.asi, .ini, .default.ini, .cur) to game scripts/
    4. Copy TPK folder (Global/ or GLOBAL/) to game root if applicable
    5. Clean up temp dir

    We skip dinput8.dll since the Widescreen Fix already provides it.

    Returns True on success, False on error.
    Raises DownloadError if the download fails.
    """
    if game_key not in _GAMES:
        _log.error("xtended_input: unknown game key: %s", game_key)
        return False

    game = _GAMES[game_key]
    _log.info("xtended_input: installing %s to %s", game["label"], install_dir)

    # Make sure scripts/ exists in game dir
    scripts_dir = os.path.join(install_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="nfsbl_xi_")
    try:
        # Step 1: Download the zip
        zip_path = os.path.join(tmp_dir, game["zip_name"])
        if on_progress:
            on_progress(f"Downloading {game['label']}...")

        try:
            download(game["zip_url"], zip_path, label=game["label"])
        except Exception as e:
            raise DownloadError(
                url=game["zip_url"],
                dest=zip_path,
                label=game["label"],
                cause=e,
            )

        # Step 2: Extract the zip
        if on_progress:
            on_progress(f"Extracting {game['label']}...")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_dir)
        except zipfile.BadZipFile:
            _log.error("xtended_input: corrupt zip: %s", zip_path)
            return False

        # Step 3: Copy scripts/ files
        extracted_scripts = os.path.join(tmp_dir, "scripts")
        if not os.path.isdir(extracted_scripts):
            _log.error("xtended_input: scripts/ folder not found in zip")
            return False

        for fname in game["scripts_files"]:
            src = os.path.join(extracted_scripts, fname)
            dst = os.path.join(scripts_dir, fname)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
                _log.debug("xtended_input: copied scripts/%s", fname)
            else:
                _log.warning("xtended_input: expected file not found: %s", src)

        # Step 4: Copy TPK folder if this game has one
        if game["tpk_folder"] and game["tpk_files"]:
            tpk_folder = game["tpk_folder"]
            extracted_tpk = os.path.join(tmp_dir, tpk_folder)
            dest_tpk = os.path.join(install_dir, tpk_folder)

            if os.path.isdir(extracted_tpk):
                os.makedirs(dest_tpk, exist_ok=True)
                for fname in game["tpk_files"]:
                    src = os.path.join(extracted_tpk, fname)
                    dst = os.path.join(dest_tpk, fname)
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                        _log.debug("xtended_input: copied %s/%s",
                                   tpk_folder, fname)
                    else:
                        _log.warning("xtended_input: TPK file not found: %s",
                                     src)
            else:
                _log.warning("xtended_input: %s/ folder not found in zip",
                             tpk_folder)

        if on_progress:
            on_progress(f"Installed {game['label']}")

        _log.info("xtended_input: %s installed successfully", game["label"])
        return True

    finally:
        # Step 5: Clean up temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


def uninstall(game_key, install_dir):
    """
    Remove XtendedInput files from a game directory.

    Removes the XI .asi, .ini, and related files from scripts/, plus
    the TPK folder contents. Does not remove the TPK folder itself
    since XenonEffects may also use GLOBAL/ for NFSMW.

    Returns True on success, False on error.
    """
    if game_key not in _GAMES:
        _log.error("xtended_input: unknown game key: %s", game_key)
        return False

    game = _GAMES[game_key]
    _log.info("xtended_input: uninstalling %s from %s",
              game["label"], install_dir)

    # Remove scripts/ files
    scripts_dir = os.path.join(install_dir, "scripts")
    for fname in game["scripts_files"]:
        fpath = os.path.join(scripts_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                _log.debug("xtended_input: removed scripts/%s", fname)
            except OSError:
                _log.warning("xtended_input: failed to remove %s", fpath)

    # Remove TPK files (but not the folder - XenonEffects may use it)
    if game["tpk_folder"] and game["tpk_files"]:
        tpk_dir = os.path.join(install_dir, game["tpk_folder"])
        for fname in game["tpk_files"]:
            fpath = os.path.join(tpk_dir, fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                    _log.debug("xtended_input: removed %s/%s",
                               game["tpk_folder"], fname)
                except OSError:
                    _log.warning("xtended_input: failed to remove %s", fpath)

    _log.info("xtended_input: %s uninstalled", game["label"])
    return True


def is_installed(game_key, install_dir):
    """
    Check if XtendedInput is installed for a game.

    Looks for the .asi file in scripts/.

    Returns True if installed, False otherwise.
    """
    if game_key not in _GAMES:
        return False

    game = _GAMES[game_key]
    asi_name = game["scripts_files"][0]
    asi_path = os.path.join(install_dir, "scripts", asi_name)
    return os.path.exists(asi_path)
