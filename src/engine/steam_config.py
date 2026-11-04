"""
steam_config.py - edits to Steam's text config files, with an undo ledger

    localconfig.vdf  (per account)  LaunchOptions, Steam Input on/off,
                                    Deck "default launch option" picks
    config.vdf       (global)       CompatToolMapping (which Proton runs an app)
    configset_*.vdf  (per account)  which controller template an app uses

Every function here must be called with Steam closed (steam.kill_steam):
Steam keeps these files in memory and writes them back on exit, so an edit
made while it runs is lost.

Every edit is recorded in the ledger (identity.LEDGER_PATH, atomic JSON)
so undo_all() can reverse exactly what this app changed instead of
regex-sweeping the user's files.
"""

import json
import os
import re

import identity
from . import steam, vdf
from .files import read_json, write_json
from .log import get_logger

_log = get_logger(__name__)

LEDGER_PATH = identity.LEDGER_PATH


# --- ledger

def _ledger() -> dict:
    return read_json(LEDGER_PATH, {}) or {}


def _record(section: str, *path, value):
    led = _ledger()
    node = led.setdefault(section, {})
    for p in path[:-1]:
        node = node.setdefault(str(p), {})
    if value is None:
        node.pop(str(path[-1]), None)
    else:
        node[str(path[-1])] = value
    try:
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        write_json(LEDGER_PATH, led)
    except OSError:
        _log.debug("ledger write failed", exc_info=True)


# --- localconfig.vdf

def _localconfigs(steam_root=None):
    for uid in steam.find_uids(steam_root):
        p = os.path.join(steam.userdata(steam_root), uid, "config", "localconfig.vdf")
        if os.path.isfile(p):
            yield uid, p, vdf.read(p)


def _app_span(text: str, appid: str):
    # Software/Valve/Steam/apps sits near the top of the file; Steam's own
    # DefaultLaunchOption entries live later under WebStorage, so prefer the real path
    return (vdf.find_path(text, "Software", "Valve", "Steam", "apps", appid)
            or vdf.find_path(text, "Software", "Valve", "Steam", "Apps", appid))


def _ensure_app(text: str, appid: str):
    """Create an empty apps/<appid> block if the account never ran the game."""
    span = _app_span(text, appid)
    if span:
        return text, span
    apps = vdf.find_path(text, "Software", "Valve", "Steam", "apps") or vdf.find_path(text, "Software", "Valve", "Steam", "Apps")
    if not apps:
        return text, None
    # Insert before the closing brace's line, indented one level below "apps"
    close_line = text.rfind("\n", 0, apps[1]) + 1
    ind = re.match(r"[ \t]*", text[close_line:]).group(0) + "\t"
    text = text[:close_line] + f'{ind}"{appid}"\n{ind}{{\n{ind}}}\n' + text[close_line:]
    return text, _app_span(text, appid)


def _set_app_value(steam_root, appid, key, value, append=False, create=True):
    appid = str(appid)
    esc = vdf.escape(value)
    for uid, path, text in _localconfigs(steam_root):
        text, span = _ensure_app(text, appid) if create else (text, _app_span(text, appid))
        if not span:
            continue
        o, c = span
        inner = vdf.set_flat_value(text[o + 1:c], key, esc, append=append)
        if vdf.write_checked(path, text[:o + 1] + inner + text[c:]):
            _record("localconfig", uid, appid, key, value=value)


def get_launch_options(appid, steam_root=None) -> dict:
    """{uid: current LaunchOptions} (unescaped)."""
    out = {}
    for uid, _, text in _localconfigs(steam_root):
        span = _app_span(text, str(appid))
        if span:
            flat, _ = vdf.split_flat(text[span[0] + 1:span[1]])
            m = vdf.value_re("LaunchOptions").search(flat)
            out[uid] = re.sub(r'\\(.)', r'\1', m.group(2)) if m else ""
    return out


def set_launch_options(appid, options: str, steam_root=None, append: bool = False):
    """
    Set an app's launch options for every account. Replaces by default:
    appending to whatever is there is how stale options from older
    versions pile up.
    """
    _set_app_value(steam_root, appid, "LaunchOptions", options, append=append)


