"""
shortcut.py - NFSBlacklist non-Steam shortcut creator

Creates non-Steam game shortcuts in Steam for the 4 Black Box NFS titles.
These games are own-game-only (never sold on digital stores), so every
shortcut points to the user's own game exe with a Proton prefix.

Shortcuts include:
  - Proper artwork (icon, grid, wide, hero, logo) from SteamGridDB
  - Correct compatdata prefix via launch options
  - Controller template assignment based on gyro mode
  - GE-Proton compat tool assignment
  - Steam Input enabled (AllowDesktopConfig)

Called at the end of OwnInstallScreen._run() after mod installation completes.
Must be called while Steam is closed.
"""

import binascii
import os
import re
import shutil
import struct
import threading
import time
import urllib.request

from identity import INSTALL_DIR, asset_url
from log import get_logger

_log = get_logger(__name__)


# -- Paths ---------------------------------------------------------------------

STEAM_ROOT     = os.path.expanduser("~/.local/share/Steam")
USERDATA_DIR   = os.path.join(STEAM_ROOT, "userdata")
COMPAT_ROOT    = os.path.join(STEAM_ROOT, "steamapps", "compatdata")
STEAM_CONFIG   = os.path.join(STEAM_ROOT, "config", "config.vdf")

_HERE          = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT   = os.path.dirname(_HERE)
ASSETS_DIR     = os.path.join(PROJECT_ROOT, "assets", "controllers")

MIN_UID = 10000

_BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
}


# -- NFS shortcut definitions -------------------------------------------------
#
# All 4 NFS games are own-game-only. Each entry defines the canonical shortcut
# name (which determines the appid CRC), artwork URLs, and controller type.
#
# Artwork credits (SteamGridDB): see README.md

NFS_SHORTCUTS = {
    "nfsu": {
        "name":           "Need for Speed: Underground",
        "template_type":  "racing",
        "icon_url":       "https://cdn2.steamgriddb.com/icon/e939d0b700e0a09fe2b8c2c9e31ef0e3.ico",
        "grid_url":       "https://cdn2.steamgriddb.com/grid/0959494b92b81147796ce901ea4f9927.png",
        "wide_url":       "https://cdn2.steamgriddb.com/grid/4ea29595c25ccf7a33d3fdec75630d5a.png",
        "hero_url":       "https://cdn2.steamgriddb.com/hero/ccc81a97c1535f9a631b9db584a264e4.png",
        "logo_url":       "https://cdn2.steamgriddb.com/logo/750263dbb2fb8547bdd810ee11a08c7a.png",
        "icon_ext": "ico", "grid_ext": "png", "wide_ext": "png", "hero_ext": "png", "logo_ext": "png",
    },
    "nfsu2": {
        "name":           "Need for Speed: Underground 2",
        "template_type":  "racing",
        "icon_url":       "https://cdn2.steamgriddb.com/icon/2131f8ecf18db66a758f718dc729e00e.ico",
        "grid_url":       "https://cdn2.steamgriddb.com/grid/8763b03d427d69f413df44433092276c.png",
        "wide_url":       "https://cdn2.steamgriddb.com/grid/c0c783b5fc0d7d808f1d14a6e9c8280d.png",
        "hero_url":       "https://cdn2.steamgriddb.com/hero/8c2d7d2728733cad5681b6b79ae799e4.png",
        "logo_url":       "https://cdn2.steamgriddb.com/logo/7a614fd06c325499f1680b9896beedeb.png",
        "icon_ext": "ico", "grid_ext": "png", "wide_ext": "png", "hero_ext": "png", "logo_ext": "png",
    },
    "nfsmw": {
        "name":           "Need for Speed: Most Wanted",
        "template_type":  "racing",
        "icon_url":       "https://cdn2.steamgriddb.com/icon/604cd803586d40e36a15c53a230c93ec.ico",
        "grid_url":       "https://cdn2.steamgriddb.com/grid/a86cc0b404ab003e0badb9ed96b55ace.png",
        "wide_url":       "https://cdn2.steamgriddb.com/grid/6fdb8f7d90e975d5d19959a0fcebf123.png",
        "hero_url":       "https://cdn2.steamgriddb.com/hero/822b440edda4c46a5e1dad463eaf8ebd.png",
        "logo_url":       "https://cdn2.steamgriddb.com/logo/eb9fc349601c69352c859c1faa287874.png",
        "icon_ext": "ico", "grid_ext": "png", "wide_ext": "png", "hero_ext": "png", "logo_ext": "png",
    },
    "nfsc": {
        "name":           "Need for Speed: Carbon",
        "template_type":  "racing",
        "icon_url":       "https://cdn2.steamgriddb.com/icon/59dfd4106ab71d11b48a4246ba153331.ico",
        "grid_url":       "https://cdn2.steamgriddb.com/grid/8eb8c14637ad7f04b17390e3c4b16ec9.png",
        "wide_url":       "https://cdn2.steamgriddb.com/grid/ee955e252af3c85e66e15864e31174fe.png",
        "hero_url":       "https://cdn2.steamgriddb.com/hero/4dff7cccfc092f41b8170fc6d7dc93c0.jpg",
        "logo_url":       "https://cdn2.steamgriddb.com/logo/fdf1bc5669e8ff5ba45d02fded729feb.png",
        "icon_ext": "ico", "grid_ext": "png", "wide_ext": "png", "hero_ext": "jpg", "logo_ext": "png",
    },
}


