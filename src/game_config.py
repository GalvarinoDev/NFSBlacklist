"""
game_config.py - NFSBlacklist display config writer

Writes display resolution and graphics settings into each game's Wine
prefix registry (user.reg) before first launch. Without this, games
default to minimum resolution (320x200 for NFSMW) or crash when the
user tries to change graphics settings (NFSC on Proton 9+).

The four NFS games store display settings in the Windows registry under
different publisher keys:
  - NFSU:  Software\\EA Games\\Need For Speed Underground
  - NFSU2: Software\\EA Games\\Need for Speed Underground 2
  - NFSMW: Software\\EA Games\\Need for Speed Most Wanted
  - NFSC:  Software\\Electronic Arts\\Need for Speed Carbon

Resolution encoding differs between games:
  - NFSU, NFSU2, NFSMW use a packed dword: 0x80000000 | (width << 16) | height
  - NFSC uses an index into a fixed resolution table (0-4)

The Widescreen Fix handles aspect ratio correction on top of whatever
base resolution the game loads from the registry.

Called from ui_install.py after mod installs, before shortcut creation.
"""

import os
import re
import time

from log import get_logger

_log = get_logger(__name__)


# -- Registry paths per game --------------------------------------------------
# These are the exact paths each game reads from HKEY_CURRENT_USER.
# In Wine's user.reg, backslashes are doubled.

REGISTRY_PATHS = {
    "nfsu":  "Software\\\\EA Games\\\\Need For Speed Underground",
    "nfsu2": "Software\\\\EA Games\\\\Need for Speed Underground 2",
    "nfsmw": "Software\\\\EA Games\\\\Need for Speed Most Wanted",
    "nfsc":  "Software\\\\Electronic Arts\\\\Need for Speed Carbon",
}

# NFSC also writes a Spanish locale key (Carbono). We write both to
# match what the game expects after a real first launch.
_NFSC_ALT_PATH = "Software\\\\Electronic Arts\\\\Need for Speed Carbono"


# -- Resolution encoding ------------------------------------------------------

def _pack_resolution(width: int, height: int) -> int:
    """Pack width and height into the dword format used by NFSU/NFSU2/NFSMW."""
    return 0x80000000 | (width << 16) | height


# Device resolution presets keyed by config model dir name
# (matches config.get_model_config_dir() return values)
_DEVICE_RESOLUTIONS = {
    "LCD":          (1280, 800),
    "OLED":         (1280, 800),
    "1920x1200":    (1920, 1200),   # Legion Go, Go S, MSI Claw 8
    "1920x1200_144hz": (1920, 1200),  # Legion Go 2
    "1920x1080":    (1920, 1080),   # ROG Ally, Ally X
    "1280x720":     (1280, 720),    # Fallback for docked 720p
    "1280x800":     (1280, 800),    # Fallback
}

# For NFSC, the resolution index doesn't support widescreen natively.
# The Widescreen Fix handles widescreen on top of whatever base the game
# engine loads. Index 2 (1024x768) is the safe default.
_NFSC_RESOLUTION_INDEX = 2


# -- Graphics presets ---------------------------------------------------------
# High quality settings for Steam Deck hardware. These games are from
# 2003-2006 and run at max settings easily on modern APUs.
#
# Values are tuples of (key_name, dword_value). Written as hex dwords
# in user.reg format.

_COMMON_GRAPHICS = [
    ("g_CarEnvironmentMapEnable",    3),
    ("g_CarLodLevel",                1),
    ("g_FSAALevel",                  2),
    ("g_MotionBlurEnable",           1),
    ("g_ParticleSystemEnable",       1),
    ("g_PerformanceLevel",           5),
    ("g_RainEnable",                 1),
    ("g_RoadReflectionEnable",       2),
    ("g_TextureFiltering",           2),
    ("g_VisualTreatment",            1),
    ("g_VSyncOn",                    0),
    ("g_WorldLodLevel",              3),
]