def clear_launch_options(appid, steam_root=None):
    for uid, path, text in _localconfigs(steam_root):
        span = _app_span(text, str(appid))
        if not span:
            continue
        flat, rest = vdf.split_flat(text[span[0] + 1:span[1]])
        m = vdf.value_re("LaunchOptions").search(flat)
        if not m or not m.group(2).strip():
            continue
        flat = flat[:m.start(2)] + flat[m.end(2):]
        if vdf.write_checked(path, text[:span[0] + 1] + flat + rest + text[span[1]:]):
            _record("localconfig", uid, str(appid), "LaunchOptions", value="")


def set_steam_input(appid, on: bool = True, steam_root=None):
    """UseSteamControllerConfig: 1 forces Steam Input on (needed for template-driven controls)."""
    _set_app_value(steam_root, appid, "UseSteamControllerConfig", "1" if on else "0")


_INTERSTITIAL = re.compile(
    r'"Deck_ConfiguratorInterstitialApps_AppLauncherInteractionIssues"\s*"[^"]*"\s*"apps"\s*\{', re.I)


def clear_default_launch_option(appids, steam_root=None):
    """
    Remove a remembered launch-menu choice from the Deck configurator block,
    so Steam shows the launch menu again. A remembered pick hides any menu
    entries added with engine.appinfo.
    """
    for uid, path, text in _localconfigs(steam_root):
        m = _INTERSTITIAL.search(text)
        if not m:
            continue
        o = m.end() - 1
        c = vdf.block_end(text, o)
        if c == -1:
            continue
        block, changed = text[o + 1:c], False
        for appid in appids:
            span = vdf.find_block(block, str(appid))
            if span:
                start = block.rfind("\n", 0, span[0] - len(str(appid)) - 2) + 1
                block = block[:start] + block[span[1] + 1:].lstrip("\n")
                changed = True
        if changed:
            vdf.write_checked(path, text[:o + 1] + block + text[c:])


# --- config.vdf CompatToolMapping

def _compat_entry(appid, tool, ind="\t\t\t\t"):
    return (f'{ind}"{appid}"\n{ind}{{\n{ind}\t"name"\t\t"{tool}"\n'
            f'{ind}\t"config"\t\t""\n{ind}\t"priority"\t\t"250"\n{ind}}}\n')


def set_compat_tool(appids, tool: str, steam_root=None):
    """
    Map appids (Steam games or shortcut appids) to a compatibility tool by
    folder name, e.g. "GE-Proton10-34". Steam only expands %command% in a
    launch option when a compat tool is set, so a Windows game with a
    launch option needs one even if something else runs Proton later.
    """
    path = steam.config_vdf(steam_root)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    text = vdf.read(path)
    for appid in map(str, appids):
        mapping = vdf.find_block(text, "CompatToolMapping")
        if not mapping:
            st = vdf.find_path(text, "Software", "Valve", "Steam") or vdf.find_path(text, "Software", "Valve", "steam")
            if not st:
                raise RuntimeError("config.vdf has no Software/Valve/Steam block")
            text = text[:st[0] + 1] + '\n\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n\t\t\t\t}' + text[st[0] + 1:]
            mapping = vdf.find_block(text, "CompatToolMapping")
        o, c = mapping
        # Match the file's own indentation so an edit changes only what it must
        ml = text.rfind("\n", 0, text.rfind('"CompatToolMapping"', 0, o)) + 1
        ind = re.match(r"[ \t]*", text[ml:]).group(0) + "\t"
        entry = vdf.find_block(text, appid, o + 1, c)
        if entry:
            ls = text.rfind("\n", 0, entry[0] - len(appid) - 2) + 1
            text = text[:ls] + _compat_entry(appid, tool, ind).rstrip("\n") + text[entry[1] + 1:]
        else:
            text = text[:o + 1] + "\n" + _compat_entry(appid, tool, ind).rstrip("\n") + text[o + 1:]
    if vdf.write_checked(path, text):
        for a in appids:
            _record("config_vdf", "CompatToolMapping", str(a), value=tool)