# -- Helpers -------------------------------------------------------------------

def _find_all_steam_uids():
    """Return all valid Steam user ID folders from userdata/."""
    if not os.path.isdir(USERDATA_DIR):
        return []
    seen, uids = set(), []
    for entry in os.listdir(USERDATA_DIR):
        if not entry.isdigit() or int(entry) < MIN_UID:
            continue
        real = os.path.realpath(os.path.join(USERDATA_DIR, entry))
        if real in seen:
            continue
        seen.add(real)
        uids.append(entry)
    return uids


def _get_deck_serial() -> str | None:
    """Read the Steam Deck serial number from Steam's config.vdf."""
    if not os.path.exists(STEAM_CONFIG):
        return None
    try:
        with open(STEAM_CONFIG, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        match = re.search(r'"SteamDeckRegisteredSerialNumber"\s+"([^"]+)"', content)
        if match:
            return match.group(1)
    except Exception:
        _log.debug("serial number read failed", exc_info=True)
    return None


def _calc_shortcut_appid(exe_path: str, name: str) -> int:
    """
    Calculate the Steam shortcut appid from exe path and name.
    This must match Steam's internal algorithm exactly. If the CRC or
    bitmask changes, shortcuts will not resolve and artwork/controller
    configs will point to the wrong appid. Do not modify.
    """
    key = (exe_path + name).encode("utf-8")
    crc = binascii.crc32(key) & 0xFFFFFFFF
    return (crc | 0x80000000) & 0xFFFFFFFF


def _to_signed32(n):
    """Convert unsigned int32 appid to signed int32 for vdf binary format."""
    return n if n <= 2147483647 else n - 2**32


def _download(url: str, dest: str) -> bool:
    """Download a file from URL to dest path. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        req = urllib.request.Request(url, headers=_BROWSER_UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            with open(dest, "wb") as f:
                f.write(r.read())
        return True
    except Exception:
        _log.debug("artwork download failed", exc_info=True)
        return False


# -- Binary VDF helpers --------------------------------------------------------

def _vdf_string(key: str, val: str) -> bytes:
    """Encode a string field for binary VDF."""
    return b'\x01' + key.encode('utf-8') + b'\x00' + val.encode('utf-8') + b'\x00'


def _vdf_int32(key: str, val: int) -> bytes:
    """Encode an int32 field for binary VDF."""
    return b'\x02' + key.encode('utf-8') + b'\x00' + struct.pack('<i', val)


def _make_shortcut_entry(idx: int, fields: dict) -> bytes:
    """Build a single shortcut entry in binary VDF format."""
    data = b'\x00' + str(idx).encode('utf-8') + b'\x00'

    for key, value in fields.items():
        if key == "tags":
            # Tags is a sub-dict
            data += b'\x00' + b'tags' + b'\x00'
            for tk, tv in value.items():
                data += _vdf_string(tk, tv)
            data += b'\x08'
        elif isinstance(value, str):
            data += _vdf_string(key, value)
        elif isinstance(value, int):
            data += _vdf_int32(key, value)

    data += b'\x08'
    return data


def _read_existing_shortcuts(path: str) -> list:
    """Return list of existing shortcut names from shortcuts.vdf."""
    if not os.path.exists(path):
        return []

    try:
        with open(path, 'rb') as f:
            data = f.read()
    except Exception:
        _log.debug("operation failed", exc_info=True)
        return []

    # Extract AppName values
    existing = []
    for match in re.finditer(b'\x01[Aa]pp[Nn]ame\x00([^\x00]+)\x00', data):
        existing.append(match.group(1).decode('utf-8', errors='replace'))

    return existing


def _read_shortcuts_raw(path: str) -> bytes:
    """Read the raw shortcuts.vdf content, stripping header/footer."""
    if not os.path.exists(path):
        return b''

    try:
        with open(path, 'rb') as f:
            data = f.read()
    except Exception:
        _log.debug("shortcuts.vdf read failed", exc_info=True)
        return b''

    # Strip header (b'\x00shortcuts\x00') and footer (b'\x08\x08')
    header = b'\x00shortcuts\x00'
    if data.startswith(header):
        data = data[len(header):]
    if data.endswith(b'\x08\x08'):
        data = data[:-2]
    elif data.endswith(b'\x08'):
        data = data[:-1]

    return data


def _get_next_index(raw_data: bytes) -> int:
    """
    Find the next available shortcut index from raw shortcut entry data.

    Shortcut entries start with the byte sequence: 0x00 <index_str> 0x00
    immediately followed by 0x02 (the appid int field marker). This two-byte
    lookahead distinguishes real entry headers from the many other 0x00...0x00
    numeric sequences present in binary VDF data (string lengths, field values, etc.).
    """
    if not raw_data:
        return 0

    indices = []
    i = 0
    while i < len(raw_data) - 2:
        if raw_data[i] == 0x00:
            end = raw_data.find(b'\x00', i + 1)
            if end != -1 and end > i + 1:
                # Only treat as an entry index if immediately followed by
                # 0x02 (int32 field type byte for the 'appid' field header)
                if end + 1 < len(raw_data) and raw_data[end + 1] == 0x02:
                    try:
                        idx_str = raw_data[i + 1:end].decode('utf-8')
                        if idx_str.isdigit():
                            indices.append(int(idx_str))
                    except (UnicodeDecodeError, ValueError):
                        _log.debug("shortcut index parse failed", exc_info=True)
                i = end + 1
            else:
                i += 1
        else:
            i += 1

    return max(indices, default=-1) + 1


def _backup_file(path: str):
    """Write a .bak copy before modifying a Steam config file."""
    if os.path.exists(path):
        try:
            shutil.copy2(path, path + ".bak")
        except OSError:
            _log.debug("shortcuts.vdf backup failed", exc_info=True)


def _write_shortcuts_vdf(path: str, existing_raw: bytes, new_entries: list):
    """Write shortcuts.vdf with existing entries preserved and new ones appended."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _backup_file(path)

    data = b'\x00shortcuts\x00'

    if existing_raw:
        data += existing_raw

    for entry_bytes in new_entries:
        data += entry_bytes

    data += b'\x08\x08'

    with open(path, 'wb') as f:
        f.write(data)


# -- Artwork download ----------------------------------------------------------

def _download_artwork(grid_dir: str, appid: int, shortcut_def: dict, prog,
                      force: bool = False, clean_stale: bool = False):
    """Download all artwork for a shortcut to the grid directory (concurrent).

    force       - if True, re-download even if the file already exists on disk.
    clean_stale - if True, delete all existing {appid}* files in grid_dir
                  before downloading. Handles extension changes between
                  versions (e.g. old .jpg -> new .png) that would otherwise
                  leave orphans Steam might pick up instead of the new files.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    appid_str = str(appid)
    os.makedirs(grid_dir, exist_ok=True)

    if clean_stale:
        try:
            import glob as _glob
            for f in _glob.glob(os.path.join(grid_dir, f"{appid_str}*")):
                try:
                    os.remove(f)
                except OSError:
                    _log.debug("file removal failed", exc_info=True)
        except Exception:
            _log.debug("file removal failed", exc_info=True)

    artwork_map = [
        ("icon_url",  f"{appid_str}_icon.{shortcut_def['icon_ext']}",  "icon"),
        ("grid_url",  f"{appid_str}p.{shortcut_def['grid_ext']}",      "grid"),
        ("wide_url",  f"{appid_str}.{shortcut_def['wide_ext']}",       "wide"),
        ("hero_url",  f"{appid_str}_hero.{shortcut_def['hero_ext']}",  "hero"),
        ("logo_url",  f"{appid_str}_logo.{shortcut_def['logo_ext']}",  "logo"),
    ]

    # Collect items that actually need downloading
    to_download = []
    for url_key, filename, label in artwork_map:
        url = shortcut_def.get(url_key)
        if not url:
            continue
        dest = os.path.join(grid_dir, filename)
        if not force and os.path.exists(dest):
            prog(f"    ✓ {label} (cached)")
            continue
        to_download.append((url, dest, label))

    if not to_download:
        return

    # Download up to 5 images concurrently
    results_lock = threading.Lock()

    def _dl(url, dest, label):
        ok = _download(url, dest)
        with results_lock:
            if ok:
                prog(f"    ✓ {label}")
            else:
                prog(f"    ⚠ {label} failed")

    with ThreadPoolExecutor(max_workers=min(5, len(to_download))) as ex:
        futs = [ex.submit(_dl, url, dest, label) for url, dest, label in to_download]
        for fut in as_completed(futs):
            # Exceptions are logged inside _dl, but catch anything unexpected
            try:
                fut.result()
            except Exception:
                _log.debug("artwork download task failed", exc_info=True)


# -- Controller template assignment -------------------------------------------

def _get_template_filename(template_type: str, gyro_mode: str) -> str:
    """Return the controller template filename based on type and gyro mode.

    NFS games all use the racing profile. Gyro on = tilt steering assist,
    gyro off = sticks only.
    """
    suffix = "gyro" if gyro_mode == "on" else "off"
    return f"controller_neptune_nfsblacklist_racing_{suffix}.vdf"


def _assign_controller_config(uid: str, appid: int, shortcut_def: dict,
                               gyro_mode: str, prog):
    """
    Assign controller template for a non-Steam shortcut.

    We write to both configset_controller_neptune.vdf and the Deck's
    serial-specific configset. SteamOS in Game Mode reads from the serial
    file, so without it the profile only works in Desktop Mode.
    This mirrors what controller_profiles.py does for regular Steam games.
    """
    template_type = shortcut_def.get("template_type", "racing")
    template_filename = _get_template_filename(template_type, gyro_mode)

    src_template = os.path.join(ASSETS_DIR, template_filename)
    if not os.path.exists(src_template):
        prog(f"    ⚠ Template not found: {template_filename}")
        return

    appid_str = str(appid)

    # Path: Steam Controller Configs/<uid>/config/<appid>/
    steam_cfg_root = os.path.join(
        STEAM_ROOT, "steamapps", "common",
        "Steam Controller Configs", uid, "config"
    )
    cfg_dir = os.path.join(steam_cfg_root, appid_str)
    os.makedirs(cfg_dir, exist_ok=True)
    shutil.copy2(src_template, os.path.join(cfg_dir, "controller_neptune.vdf"))

    # Patch configset_controller_neptune.vdf
    configset_path = os.path.join(steam_cfg_root, "configset_controller_neptune.vdf")
    _patch_configset(configset_path, appid_str, template_filename)

    # Patch configset_{serial}.vdf - SteamOS on Deck reads from this file
    serial = _get_deck_serial()
    if serial:
        configset_serial = os.path.join(steam_cfg_root, f"configset_{serial}.vdf")
        _patch_configset(configset_serial, appid_str, template_filename)

    prog(f"    ✓ Controller: {template_filename}")


def _record_configset_edit(configset_path: str, key: str, template_name: str):
    """Record a configset VDF edit in the wrapper ledger."""
    try:
        from wrapper import _record_configset
        filename = os.path.basename(configset_path)
        _record_configset(filename, key, template_name)
    except Exception:
        _log.debug("configset ledger record failed", exc_info=True)


def _patch_configset(configset_path: str, key: str, template_name: str):
    """
    Patch configset_controller_neptune.vdf to set our template as default.
    Duplicated from controller_profiles.py because shortcut.py runs
    standalone and should not import from the controller module.
    """
    entry = f'\t"{key}"\n\t{{\n\t\t"template"\t\t"{template_name}"\n\t}}\n'

    if not os.path.exists(configset_path):
        os.makedirs(os.path.dirname(configset_path), exist_ok=True)
        with open(configset_path, "w", encoding="utf-8") as f:
            f.write('"controller_config"\n{\n' + entry + '}\n')
        _record_configset_edit(configset_path, key, template_name)
        return

    with open(configset_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    pattern = rf'\t"{re.escape(key)}"\n\t\{{[^}}]*\}}\n?'
    if re.search(pattern, content, re.MULTILINE | re.DOTALL):
        content = re.sub(pattern, entry, content, flags=re.MULTILINE | re.DOTALL)
    else:
        content = content.rstrip()
        if content.endswith("}"):
            content = content[:-1].rstrip() + "\n" + entry + "}\n"

    with open(configset_path, "w", encoding="utf-8") as f:
        f.write(content)
    _record_configset_edit(configset_path, key, template_name)


def _clear_compat_tool(appid_str: str):
    """
    Remove any CompatToolMapping entry for the given appid from config.vdf.

    Delegates to wrapper.clear_compat_tool() so the write goes through
    _write_and_validate_vdf() with brace-balance checking and auto-restore.
    """
    from wrapper import clear_compat_tool
    clear_compat_tool([appid_str])


# -- Shortcut appid lookup ----------------------------------------------------

def get_shortcut_appid(name: str) -> int | None:
    """
    Look up the actual appid of a non-Steam shortcut by its display name.

    Reads shortcuts.vdf for all Steam user accounts and returns the unsigned
    appid if a matching entry is found. Returns None if the shortcut doesn't
    exist yet.

    This is more reliable than recalculating the CRC because the appid in
    shortcuts.vdf is the one Steam actually uses for the prefix, artwork,
    and controller config - even if the exe path has changed since creation.
    """
    uids = _find_all_steam_uids()
    name_bytes = name.encode("utf-8")

    for uid in uids:
        shortcuts_path = os.path.join(USERDATA_DIR, uid, "config", "shortcuts.vdf")
        if not os.path.exists(shortcuts_path):
            continue

        try:
            with open(shortcuts_path, "rb") as f:
                data = f.read()
        except Exception:
            _log.debug("shortcuts.vdf read failed", exc_info=True)
            continue

        idx = data.find(name_bytes)
        if idx == -1:
            continue

        # The appid int32 field is before the AppName field.
        # Search backward from the name for the appid marker.
        # Binary VDF: \x02appid\x00<4 bytes signed int32>
        search_start = max(0, idx - 80)
        chunk = data[search_start:idx]
        marker = b'\x02appid\x00'
        marker_pos = chunk.rfind(marker)
        if marker_pos == -1:
            continue

        appid_offset = marker_pos + len(marker)
        if appid_offset + 4 > len(chunk):
            continue

        signed = struct.unpack_from("<i", chunk, appid_offset)[0]
        unsigned = signed if signed >= 0 else signed + 2**32
        return unsigned

    return None


# -- Entry-stripping helper (rewrite-on-collision support) ---------------------
#
# When a shortcut with a matching AppName already exists, we strip the stale
# entry from the raw VDF body and re-index the remaining entries so the new
# write can append a fresh entry with correct Exe / LaunchOptions / StartDir.

def _strip_entries_by_name(raw_body: bytes, names_to_strip: set) -> tuple:
    """
    Remove entries from raw_body whose AppName matches any name in
    names_to_strip. raw_body is the shortcut body with header/footer
    already stripped (as returned by _read_shortcuts_raw).

    Returns (new_body, stripped_names) where stripped_names is a set of
    names that were actually found and removed. Re-indexes remaining
    entries to contiguous numeric indices starting at 0.

    If no matching entries are found, returns (raw_body, set()) unchanged.
    """
    if not raw_body or not names_to_strip:
        return raw_body, set()

    # Find entry boundaries
    entry_starts = [m.start() for m in re.finditer(rb'\x00\d+\x00', raw_body)]
    if not entry_starts:
        return raw_body, set()

    entries = []
    for i, start in enumerate(entry_starts):
        end = entry_starts[i + 1] if i + 1 < len(entry_starts) else len(raw_body)
        entries.append(raw_body[start:end])

    kept = []
    stripped = set()
    for entry in entries:
        # Check if this entry's AppName matches anything we want to strip.
        # Match the full "\x01AppName\x00NAME\x00" sequence so partial
        # substring matches do not trigger a false strip.
        matched_name = None
        for name in names_to_strip:
            name_bytes = name.encode("utf-8")
            if (b'\x01AppName\x00' + name_bytes + b'\x00' in entry or
                b'\x01appname\x00' + name_bytes + b'\x00' in entry):
                matched_name = name
                break
        if matched_name is not None:
            stripped.add(matched_name)
            continue
        kept.append(entry)

    if not stripped:
        return raw_body, set()

    # Re-index remaining entries so Steam sees contiguous indices starting at 0
    reindexed = []
    for new_idx, entry in enumerate(kept):
        entry = re.sub(
            rb'^\x00\d+\x00',
            f'\x00{new_idx}\x00'.encode(),
            entry,
        )
        reindexed.append(entry)

    return b''.join(reindexed), stripped


# -- Generic shortcut API ------------------------------------------------------
#
# add_shortcut / remove_shortcut are the single-shortcut building blocks.
# Higher-level functions like write_own_shortcuts batch multiple shortcuts
# per VDF write. These generic functions write one shortcut at a time.

def add_shortcut(
    name: str,
    exe_path: str,
    start_dir: str,
    launch_options: str,
    artwork_def: dict,
    template_type: str,
    gyro_mode: str,
    on_progress=None,
    compat_tool: str = None,
    clear_compat: bool = False,
    force_artwork: bool = False,
    appid_exe_path: str = None,
) -> int:
    """
    Create a single non-Steam shortcut across all Steam UIDs.

    Returns the unsigned shortcut appid.

    name             - display name (AppName in shortcuts.vdf)
    exe_path         - quoted exe path for the shortcut entry
    start_dir        - quoted StartDir for the shortcut entry
    launch_options   - LaunchOptions string
    artwork_def      - dict with icon_url, grid_url, wide_url, hero_url,
                        logo_url and corresponding *_ext keys
    template_type    - "racing" for NFS games
    gyro_mode        - "on" or "off"
    on_progress      - optional callback(msg: str)
    compat_tool      - GE-Proton version to set, or None to skip
    clear_compat     - if True, remove any existing compat tool entry
    force_artwork    - re-download even if cached
    appid_exe_path   - if provided, use this instead of exe_path for the
                        appid CRC calculation (for stable appids when the
                        actual exe differs from the original shortcut exe)
    """
    def prog(msg):
        if on_progress:
            on_progress(msg)

    appid_key = appid_exe_path if appid_exe_path else exe_path
    shortcut_appid = _calc_shortcut_appid(appid_key, name)

    uids = _find_all_steam_uids()
    if not uids:
        prog("  No Steam user accounts found - shortcut skipped.")
        return shortcut_appid

    for uid in uids:
        shortcuts_path = os.path.join(USERDATA_DIR, uid, "config", "shortcuts.vdf")
        grid_dir = os.path.join(USERDATA_DIR, uid, "config", "grid")

        existing_names = _read_existing_shortcuts(shortcuts_path)
        existing_raw = _read_shortcuts_raw(shortcuts_path)

        # If a shortcut with this name already exists, strip its entry from
        # the raw body so we can write a fresh one with current Exe /
        # StartDir / LaunchOptions.
        replaced = False
        if name in existing_names:
            existing_raw, stripped = _strip_entries_by_name(
                existing_raw, {name}
            )
            if stripped:
                replaced = True

        next_idx = _get_next_index(existing_raw)

        icon_path = os.path.join(
            grid_dir,
            f"{shortcut_appid}_icon.{artwork_def.get('icon_ext', 'png')}",
        )

        entry = {
            "appid":               _to_signed32(shortcut_appid),
            "AppName":             name,
            "Exe":                 exe_path,
            "StartDir":            start_dir,
            "icon":                icon_path,
            "ShortcutPath":        "",
            "LaunchOptions":       launch_options,
            "IsHidden":            0,
            "AllowDesktopConfig":  1,
            "AllowOverlay":        1,
            "OpenVR":              0,
            "Devkit":              0,
            "DevkitGameID":        "",
            "DevkitOverrideAppID": 0,
            "LastPlayTime":        0,
            "FlatpakAppID":        "",
            "tags":                {"0": "NFSBlacklist"},
        }

        entry_bytes = _make_shortcut_entry(next_idx, entry)
        try:
            _write_shortcuts_vdf(shortcuts_path, existing_raw, [entry_bytes])
            if replaced:
                prog(f"    ✓ Shortcut replaced: {name}")
            else:
                prog(f"    ✓ Shortcut created: {name}")
        except Exception as e:
            prog(f"    ⚠ Failed to write shortcut: {e}")

        # Artwork
        _download_artwork(grid_dir, shortcut_appid, artwork_def, prog,
                          force=force_artwork, clean_stale=force_artwork)

        # Controller config
        _assign_controller_config(uid, shortcut_appid,
                                  {"template_type": template_type},
                                  gyro_mode, prog)

    # Compat tool handling (config.vdf is global, outside UID loop)
    if clear_compat:
        try:
            _clear_compat_tool(str(shortcut_appid))
            prog(f"    Cleared compat tool for shortcut")
        except Exception as ex:
            prog(f"    Could not clear compat tool: {ex}")
    elif compat_tool:
        try:
            from wrapper import set_compat_tool as _set_compat
            _set_compat([str(shortcut_appid)], compat_tool)
            prog(f"    ✓ GE-Proton {compat_tool} set")
        except Exception as ex:
            prog(f"    ⚠ Could not set compat tool: {ex}")

    prog(f"  Shortcut appid: {shortcut_appid}")
    return shortcut_appid


def remove_shortcut(name: str, exe_path: str, artwork_def: dict = None,
                    on_progress=None):
    """
    Remove a non-Steam shortcut by name from shortcuts.vdf for all UIDs.
    Also removes associated artwork from the grid directory.

    name        - AppName to match in shortcuts.vdf
    exe_path    - quoted exe path used for appid CRC (needed for artwork
                   file cleanup - artwork filenames are keyed on appid)
    artwork_def - dict with *_ext keys for artwork file removal;
                   if None, artwork files are left in place
    on_progress - optional callback(msg: str)
    """
    def prog(msg):
        if on_progress:
            on_progress(msg)

    shortcut_appid = _calc_shortcut_appid(exe_path, name)

    uids = _find_all_steam_uids()
    if not uids:
        return

    for uid in uids:
        shortcuts_path = os.path.join(USERDATA_DIR, uid, "config", "shortcuts.vdf")
        grid_dir = os.path.join(USERDATA_DIR, uid, "config", "grid")

        if not os.path.exists(shortcuts_path):
            continue

        try:
            with open(shortcuts_path, "rb") as f:
                data = f.read()
        except OSError:
            _log.debug("shortcuts.vdf read failed", exc_info=True)
            continue

        header = b'\x00shortcuts\x00'
        footer = b'\x08\x08'

        body = data
        if body.startswith(header):
            body = body[len(header):]
        if body.endswith(footer):
            body = body[:-2]
        elif body.endswith(b'\x08'):
            body = body[:-1]

        entry_starts = [m.start() for m in re.finditer(rb'\x00\d+\x00', body)]
        if not entry_starts:
            continue

        entries = []
        for i, start in enumerate(entry_starts):
            end = entry_starts[i + 1] if i + 1 < len(entry_starts) else len(body)
            entries.append(body[start:end])

        title_bytes = name.encode("utf-8")
        filtered = [
            e for e in entries
            if b'\x01AppName\x00' + title_bytes + b'\x00' not in e
            and b'\x01appname\x00' + title_bytes + b'\x00' not in e
        ]

        if len(filtered) < len(entries):
            reindexed = []
            for new_idx, entry in enumerate(filtered):
                entry = re.sub(
                    rb'^\x00\d+\x00',
                    f'\x00{new_idx}\x00'.encode(),
                    entry,
                )
                reindexed.append(entry)
            new_data = header + b''.join(reindexed) + footer
            try:
                _backup_file(shortcuts_path)
                with open(shortcuts_path, "wb") as f:
                    f.write(new_data)
                prog(f"  Removed shortcut '{name}' for uid {uid}")
            except OSError as ex:
                prog(f"  Could not write shortcuts.vdf: {ex}")

        # Remove artwork
        if artwork_def:
            artwork_suffixes = [
                f"_icon.{artwork_def.get('icon_ext', 'png')}",
                f"p.{artwork_def.get('grid_ext', 'jpg')}",
                f".{artwork_def.get('wide_ext', 'jpg')}",
                f"_hero.{artwork_def.get('hero_ext', 'jpg')}",
                f"_logo.{artwork_def.get('logo_ext', 'png')}",
            ]
            for suffix in artwork_suffixes:
                art_path = os.path.join(grid_dir, f"{shortcut_appid}{suffix}")
                if os.path.exists(art_path):
                    try:
                        os.remove(art_path)
                    except OSError:
                        _log.debug("file removal failed", exc_info=True)


# -- Public API ----------------------------------------------------------------

def enrich_own_games(own_games: dict, selected_keys: list,
                     on_progress=None):
    """
    Compute shortcut appids, compatdata paths, resolved exe paths, and
    launch options for own games - WITHOUT writing any VDF entries,
    artwork, controller configs, or compat tool mappings.

    Must run early in the install flow so prefix creation can use the
    computed compatdata_path. The actual shortcut writing is deferred to
    write_own_shortcuts(), which should run AFTER all mod installs so
    every target exe exists on disk.

    own_games     - dict {key: game_dict} from detect_games / OwnScanScreen
    selected_keys - list of game keys the user selected
    on_progress   - optional callback(msg: str)

    Returns own_games dict enriched with:
      shortcut_appid, compatdata_path, source, current_name,
      _own_actual_exe, _own_launch_options
    """
    def prog(msg):
        if on_progress:
            on_progress(msg)

    from detect_games import GAMES

    for key in selected_keys:
        if key not in NFS_SHORTCUTS:
            continue
        if key not in own_games:
            continue
        game = own_games[key]
        install_dir = game.get("install_dir")
        if not install_dir:
            continue

        shortcut_def = NFS_SHORTCUTS[key]
        name         = shortcut_def["name"]
        exe_path     = game["exe_path"]

        # Calculate appid from quoted exe + canonical name.
        # Gotcha: must use quoted path '"path/to/exe"' not 'path/to/exe'
        quoted_exe     = f'"{exe_path}"'
        shortcut_appid = _calc_shortcut_appid(quoted_exe, name)

        # Own games get their own CRC-based prefix keyed on the shortcut appid
        compatdata_path = os.path.join(COMPAT_ROOT, str(shortcut_appid))

        # Enrich the game dict so downstream code has the appid and paths
        game["shortcut_appid"]  = shortcut_appid
        game["compatdata_path"] = compatdata_path
        game["source"]          = "own"
        game["current_name"]    = name

        # NFS games all launch directly via their exe through Proton.
        # No mod clients redirect the exe (unlike CoD Plutonium/IW4x).
        # STEAM_COMPAT_DATA_PATH tells Proton which prefix to use.
        actual_exe     = exe_path
        launch_options = f'STEAM_COMPAT_DATA_PATH="{compatdata_path}" WINEDLLOVERRIDES="dinput8=n,b" %command%'

        # Store resolved values for write_own_shortcuts() to use later
        game["_own_actual_exe"]     = actual_exe
        game["_own_launch_options"] = launch_options

        prog(f"  -> {name}  appid: {shortcut_appid}")

    return own_games


def write_own_shortcuts(own_games: dict, selected_keys: list,
                        gyro_mode: str, on_progress=None):
    """
    Write non-Steam shortcut VDF entries, download artwork, assign
    controller configs, and set GE-Proton compat tool for own games.

    Must run AFTER all mod installs so every target exe exists on disk.
    Reads enrichment data (shortcut_appid, _own_actual_exe,
    _own_launch_options) previously set by enrich_own_games().

    own_games     - dict {key: game_dict} enriched by enrich_own_games()
    selected_keys - list of game keys the user selected
    gyro_mode     - "on" or "off"
    on_progress   - optional callback(msg: str)
    """
    def prog(msg):
        if on_progress:
            on_progress(msg)

    to_create = {}
    for key in selected_keys:
        if key not in NFS_SHORTCUTS:
            continue
        if key not in own_games:
            continue
        game = own_games[key]
        if not game.get("install_dir"):
            continue
        if game.get("_own_actual_exe") is None:
            continue
        to_create[key] = (NFS_SHORTCUTS[key], game)

    if not to_create:
        prog("No non-Steam game shortcuts to write.")
        return

    uids = _find_all_steam_uids()
    if not uids:
        prog("⚠ No Steam user accounts found - shortcuts skipped.")
        return

    for uid in uids:
        prog(f"Writing NFS shortcuts for user {uid}...")

        shortcuts_path = os.path.join(USERDATA_DIR, uid, "config", "shortcuts.vdf")
        grid_dir = os.path.join(USERDATA_DIR, uid, "config", "grid")

        existing_raw = _read_shortcuts_raw(shortcuts_path)

        # Strip any existing entries whose AppName matches a shortcut we're
        # about to write so reinstalls replace stale entries cleanly.
        names_to_write = {d["name"] for d, _ in to_create.values()}
        existing_raw, stripped = _strip_entries_by_name(
            existing_raw, names_to_write
        )
        if stripped:
            prog(f"  Replacing {len(stripped)} stale shortcut(s)...")

        existing_names = [
            n for n in _read_existing_shortcuts(shortcuts_path)
            if n not in stripped
        ]

        next_idx = _get_next_index(existing_raw)

        new_entries = []

        for key, (shortcut_def, game) in to_create.items():
            name           = shortcut_def["name"]
            install_dir    = game["install_dir"]
            actual_exe     = game["_own_actual_exe"]
            launch_options = game["_own_launch_options"]
            shortcut_appid = game["shortcut_appid"]

            icon_path = os.path.join(
                grid_dir, f"{shortcut_appid}_icon.{shortcut_def['icon_ext']}"
            )

            if not os.path.exists(actual_exe):
                prog(f"  -> {name}")
                prog(f"    ⚠ {os.path.basename(actual_exe)} not found - shortcut will be created anyway")
            else:
                prog(f"  -> {name}")
            prog(f"    appid: {shortcut_appid}")

            if name in existing_names:
                prog(f"    ⚠ Unexpected name collision after strip")

            entry = {
                "appid":               _to_signed32(shortcut_appid),
                "AppName":             name,
                "Exe":                 f'"{actual_exe}"',
                "StartDir":            f'"{install_dir}"',
                "icon":                icon_path,
                "ShortcutPath":        "",
                "LaunchOptions":       launch_options,
                "IsHidden":            0,
                "AllowDesktopConfig":  1,
                "AllowOverlay":        1,
                "OpenVR":              0,
                "Devkit":              0,
                "DevkitGameID":        "",
                "DevkitOverrideAppID": 0,
                "LastPlayTime":        0,
                "FlatpakAppID":        "",
                "tags":                {"0": "NFSBlacklist"},
            }

            entry_bytes = _make_shortcut_entry(next_idx, entry)
            new_entries.append(entry_bytes)
            next_idx += 1
            prog(f"    ✓ Shortcut created")

            # Download artwork
            _download_artwork(grid_dir, shortcut_appid, shortcut_def, prog,
                              force=True, clean_stale=True)

            # Assign controller config
            _assign_controller_config(uid, shortcut_appid, shortcut_def, gyro_mode, prog)

            # Set GE-Proton compat tool
            try:
                import config as _cfg
                from wrapper import set_compat_tool
                ge_version = _cfg.get_ge_proton_version()
                if ge_version:
                    set_compat_tool([str(shortcut_appid)], ge_version)
                    prog(f"    ✓ GE-Proton {ge_version} set")
            except Exception as ex:
                prog(f"    ⚠ Could not set GE-Proton: {ex}")

        if new_entries:
            try:
                _write_shortcuts_vdf(shortcuts_path, existing_raw, new_entries)
                prog(f"  ✓ shortcuts.vdf saved")
            except Exception as e:
                prog(f"  ⚠ Failed to write shortcuts.vdf: {e}")
        else:
            prog(f"  ✓ No new shortcuts needed")

    prog("✓ Non-Steam shortcuts written.")


def create_own_shortcuts(own_games: dict, selected_keys: list,
                        gyro_mode: str, on_progress=None):
    """
    Legacy wrapper - enriches own game dicts AND writes shortcuts in one
    call. Kept for backward compatibility. New code should call
    enrich_own_games() early and write_own_shortcuts() after installs.

    Returns own_games dict enriched with shortcut_appid, compatdata_path,
    and source fields.
    """
    own_games = enrich_own_games(own_games, selected_keys,
                                 on_progress=on_progress)
    write_own_shortcuts(own_games, selected_keys, gyro_mode,
                        on_progress=on_progress)
    return own_games