# Per-game graphics overrides and additions
_GAME_GRAPHICS = {
    "nfsu": [
        ("g_AnimatedTextureEnable",      1),
        ("g_BleachByPassEnable",         1),
        ("g_CarEnvironmentMapEnable",    1),
        ("g_CarEnvironmentMapUpdateData", 1),
        ("g_CarLodLevel",                1),
        ("g_FSAALevel",                  0),
        ("g_MotionBlurEnable",           1),
        ("g_OverBrightEnable",           1),
        ("g_ParticleSystemEnable",       1),
        ("g_PerformanceLevel",           3),
        ("g_RainEnable",                 1),
        ("g_RoadReflectionEnable",       0),
        ("g_TextureFiltering",           1),
        ("g_VisualTreatment",            1),
        ("g_VSyncOn",                    0),
        ("g_WorldLodLevel",              2),
    ],
    "nfsu2": [
        ("g_AnimatedTextureEnable",      1),
        ("g_BleachByPassEnable",         1),
        ("g_CarDamageEnable",            0),
        ("g_CarEnvironmentMapEnable",    3),
        ("g_CarEnvironmentMapUpdateData", 1),
        ("g_CarHeadlightEnable",         1),
        ("g_CarLightingEnable",          0),
        ("g_CarLodLevel",                1),
        ("g_CarShadowEnable",            2),
        ("g_CrowdEnable",               1),
        ("g_DepthOfFieldEnable",         1),
        ("g_FogEnable",                  1),
        ("g_FSAALevel",                  2),
        ("g_HorizonFogEnable",           1),
        ("g_LightGlowEnable",           1),
        ("g_LightStreaksEnable",         1),
        ("g_MotionBlurEnable",           1),
        ("g_OverBrightEnable",           1),
        ("g_ParticleSystemEnable",       1),
        ("g_PerformanceLevel",           5),
        ("g_RainEnable",                 1),
        ("g_RoadReflectionEnable",       3),
        ("g_TextureFiltering",           2),
        ("g_TintingEnable",              1),
        ("g_VSyncOn",                    0),
        ("g_WorldLodLevel",              3),
        ("NotFirstTime",                 1),
    ],
    "nfsmw": [
        ("g_CarEnvironmentMapEnable",    0),
        ("g_CarEnvironmentMapUpdateData", 0),
        ("g_CarLodLevel",                0),
        ("g_FSAALevel",                  0),
        ("g_MotionBlurEnable",           1),
        ("g_OverBrightEnable",           0),
        ("g_ParticleSystemEnable",       1),
        ("g_PerformanceLevel",           1),
        ("g_RainEnable",                 1),
        ("g_RoadReflectionEnable",       0),
        ("g_ShadowDetail",               0),
        ("g_TextureFiltering",           0),
        ("g_VisualTreatment",            1),
        ("g_VSyncOn",                    0),
        ("g_WorldLodLevel",              0),
        ("FirstTime",                    1),
    ],
    "nfsc": [
        ("g_AudioMode",                  0),
        ("g_Brightness",                 0),
        ("g_CarEnvironmentMapEnable",    3),
        ("g_CarLodLevel",                1),
        ("g_FSAALevel",                  2),
        ("g_MotionBlurEnable",           1),
        ("g_ParticleSystemEnable",       1),
        ("g_PerformanceLevel",           5),
        ("g_RainEnable",                 1),
        ("g_RoadReflectionEnable",       2),
        ("g_ShaderDetailLevel",          3),
        ("g_ShadowDetail",               0),
        ("g_TextureFiltering",           2),
        ("g_VisualTreatment",            1),
        ("g_VSyncOn",                    0),
        ("g_WorldLodLevel",              3),
        ("FirstTime",                    0),
    ],
}


# -- Wine user.reg helpers ----------------------------------------------------

def _wine_timestamp():
    """Return a Wine-style timestamp line for registry sections."""
    # Wine uses Windows FILETIME (100ns intervals since 1601-01-01)
    # but the exact value doesn't matter for game settings -- the game
    # just reads the values. We use the current unix time as a simple
    # unique value that Wine accepts.
    return str(int(time.time()))


def _format_dword(value: int) -> str:
    """Format an integer as a Wine registry dword string."""
    return f"dword:{value:08x}"


def _build_registry_section(reg_path: str, entries: list) -> str:
    """
    Build a complete Wine user.reg section string.

    reg_path — double-backslash registry path (e.g. "Software\\\\EA Games\\\\...")
    entries  — list of (key_name, formatted_value) tuples where
               formatted_value is already a Wine reg string like
               'dword:85000320' or '"Z:\\\\path\\\\"'

    Returns a string ready to append to user.reg.
    """
    lines = [f"\n[{reg_path}] {_wine_timestamp()}"]
    for key_name, value in entries:
        lines.append(f'"{key_name}"={value}')
    lines.append("")  # trailing newline
    return "\n".join(lines)


