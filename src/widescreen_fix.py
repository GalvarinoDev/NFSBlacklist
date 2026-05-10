"""
widescreen_fix.py - ThirteenAG Widescreen Fix installer

Downloads and installs the Widescreen Fix for each NFS game from
ThirteenAG's GitHub releases. This is the foundation mod - it provides
the dinput8.dll (Ultimate ASI Loader) that every other mod depends on.

Install order: Widescreen Fix goes first, then Extra Options, then
XtendedInput, then XenonEffects (NFSMW only).

The zip for each game extracts flat (no wrapping folder):
  - dinput8.dll    -> game root
  - scripts/*.asi  -> game root/scripts/
  - scripts/*.ini  -> game root/scripts/
  - scripts/*.dat  -> game root/scripts/ (NFSU, NFSU2 only)
  - scripts/*.tpk  -> game root/scripts/ (NFSU, NFSMW, NFSC only)

After extraction, we patch the INI with ini_utils.patch_ini() to set
ImproveGamepadSupport = 0 (disabled, since XtendedInput handles input)
and AutoFitFE = 1 (for 16:10 devices like the Steam Deck).

Usage:
    from widescreen_fix import install, uninstall, is_installed

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
from ini_utils import patch_ini

_log = get_logger(__name__)

# -- Per-game data -------------------------------------------------------------
# Each entry defines the download URL, the INI filename inside scripts/,
# and the list of all files the zip places in scripts/ (for uninstall).

_BASE_URL = "https://github.com/ThirteenAG/WidescreenFixesPack/releases/download"

_GAMES = {
    "nfsu": {
        "zip_url": f"{_BASE_URL}/nfsu/NFSUnderground.WidescreenFix.zip",
        "zip_name": "NFSUnderground.WidescreenFix.zip",
        "label": "NFSU Widescreen Fix",
        "ini_name": "NFSUnderground.WidescreenFix.ini",
        "scripts_files": [
            "NFSUnderground.WidescreenFix.asi",
            "NFSUnderground.WidescreenFix.ini",
            "NFSUnderground.WidescreenFix.dat",
            "NFSUnderground.WidescreenFix.tpk",
        ],
    },
    "nfsu2": {
        "zip_url": f"{_BASE_URL}/nfsu2/NFSUnderground2.WidescreenFix.zip",
        "zip_name": "NFSUnderground2.WidescreenFix.zip",
        "label": "NFSU2 Widescreen Fix",
        "ini_name": "NFSUnderground2.WidescreenFix.ini",
        "scripts_files": [
            "NFSUnderground2.WidescreenFix.asi",
            "NFSUnderground2.WidescreenFix.ini",
            "NFSUnderground2.WidescreenFix.dat",
        ],
    },
    "nfsmw": {
        "zip_url": f"{_BASE_URL}/nfsmw/NFSMostWanted.WidescreenFix.zip",
        "zip_name": "NFSMostWanted.WidescreenFix.zip",
        "label": "NFSMW Widescreen Fix",
        "ini_name": "NFSMostWanted.WidescreenFix.ini",
        "scripts_files": [
            "NFSMostWanted.WidescreenFix.asi",
            "NFSMostWanted.WidescreenFix.ini",
            "NFSMostWanted.WidescreenFix.tpk",
        ],
    },
    "nfsc": {
        "zip_url": f"{_BASE_URL}/nfsc/NFSCarbon.WidescreenFix.zip",
        "zip_name": "NFSCarbon.WidescreenFix.zip",
        "label": "NFSC Widescreen Fix",
        "ini_name": "NFSCarbon.WidescreenFix.ini",
        "scripts_files": [
            "NFSCarbon.WidescreenFix.asi",
            "NFSCarbon.WidescreenFix.ini",
            "NFSCarbon.WidescreenFix.tpk",
        ],
    },
}

# -- INI patches applied after extraction --------------------------------------
# ImproveGamepadSupport is disabled for all games because XtendedInput
# handles controller input. AutoFitFE is enabled so the UI scales
# correctly on 16:10 displays (Steam Deck, Legion Go, etc).
#
# NFSU2 is special: its ImproveGamepadSupport uses value 4 for "None"
# (ThirteenAG already set this for XtendedInput coexistence). We leave
# it at 4 instead of setting to 0.

_INI_PATCHES = {
    "nfsu": {
        "MISC": {"ImproveGamepadSupport": "0"},
        "MAIN": {"AutoFitFE": "1"},
    },
    "nfsu2": {
        # ImproveGamepadSupport already 4 (None) in stock INI - leave it
        "MAIN": {"AutoFitFE": "1"},
    },
    "nfsmw": {
        "MISC": {"ImproveGamepadSupport": "0"},
        # AutoFitFE already 1 in stock INI
    },
    "nfsc": {
        "MISC": {"ImproveGamepadSupport": "0"},
        # AutoFitFE already 1 in stock INI
    },
}


# -- Public API ----------------------------------------------------------------

def install(game_key, install_dir, on_progress=None):
    """
    Download and install the Widescreen Fix for a game.

    1. Download the zip from ThirteenAG's GitHub releases
    2. Extract to a temp dir
    3. Copy dinput8.dll to game root
    4. Copy scripts/ contents to game root/scripts/
    5. Patch the INI with our settings
    6. Clean up temp dir

    Returns True on success, False on error.
    Raises DownloadError if the download fails (caller can show
    a manual download dialog).
    """
    if game_key not in _GAMES:
        _log.error("widescreen_fix: unknown game key: %s", game_key)
        return False

    game = _GAMES[game_key]
    _log.info("widescreen_fix: installing %s to %s", game["label"], install_dir)

    # Create scripts/ in game dir if it doesn't exist
    scripts_dir = os.path.join(install_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="nfsbl_wsf_")
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
            _log.error("widescreen_fix: corrupt zip: %s", zip_path)
            return False

        # Step 3: Copy dinput8.dll to game root
        dll_src = os.path.join(tmp_dir, "dinput8.dll")
        dll_dst = os.path.join(install_dir, "dinput8.dll")
        if os.path.exists(dll_src):
            shutil.copy2(dll_src, dll_dst)
            _log.info("widescreen_fix: copied dinput8.dll")
        else:
            _log.error("widescreen_fix: dinput8.dll not found in zip")
            return False

        # Step 4: Copy scripts/ contents
        extracted_scripts = os.path.join(tmp_dir, "scripts")
        if os.path.isdir(extracted_scripts):
            for fname in os.listdir(extracted_scripts):
                src = os.path.join(extracted_scripts, fname)
                dst = os.path.join(scripts_dir, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    _log.debug("widescreen_fix: copied scripts/%s", fname)
        else:
            _log.error("widescreen_fix: scripts/ folder not found in zip")
            return False

        # Step 5: Patch the INI
        if game_key in _INI_PATCHES:
            ini_path = os.path.join(scripts_dir, game["ini_name"])
            if os.path.exists(ini_path):
                patch_ini(ini_path, _INI_PATCHES[game_key])
                if on_progress:
                    on_progress(f"Configured {game['label']}")
            else:
                _log.warning("widescreen_fix: INI not found at %s", ini_path)

        _log.info("widescreen_fix: %s installed successfully", game["label"])
        return True

    finally:
        # Step 6: Clean up temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


def uninstall(game_key, install_dir):
    """
    Remove Widescreen Fix files from a game directory.

    Removes the WSF-specific files from scripts/ and dinput8.dll from
    the game root. Only call this when no other mods need the ASI loader
    (Widescreen Fix should be the last mod uninstalled).

    Returns True on success, False on error.
    """
    if game_key not in _GAMES:
        _log.error("widescreen_fix: unknown game key: %s", game_key)
        return False

    game = _GAMES[game_key]
    _log.info("widescreen_fix: uninstalling %s from %s", game["label"], install_dir)

    # Remove scripts/ files
    scripts_dir = os.path.join(install_dir, "scripts")
    for fname in game["scripts_files"]:
        fpath = os.path.join(scripts_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                _log.debug("widescreen_fix: removed scripts/%s", fname)
            except OSError:
                _log.warning("widescreen_fix: failed to remove %s", fpath)

    # Remove dinput8.dll
    dll_path = os.path.join(install_dir, "dinput8.dll")
    if os.path.exists(dll_path):
        try:
            os.remove(dll_path)
            _log.debug("widescreen_fix: removed dinput8.dll")
        except OSError:
            _log.warning("widescreen_fix: failed to remove dinput8.dll")

    _log.info("widescreen_fix: %s uninstalled", game["label"])
    return True


def is_installed(game_key, install_dir):
    """
    Check if the Widescreen Fix is installed for a game.

    Looks for the .asi file in scripts/ - that's the definitive marker.
    The dinput8.dll alone isn't enough since other mods also ship it.

    Returns True if installed, False otherwise.
    """
    if game_key not in _GAMES:
        return False

    game = _GAMES[game_key]
    # The first file in scripts_files is always the .asi
    asi_name = game["scripts_files"][0]
    asi_path = os.path.join(install_dir, "scripts", asi_name)
    return os.path.exists(asi_path)
