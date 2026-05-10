"""
xenon_effects.py - XenonEffects installer (NFSMW only)

Downloads and installs XenonEffects for NFS Most Wanted from xan1242's
GitHub releases. This mod restores Xbox 360 sparks and contrails (wind
effects behind cars) that were missing from the PC version.

NFSMW only - NFS Carbon doesn't need this because the Widescreen Fix
has FixXenonEffects = 1 built in.

Install order: XenonEffects goes last, after Widescreen Fix, Extra
Options, and XtendedInput. Requires the ASI loader (dinput8.dll) from
the Widescreen Fix.

Zip layout (flat, verified from actual release zip):
  - GLOBAL/XenonEffects.tpk          -> GLOBAL/
  - scripts/NFSMW_XenonEffects.asi   -> scripts/
  - scripts/NFSMW_XenonEffects.ini   -> scripts/

No dinput8.dll in this zip - it expects the ASI loader is already there.
No INI patching needed - defaults are good.

Usage:
    from xenon_effects import install, uninstall, is_installed

    success = install("/path/to/game", on_progress=callback)
    installed = is_installed("/path/to/game")
    success = uninstall("/path/to/game")
"""

import os
import shutil
import tempfile
import zipfile

from log import get_logger
from net import download, DownloadError

_log = get_logger(__name__)

_ZIP_URL = "https://github.com/xan1242/NFSMW_XenonEffects/releases/download/1.02/NFSMW_XenonEffects.zip"
_ZIP_NAME = "NFSMW_XenonEffects.zip"
_LABEL = "NFSMW XenonEffects"

_SCRIPTS_FILES = [
    "NFSMW_XenonEffects.asi",
    "NFSMW_XenonEffects.ini",
]

_TPK_FOLDER = "GLOBAL"
_TPK_FILES = ["XenonEffects.tpk"]


# -- Public API ----------------------------------------------------------------

def install(install_dir, on_progress=None):
    """
    Download and install XenonEffects for NFS Most Wanted.

    1. Download the zip from xan1242's GitHub releases
    2. Extract to a temp dir
    3. Copy scripts/ files (.asi, .ini) to game scripts/
    4. Copy GLOBAL/XenonEffects.tpk to game GLOBAL/
    5. Clean up temp dir

    Returns True on success, False on error.
    Raises DownloadError if the download fails.
    """
    _log.info("xenon_effects: installing to %s", install_dir)

    scripts_dir = os.path.join(install_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="nfsbl_xe_")
    try:
        # Step 1: Download the zip
        zip_path = os.path.join(tmp_dir, _ZIP_NAME)
        if on_progress:
            on_progress(f"Downloading {_LABEL}...")

        try:
            download(_ZIP_URL, zip_path, label=_LABEL)
        except Exception as e:
            raise DownloadError(
                url=_ZIP_URL,
                dest=zip_path,
                label=_LABEL,
                cause=e,
            )

        # Step 2: Extract the zip
        if on_progress:
            on_progress(f"Extracting {_LABEL}...")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_dir)
        except zipfile.BadZipFile:
            _log.error("xenon_effects: corrupt zip: %s", zip_path)
            return False

        # Step 3: Copy scripts/ files
        extracted_scripts = os.path.join(tmp_dir, "scripts")
        if not os.path.isdir(extracted_scripts):
            _log.error("xenon_effects: scripts/ folder not found in zip")
            return False

        for fname in _SCRIPTS_FILES:
            src = os.path.join(extracted_scripts, fname)
            dst = os.path.join(scripts_dir, fname)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
                _log.debug("xenon_effects: copied scripts/%s", fname)
            else:
                _log.warning("xenon_effects: expected file not found: %s", src)

        # Step 4: Copy GLOBAL/ TPK
        extracted_tpk = os.path.join(tmp_dir, _TPK_FOLDER)
        dest_tpk = os.path.join(install_dir, _TPK_FOLDER)

        if os.path.isdir(extracted_tpk):
            os.makedirs(dest_tpk, exist_ok=True)
            for fname in _TPK_FILES:
                src = os.path.join(extracted_tpk, fname)
                dst = os.path.join(dest_tpk, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    _log.debug("xenon_effects: copied %s/%s",
                               _TPK_FOLDER, fname)
                else:
                    _log.warning("xenon_effects: TPK file not found: %s", src)
        else:
            _log.error("xenon_effects: %s/ folder not found in zip",
                       _TPK_FOLDER)
            return False

        if on_progress:
            on_progress(f"Installed {_LABEL}")

        _log.info("xenon_effects: installed successfully")
        return True

    finally:
        # Step 5: Clean up temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


def uninstall(install_dir):
    """
    Remove XenonEffects files from the game directory.

    Removes the XE .asi and .ini from scripts/ and the XenonEffects.tpk
    from GLOBAL/. Does not remove the GLOBAL/ folder itself since
    XtendedInput may also use it.

    Returns True on success, False on error.
    """
    _log.info("xenon_effects: uninstalling from %s", install_dir)

    # Remove scripts/ files
    scripts_dir = os.path.join(install_dir, "scripts")
    for fname in _SCRIPTS_FILES:
        fpath = os.path.join(scripts_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                _log.debug("xenon_effects: removed scripts/%s", fname)
            except OSError:
                _log.warning("xenon_effects: failed to remove %s", fpath)

    # Remove TPK files (but not the folder - XtendedInput may use it)
    tpk_dir = os.path.join(install_dir, _TPK_FOLDER)
    for fname in _TPK_FILES:
        fpath = os.path.join(tpk_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                _log.debug("xenon_effects: removed %s/%s",
                           _TPK_FOLDER, fname)
            except OSError:
                _log.warning("xenon_effects: failed to remove %s", fpath)

    _log.info("xenon_effects: uninstalled")
    return True


def is_installed(install_dir):
    """
    Check if XenonEffects is installed.

    Looks for the .asi file in scripts/.

    Returns True if installed, False otherwise.
    """
    asi_path = os.path.join(install_dir, "scripts", "NFSMW_XenonEffects.asi")
    return os.path.exists(asi_path)