def _read_user_reg(compatdata_path: str) -> str | None:
    """Read user.reg from a Wine prefix. Returns None if not found."""
    reg_path = os.path.join(compatdata_path, "pfx", "user.reg")
    if not os.path.exists(reg_path):
        return None
    try:
        with open(reg_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        _log.debug("user.reg read failed", exc_info=True)
        return None


def _write_user_reg(compatdata_path: str, content: str) -> bool:
    """Write user.reg back to a Wine prefix. Returns True on success."""
    reg_path = os.path.join(compatdata_path, "pfx", "user.reg")
    try:
        os.makedirs(os.path.dirname(reg_path), exist_ok=True)
        with open(reg_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except OSError:
        _log.debug("user.reg write failed", exc_info=True)
        return False


def _update_or_append_section(content: str, reg_path: str,
                               entries: list) -> str:
    """
    Update existing registry values in a section, or append a new section
    if it doesn't exist. Preserves all other content in user.reg.

    reg_path — the [Section\\\\Path] to find or create
    entries  — list of (key_name, formatted_value) tuples
    """
    # Escape the path for regex (brackets are literal in the file)
    escaped_path = re.escape(f"[{reg_path}]")

    # Check if section exists
    section_match = re.search(
        escaped_path + r'[^\[]*',
        content,
        re.DOTALL,
    )

    if section_match:
        # Section exists - update values within it
        section_text = section_match.group(0)
        for key_name, value in entries:
            # Try to replace existing key
            key_pattern = re.compile(
                r'^"' + re.escape(key_name) + r'"=.*$',
                re.MULTILINE,
            )
            if key_pattern.search(section_text):
                section_text = key_pattern.sub(
                    f'"{key_name}"={value}',
                    section_text,
                )
            else:
                # Key doesn't exist in section - add before the next section
                # or at end of section
                section_text = section_text.rstrip("\n") + f'\n"{key_name}"={value}\n'

        content = (
            content[:section_match.start()] +
            section_text +
            content[section_match.end():]
        )
    else:
        # Section doesn't exist - append it
        new_section = _build_registry_section(reg_path, entries)
        content = content.rstrip("\n") + "\n" + new_section

    return content


# -- Public API ---------------------------------------------------------------

def write_display_configs(selected_keys: list, installed_games: dict,
                          on_progress=None):
    """
    Write display resolution and graphics settings into each game's
    Wine prefix registry (user.reg) before first launch.

    Must be called AFTER prefix creation (so user.reg exists) and AFTER
    mod installs, but BEFORE shortcut creation.

    selected_keys  — list of game keys the user selected
    installed_games — dict {key: game_dict} enriched by shortcut.enrich_own_games()
    on_progress    — optional callback(msg: str)
    """
    import config as cfg

    def prog(msg):
        if on_progress:
            on_progress(msg)

    # Determine target resolution from device model
    model_dir = cfg.get_model_config_dir()
    resolution = _DEVICE_RESOLUTIONS.get(model_dir)
    if not resolution:
        # Fallback to Steam Deck default
        resolution = (1280, 800)
        prog(f"  !!  Unknown device model '{model_dir}', defaulting to 1280x800")

    width, height = resolution
    packed_res = _pack_resolution(width, height)
    prog(f"  Target resolution: {width}x{height} (packed: 0x{packed_res:08x})")

    applied = 0
    failed = 0

    for key in selected_keys:
        if key not in REGISTRY_PATHS:
            continue
        if key not in installed_games:
            continue

        game = installed_games[key]
        compatdata_path = game.get("compatdata_path")
        install_dir = game.get("install_dir")

        if not compatdata_path:
            prog(f"  !!  {key}: no compatdata path, skipping")
            failed += 1
            continue

        reg_path = REGISTRY_PATHS[key]
        game_name = game.get("name", key)

        # Read existing user.reg
        content = _read_user_reg(compatdata_path)
        if content is None:
            prog(f"  !!  {key}: user.reg not found at {compatdata_path}, skipping")
            failed += 1
            continue

        # Build registry entries
        entries = []

        # Resolution
        if key == "nfsc":
            entries.append(("g_RacingResolution", _format_dword(_NFSC_RESOLUTION_INDEX)))
        else:
            entries.append(("g_RacingResolution", _format_dword(packed_res)))

        # Install paths - Wine Z: drive maps to Linux root
        wine_install = install_dir.replace("/", "\\\\")
        wine_path = f'"Z:{wine_install}\\\\"'
        entries.append(("Install Dir", wine_path))
        entries.append(("InstallDir", wine_path))
        entries.append(("Path", wine_path))

        # Other standard keys
        entries.append(("@", '"INSERTYOURCDKEYHERE"'))
        entries.append(("CD Drive", '"D:\\\\"'))
        entries.append(("Language", '"English US"'))
        entries.append(("CacheSize", _format_dword(0xFFFFFFFF)))
        entries.append(("StreamingInstall", _format_dword(0)))
        entries.append(("SwapSize", _format_dword(0x04600000)))
        entries.append(("VERSION", _format_dword(1)))
        entries.append(("SIZE", _format_dword(0x64)))

        # Graphics settings - use per-game preset if available, else common
        graphics = _GAME_GRAPHICS.get(key, _COMMON_GRAPHICS)
        for gfx_key, gfx_val in graphics:
            entries.append((gfx_key, _format_dword(gfx_val)))

        # Write the section
        content = _update_or_append_section(content, reg_path, entries)

        # NFSC also needs the Spanish locale key written
        if key == "nfsc":
            content = _update_or_append_section(content, _NFSC_ALT_PATH, entries)

        # Write back
        if _write_user_reg(compatdata_path, content):
            prog(f"  ok  {game_name}: display config written ({width}x{height})")
            applied += 1
        else:
            prog(f"  !!  {game_name}: failed to write user.reg")
            failed += 1

    prog(f"Display configs: {applied} written, {failed} failed.")
    return applied, failed


# -- CLI for testing ----------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Fake a minimal game dict for testing
    print("game_config.py - display config writer")
    print("Run through ui_install.py for real usage.")
    print()
    print("Registry paths:")
    for key, path in REGISTRY_PATHS.items():
        print(f"  {key}: {path}")
    print()
    print("Resolution presets:")
    for model, (w, h) in _DEVICE_RESOLUTIONS.items():
        packed = _pack_resolution(w, h)
        print(f"  {model}: {w}x{h} -> 0x{packed:08x}")