def clear_compat_tool(appids, steam_root=None):
    """
    Remove the mapping. Needed for shortcuts that launch host tools (flatpak,
    a native script): with a compat tool Steam wraps the launch in the Steam
    Linux Runtime container, where host binaries are not visible.
    """
    path = steam.config_vdf(steam_root)
    if not os.path.isfile(path):
        return
    text = vdf.read(path)
    changed = False
    for appid in map(str, appids):
        mapping = vdf.find_block(text, "CompatToolMapping")
        entry = mapping and vdf.find_block(text, appid, mapping[0] + 1, mapping[1])
        if entry:
            ls = text.rfind("\n", 0, entry[0] - len(appid) - 2)
            text = text[:ls] + text[entry[1] + 1:]
            changed = True
    if changed and vdf.write_checked(path, text):
        for a in appids:
            _record("config_vdf", "CompatToolMapping", str(a), value=None)


def get_compat_tool(appid, steam_root=None) -> str | None:
    try:
        d = vdf.loads(vdf.read(steam.config_vdf(steam_root)))
    except OSError:
        return None
    m = vdf.get_ci(d, "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping", str(appid))
    return m.get("name") if isinstance(m, dict) else None


# --- controller configsets

def patch_configset(path: str, key: str, template: str):
    """
    Point key (an appid, a game's name key, or a shortcut title key) at a
    template file name in a configset. Creates the file if missing.
    Configset entries are one level deep, so the block regex is safe here;
    do not reuse it for deeper files.
    """
    entry = f'\t"{key}"\n\t{{\n\t\t"template"\t\t"{template}"\n\t}}\n'
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = '"controller_config"\n{\n' + entry + "}\n"
    else:
        text = vdf.read(path)
        rx = re.compile(r'\t"' + re.escape(key) + r'"\n\t\{[^}]*\}\n?', re.S)
        if rx.search(text):
            text = rx.sub(lambda m: entry, text, count=1)
        else:
            text = text.rstrip()
            text = (text[:-1].rstrip() + "\n" + entry + "}\n") if text.endswith("}") else ('"controller_config"\n{\n' + entry + "}\n")
    if vdf.write_checked(path, text):
        _record("configsets", os.path.basename(path), key, value=template)


def remove_configset_key(path: str, key: str):
    if not os.path.isfile(path):
        return
    text = vdf.read(path)
    new = re.sub(r'\t"' + re.escape(key) + r'"\n\t\{[^}]*\}\n?', "", text, flags=re.S)
    if new != text:
        vdf.write_checked(path, new)


# --- undo

def undo_all(steam_root=None, on_progress=None):
    """
    Reverse every recorded edit: clear launch options and Steam Input keys we
    set, remove our compat tool mappings and configset keys. Steam must be
    closed. Used by the uninstaller and by Reset.
    """
    prog = on_progress or (lambda *a: None)
    led = _ledger()
    for uid, apps in led.get("localconfig", {}).items():
        for appid, keys in apps.items():
            if "LaunchOptions" in keys:
                clear_launch_options(appid, steam_root)
            if "UseSteamControllerConfig" in keys:
                _set_app_value(steam_root, appid, "UseSteamControllerConfig", "0", create=False)
            prog(f"  localconfig {appid} restored")
    compat = led.get("config_vdf", {}).get("CompatToolMapping", {})
    if compat:
        clear_compat_tool(list(compat), steam_root)
        prog(f"  {len(compat)} compat tool mapping(s) removed")
    cfg_roots = [os.path.join(steam_root or steam.STEAM_ROOT, "steamapps", "common", "Steam Controller Configs", uid, "config")
                 for uid in steam.find_uids(steam_root)]
    for name, keys in led.get("configsets", {}).items():
        for root in cfg_roots:
            for key in keys:
                remove_configset_key(os.path.join(root, name), key)
    if led.get("configsets"):
        prog("  controller configset entries removed")
    try:
        os.remove(LEDGER_PATH)
    except OSError:
        pass


def dump_ledger() -> str:
    return json.dumps(_ledger(), indent=2)
