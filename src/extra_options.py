"""
extra_options.py - Extra Options plugin installer

Downloads and installs Extra Options for each NFS game from the
ExOptsTeam GitHub releases. Extra Options provides bug fixes, QoL
improvements, and gameplay enhancements.

Install order: Extra Options goes after Widescreen Fix (which provides
the dinput8.dll ASI loader). We only copy the .asi and .ini into
scripts/ - we do NOT overwrite dinput8.dll since the Widescreen Fix
already placed a newer version.

Zip layouts (verified from actual release zips):
  NFSU, NFSU2, NFSMW: flat layout
    - dinput8.dll       (skipped - WSF already provides this)
    - Read Me.txt       (skipped)
    - scripts/*.asi     -> game root/scripts/
    - scripts/*.ini     -> game root/scripts/

  NFSC: has a Main Files/ subfolder
    - Main Files/dinput8.dll       (skipped)
    - Main Files/scripts/*.asi     -> game root/scripts/
    - Main Files/scripts/*.ini     -> game root/scripts/
    - Read Me.txt                  (skipped)

No INI patching needed - the defaults are good as-is. ForceBlackEdition
(NFSMW) and ForceCollectorsEdition (NFSC) are already enabled by
default in the stock INIs.

Usage:
    from extra_options import install, uninstall, is_installed

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
        "zip_url": "https://github.com/ExOptsTeam/NFSUExOpts/releases/download/v3.0.1.1337/NFSU.ExOpts.v3.0.1.1337.zip",
        "zip_name": "NFSU.ExOpts.v3.0.1.1337.zip",
        "label": "NFSU Extra Options",
        "scripts_prefix": "scripts",  # flat layout - scripts/ at zip root
        "scripts_files": [
            "NFSUExtraOptions.asi",
            "NFSUExtraOptionsSettings.ini",
        ],
    },
    "nfsu2": {
        "zip_url": "https://github.com/ExOptsTeam/NFSU2ExOpts/releases/download/v5.1.0.1340/NFSU2.ExOpts.v5.1.0.1340.zip",
        "zip_name": "NFSU2.ExOpts.v5.1.0.1340.zip",
        "label": "NFSU2 Extra Options",
        "scripts_prefix": "scripts",
        "scripts_files": [
            "NFSU2ExtraOptions.asi",
            "NFSU2ExtraOptionsSettings.ini",
        ],
    },
    "nfsmw": {
        "zip_url": "https://github.com/ExOptsTeam/NFSMWExOpts/releases/download/v10.0.1.1337/NFSMW.ExOpts.v10.0.1.1337.zip",
        "zip_name": "NFSMW.ExOpts.v10.0.1.1337.zip",
        "label": "NFSMW Extra Options",
        "scripts_prefix": "scripts",
        "scripts_files": [
            "NFSMWExtraOptions.asi",
            "NFSMWExtraOptionsSettings.ini",
        ],
    },
    "nfsc": {
        "zip_url": "https://github.com/ExOptsTeam/NFSCExOpts/releases/download/v3.0.1.1338/NFSC.ExOpts.v3.0.1.1338.zip",
        "zip_name": "NFSC.ExOpts.v3.0.1.1338.zip",
        "label": "NFSC Extra Options",
        "scripts_prefix": "Main Files/scripts",  # NFSC quirk - nested under Main Files/
        "scripts_files": [
            "NFSCExtraOptions.asi",
            "NFSCExtraOptionsSettings.ini",
        ],
    },
}


# -- Public API ----------------------------------------------------------------

def install(game_key, install_dir, on_progress=None):
    """
    Download and install Extra Options for a game.

    1. Download the zip from ExOptsTeam's GitHub releases
    2. Extract to a temp dir
    3. Copy .asi and .ini from scripts/ (or Main Files/scripts/ for NFSC)
       into game root/scripts/
    4. Clean up temp dir

    We skip dinput8.dll since the Widescreen Fix already provides it.

    Returns True on success, False on error.
    Raises DownloadError if the download fails.
    """
    if game_key not in _GAMES:
        _log.error("extra_options: unknown game key: %s", game_key)
        return False

    game = _GAMES[game_key]
    _log.info("extra_options: installing %s to %s", game["label"], install_dir)

    # Make sure scripts/ exists in game dir
    scripts_dir = os.path.join(install_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="nfsbl_exopts_")
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
            _log.error("extra_options: corrupt zip: %s", zip_path)
            return False

        # Step 3: Copy .asi and .ini into scripts/
        # The scripts_prefix handles the NFSC Main Files/ quirk
        extracted_scripts = os.path.join(tmp_dir, game["scripts_prefix"])
        if not os.path.isdir(extracted_scripts):
            _log.error("extra_options: scripts folder not found at %s",
                       extracted_scripts)
            return False

        for fname in game["scripts_files"]:
            src = os.path.join(extracted_scripts, fname)
            dst = os.path.join(scripts_dir, fname)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
                _log.debug("extra_options: copied scripts/%s", fname)
            else:
                _log.warning("extra_options: expected file not found: %s", src)

        if on_progress:
            on_progress(f"Installed {game['label']}")

        _log.info("extra_options: %s installed successfully", game["label"])
        return True

    finally:
        # Step 4: Clean up temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


def uninstall(game_key, install_dir):
    """
    Remove Extra Options files from a game directory.

    Only removes the ExOpts .asi and .ini from scripts/. Does not touch
    dinput8.dll (owned by Widescreen Fix).

    Returns True on success, False on error.
    """
    if game_key not in _GAMES:
        _log.error("extra_options: unknown game key: %s", game_key)
        return False

    game = _GAMES[game_key]
    _log.info("extra_options: uninstalling %s from %s",
              game["label"], install_dir)

    scripts_dir = os.path.join(install_dir, "scripts")
    for fname in game["scripts_files"]:
        fpath = os.path.join(scripts_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                _log.debug("extra_options: removed scripts/%s", fname)
            except OSError:
                _log.warning("extra_options: failed to remove %s", fpath)

    _log.info("extra_options: %s uninstalled", game["label"])
    return True


def is_installed(game_key, install_dir):
    """
    Check if Extra Options is installed for a game.

    Looks for the .asi file in scripts/.

    Returns True if installed, False otherwise.
    """
    if game_key not in _GAMES:
        return False

    game = _GAMES[game_key]
    asi_name = game["scripts_files"][0]
    asi_path = os.path.join(install_dir, "scripts", asi_name)
    return os.path.exists(asi_path)
