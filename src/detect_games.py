"""
detect_games.py - NFSBlacklist game detection

Detects installed NFS Black Box games from user-provided game files.
These four titles were never sold on Steam, so detection is
own-game-only. No Steam library scanning, no appmanifest parsing.

The four supported titles share two exe names:
  - speed.exe   is used by both NFSU and NFSMW
  - SPEED2.exe  is unique to NFSU2
  - NFSC.exe    is unique to NFSC

Because of the speed.exe collision, sentinel files are used to
disambiguate NFSU from NFSMW.

Case sensitivity: Linux filesystems are case-sensitive, but game files
from Windows installs have unpredictable casing (Speed.exe, speed.exe,
SPEED2.EXE, TRACKS vs Tracks, etc). All file lookups use case-insensitive
matching to handle whatever the user gives us.
"""

import os
import re
import glob

from log import get_logger

_log = get_logger(__name__)

# -- Game definitions ---------------------------------------------------------
# These four Black Box NFS titles are all that NFSBlacklist supports.
# None of them were ever sold on Steam.

GAMES = {
    "nfsu": {
        "name": "Need for Speed: Underground",
        "order": 1,
        "exe": "speed.exe",
        "year": 2003,
    },
    "nfsu2": {
        "name": "Need for Speed: Underground 2",
        "order": 2,
        "exe": "SPEED2.exe",
        "year": 2004,
    },
    "nfsmw": {
        "name": "Need for Speed: Most Wanted",
        "order": 3,
        "exe": "speed.exe",
        "year": 2005,
    },
    "nfsc": {
        "name": "Need for Speed: Carbon",
        "order": 4,
        "exe": "NFSC.exe",
        "year": 2006,
    },
}


# -- Case-insensitive file helpers --------------------------------------------
# Game files from Windows installs have unpredictable casing. These helpers
# find files regardless of how the user's copy is cased.

def _ipath(base, *parts):
    """
    Case-insensitive path join. Walks each path component and finds the
    actual entry on disk that matches case-insensitively.

    Returns the resolved path if every component is found, None otherwise.

    Example:
        _ipath("/home/deck/Games/NFSC", "TRACKS", "L2RA.BUN")
        might return "/home/deck/Games/NFSC/Tracks/l2ra.bun" or whatever
        casing actually exists on disk.
    """
    current = base
    for part in parts:
        if not os.path.isdir(current):
            return None
        part_lower = part.lower()
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        match = None
        for entry in entries:
            if entry.lower() == part_lower:
                match = entry
                break
        if match is None:
            return None
        current = os.path.join(current, match)
    return current


def _iexists(base, *parts):
    """Case-insensitive check for whether a path exists."""
    return _ipath(base, *parts) is not None


def _ifind_exe(game_root, exe_name):
    """
    Find the game exe in game_root with case-insensitive matching.
    Returns the full path to the exe, or a best-guess path if not found.
    """
    resolved = _ipath(game_root, exe_name)
    if resolved and os.path.isfile(resolved):
        return resolved
    # Fall back to the expected path even if it doesn't exist on disk
    return os.path.join(game_root, exe_name)


# -- Own-game detection --------------------------------------------------------
# Scans common game install locations for known NFS game folders.
#
# Detection uses two passes:
#   1. Exact match  -- folder name matches a known name exactly
#                      (case-insensitive)
#   2. Keyword match -- folder name contains known short codes or title words
#                       checked with word boundaries so short codes like "nfsu"
#                       don't match unrelated folder names
#
# After a folder name match, a sentinel file check confirms the game identity
# and locates the actual game root (which may be a subfolder of the matched
# directory).

# Exact folder name -> list of game keys.
# Order matters: check "underground 2" before "underground" so NFSU2
# folders don't false-match to NFSU.
# Includes variants seen in the wild: dashes, "black edition", abbreviations.
FOLDER_TO_KEYS = {
    # NFSU2 - check before NFSU
    "need for speed underground 2":           ["nfsu2"],
    "need for speed - underground 2":         ["nfsu2"],
    "nfs underground 2":                      ["nfsu2"],
    "nfsu2":                                  ["nfsu2"],
    # NFSU
    "need for speed underground":             ["nfsu"],
    "need for speed - underground":           ["nfsu"],
    "nfs underground":                        ["nfsu"],
    "nfsu":                                   ["nfsu"],
    # NFSMW - includes "black edition" variant
    "need for speed most wanted":             ["nfsmw"],
    "need for speed most wanted black edition": ["nfsmw"],
    "nfs most wanted":                        ["nfsmw"],
    "nfs most wanted black edition":          ["nfsmw"],
    "nfsmw":                                  ["nfsmw"],
    "most wanted":                            ["nfsmw"],
    "most wanted black edition":              ["nfsmw"],
    # NFSC
    "need for speed carbon":                  ["nfsc"],
    "need for speed - carbon":                ["nfsc"],
    "nfs carbon":                             ["nfsc"],
    "nfsc":                                   ["nfsc"],
}

# Keyword rules checked in order when exact match fails.
# Each entry is (compiled_regex, keys_list).
# Order matters: more specific rules first.
#
# We use (?:^|[\b\s_\-]) and (?:[\b\s_\-]|$) instead of plain \b because
# Python's \b treats underscores as word characters. Folder names like
# "NFS_Carbon_v1.4" need underscores and dashes to act as boundaries.
_SEP = r'(?:^|(?<=[\s_\-])|\b)'
_END = r'(?:$|(?=[\s_\-])|\b)'

_KEYWORD_RULES = [
    # UG2 - check before UG1 so "underground 2" doesn't fall through
    (re.compile(_SEP + r'(underground[\s_\-]*2|nfsu2|ug2)' + _END, re.IGNORECASE), ["nfsu2"]),
    # UG1
    (re.compile(_SEP + r'(underground|nfsu|ug1)' + _END, re.IGNORECASE),            ["nfsu"]),
    # Most Wanted
    (re.compile(_SEP + r'(most[\s_\-]*wanted|nfsmw|mw)' + _END, re.IGNORECASE),     ["nfsmw"]),
    # Carbon
    (re.compile(_SEP + r'(carbon|nfsc)' + _END, re.IGNORECASE),                      ["nfsc"]),
]

# Default scan locations - case-sensitive on Linux
OWN_SCAN_PATHS = [
    os.path.expanduser("~/Games"),
    os.path.expanduser("~/games"),
    os.path.expanduser("~/NFS"),
    "/run/media/deck/*/Games",
    "/run/media/deck/*/games",
    "/run/media/deck/*/NFS",
    "/run/media/deck/*",
    "/run/media/mmcblk0p1",
]

# Maximum directory depth to walk when scanning for game folders
_MAX_SCAN_DEPTH = 5

# Maximum depth to search within a matched folder for sentinel files
_SENTINEL_SCAN_DEPTH = 3


# -- Sentinel file map --------------------------------------------------------
# Sentinel files disambiguate games that share the same exe name.
# NFSU and NFSMW both use speed.exe, so we need unique files to tell
# them apart. NFSU2 and NFSC are unambiguous but still use sentinels
# for extra validation.
#
# Each sentinel is a tuple of path components checked case-insensitively.
# Verified against actual game installs on a physical Steam Deck:
#   NFSU:  Tracks/STREAML1RA.BUN  (UG1-specific track format)
#   NFSU2: SPEED2.exe             (unique exe)
#   NFSMW: TRACKS/L2RA.BUN        (MW-specific track data)
#   NFSC:  NFSC.exe               (unique exe)

GAME_SENTINELS = {
    "nfsu":  ("Tracks", "STREAML1RA.BUN"),
    "nfsu2": ("SPEED2.exe",),
    "nfsmw": ("TRACKS", "L2RA.BUN"),
    "nfsc":  ("NFSC.exe",),
}

# Maps each game key to its sentinel group.
# For NFS each key is its own group (unlike CoD where SP/MP share one).
KEY_TO_SENTINEL = {
    "nfsu":  "nfsu",
    "nfsu2": "nfsu2",
    "nfsmw": "nfsmw",
    "nfsc":  "nfsc",
}


def get_exe_size(exe_path):
    if os.path.exists(exe_path):
        return os.path.getsize(exe_path)
    return None


def _check_sentinel(candidate_dir, sentinel_group):
    """
    Check if a sentinel file exists relative to candidate_dir.
    Uses case-insensitive path matching since game files from
    Windows installs have unpredictable casing.

    Returns True if the sentinel is found, False otherwise.
    """
    sentinel_parts = GAME_SENTINELS.get(sentinel_group)
    if not sentinel_parts:
        return False

    return _iexists(candidate_dir, *sentinel_parts)


def _find_game_root(candidate_dir, sentinel_group):
    """
    Starting from candidate_dir (a folder that matched by name), search
    for the sentinel file to confirm the game identity and locate the
    actual game root directory.

    1. Check candidate_dir itself
    2. Walk up to _SENTINEL_SCAN_DEPTH levels deep looking for the sentinel

    Returns the confirmed game root path, or None if the sentinel was not
    found (indicating an incomplete, wrong, or empty install).
    """
    # Check the candidate dir directly first - most common case
    if _check_sentinel(candidate_dir, sentinel_group):
        return candidate_dir

    # Search subdirectories up to _SENTINEL_SCAN_DEPTH levels deep
    skip = {"__pycache__", ".git", ".svn"}
    for dirpath, dirnames, _filenames in os.walk(candidate_dir):
        rel = os.path.relpath(dirpath, candidate_dir)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= _SENTINEL_SCAN_DEPTH:
            dirnames.clear()
            continue
        # Skip hidden dirs and known junk
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in skip]

        # Don't re-check candidate_dir (already checked above)
        if dirpath == candidate_dir:
            continue

        if _check_sentinel(dirpath, sentinel_group):
            return dirpath

    return None


def _walk_limited(root, max_depth):
    """Walk a directory tree up to max_depth levels deep."""
    skip = {".steam", ".local", ".cache", ".config", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirnames.clear()
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in skip]
        yield dirpath, dirnames, filenames


def _match_folder(name):
    """
    Try to match a folder name to a set of game keys.
    Returns a list of keys or an empty list if no match.

    Pass 1 - exact match (case-insensitive).
    Pass 2 - keyword regex rules in priority order.
    """
    name_lower = name.lower()

    # Pass 1 - exact
    if name_lower in FOLDER_TO_KEYS:
        return FOLDER_TO_KEYS[name_lower]

    # Pass 2 - keyword
    for pattern, keys in _KEYWORD_RULES:
        if pattern.search(name):
            return keys

    return []


def find_own_installed(extra_paths=None, on_progress=None):
    """
    Scan the filesystem for known NFS game folders.

    Searches ~/Games, ~/games, ~/NFS, SD card game folders, plus any
    user-provided extra paths (e.g. from a folder picker in the UI).

    Detection is two-phase:
      1. Folder name matching (exact then keyword) finds candidate directories
      2. Sentinel file check confirms the game and locates the actual game root
         (which may be the matched folder or a subfolder up to 3 levels deep)

    If a folder name matches but the sentinel is not found, the game is skipped
    (incomplete or wrong install). If the sentinel is in a subfolder, that
    subfolder becomes install_dir so mod installers write to the correct place.

    Returns a dict of game keys -> game info dicts with "source": "own".

    extra_paths -- optional list of additional directories to scan
    on_progress -- optional callback(msg: str)
    """
    def prog(msg):
        if on_progress:
            on_progress(msg)

    # Build scan list: defaults + globs + extras
    scan_dirs = []
    seen = set()
    for pattern in OWN_SCAN_PATHS:
        for path in glob.glob(pattern):
            path = os.path.normpath(path)
            if path not in seen and os.path.isdir(path):
                seen.add(path)
                scan_dirs.append(path)
    if extra_paths:
        for path in extra_paths:
            path = os.path.normpath(path)
            if path not in seen and os.path.isdir(path):
                seen.add(path)
                scan_dirs.append(path)

    if not scan_dirs:
        prog("No game folders found to scan.")
        return {}

    found = {}

    for scan_dir in scan_dirs:
        prog(f"Scanning {scan_dir}...")
        for dirpath, dirnames, _filenames in _walk_limited(scan_dir, _MAX_SCAN_DEPTH):
            folder_name = os.path.basename(dirpath)
            matched_keys = _match_folder(folder_name)

            if not matched_keys:
                continue

            # Determine the sentinel group from the first matched key
            sentinel_group = KEY_TO_SENTINEL.get(matched_keys[0])
            if not sentinel_group:
                # No sentinel defined - fall back to trusting folder name
                dirnames.clear()
                for key in matched_keys:
                    if key in found:
                        continue
                    meta = GAMES.get(key)
                    if not meta:
                        continue
                    exe_path = _ifind_exe(dirpath, meta["exe"])
                    found[key] = {
                        **meta,
                        "install_dir": dirpath,
                        "exe_path":    exe_path,
                        "exe_size":    get_exe_size(exe_path),
                        "source":      "own",
                    }
                    prog(f"  found {key}: {meta['name']} at {dirpath}")
                continue

            # Run sentinel check to confirm and locate actual game root
            game_root = _find_game_root(dirpath, sentinel_group)

            if game_root is None:
                # Sentinel not found - incomplete or wrong install.
                # Don't stop descending: the real game might be deeper
                # under a differently-named subfolder.
                prog(f"  {folder_name}: folder matched but game files not found, skipping")
                continue

            # Sentinel confirmed - stop descending into this branch
            dirnames.clear()

            if game_root != dirpath:
                prog(f"  {folder_name}: game root found in subfolder {os.path.relpath(game_root, dirpath)}")

            for key in matched_keys:
                if key in found:
                    continue
                meta = GAMES.get(key)
                if not meta:
                    continue

                exe_path = _ifind_exe(game_root, meta["exe"])
                found[key] = {
                    **meta,
                    "install_dir": game_root,
                    "exe_path":    exe_path,
                    "exe_size":    get_exe_size(exe_path),
                    "source":      "own",
                }
                prog(f"  found {key}: {meta['name']} at {game_root}")

    if not found:
        prog("No supported games found.")
    else:
        prog(f"Found {len(found)} game(s).")

    return found


# -- CLI test harness ----------------------------------------------------------

if __name__ == "__main__":
    print("NFS own-game scan:")
    own = find_own_installed(on_progress=print)
    for key, game in own.items():
        print(f"  [{key}] {game['name']}")
        print(f"        {game['install_dir']}")
