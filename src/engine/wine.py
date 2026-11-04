"""
wine.py - prefix tweaks older (and newer) Windows games often need

    DLL overrides     so a mod's d3d9.dll / dinput8.dll / dsound.dll is loaded
                      instead of Wine's own (ASI loaders, wrappers, injectors)
    registry          install paths, CD keys, settings games read from the registry
    winetricks verbs  vcrun, d3dx9, xact, dotnet... via winetricks or protontricks
    Proton env        PROTON_*, DXVK_*, VKD3D_* switches for the launch option

Two ways to override a DLL, pick one per game:
  launch option   WINEDLLOVERRIDES="dinput8=n,b" %command%   (engine.launch)
                  No prefix edit; travels with the Steam launch; undone by
                  clearing the option. Best for Steam games.
  prefix registry set_dll_overrides(compat, {...}) writes user.reg.
                  Works for every launcher (non-Steam, Heroic, Lutris).

Registry files are edited directly (fast, no Wine run) and only while
nothing runs in the prefix: Wine rewrites user.reg from memory on exit.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time

from . import proton
from .files import backup_file
from .log import get_logger

_log = get_logger(__name__)

HKCU, HKLM = "user.reg", "system.reg"


def _reg_path(compat: str, hive: str) -> str:
    return os.path.join(compat, "pfx", hive)


def _esc_key(key: str) -> str:
    return key.replace("\\", "\\\\")


def _fmt(value) -> str:
    if isinstance(value, int):
        return f"dword:{value:08x}"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_reg(compat: str, hive: str, key: str, values: dict):
    """
    Set values under key (e.g. r"Software\\Wine\\DllOverrides") in user.reg
    (HKCU) or system.reg (HKLM; give the key without "HKEY_LOCAL_MACHINE\\").
    str values are REG_SZ, int values REG_DWORD. None deletes a value.
    For 32-bit games on 64-bit Windows, HKLM keys usually belong under
    Software\\Wow6432Node\\...; write both when unsure.
    """
    path = _reg_path(compat, hive)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{path} (prefix not initialised?)")
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        text = f.read()
    header = f"[{_esc_key(key)}]"
    lines = text.split("\n")
    idx = next((i for i, l in enumerate(lines) if l.lower().startswith(header.lower())), None)
    if idx is None:
        lines += ["", f"{header} {int(time.time())}", f"#time={int(time.time() * 1e7):x}"]
        idx = len(lines) - 2
    end = idx + 1
    while end < len(lines) and lines[end].strip() and not lines[end].startswith("["):
        end += 1
    body = lines[idx + 1:end]
    for name, val in values.items():
        q = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"=' if name != "@" else "@="
        body = [l for l in body if not l.lower().startswith(q.lower())]
        if val is not None:
            body.append(q + _fmt(val))
    lines[idx + 1:end] = body
    backup_file(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)


def get_reg(compat: str, hive: str, key: str) -> dict:
    path = _reg_path(compat, hive)
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return out
    m = re.search(r"^\[" + re.escape(_esc_key(key)) + r"\][^\n]*\n(.*?)(?=^\[|\Z)", text, re.M | re.S | re.I)
    for name, val in re.findall(r'^"((?:[^"\\]|\\.)*)"=(.*)$', m.group(1) if m else "", re.M):
        out[name.replace("\\\\", "\\")] = val.strip('"').replace("\\\\", "\\")
    return out


def set_dll_overrides(compat: str, dlls: dict):
    """dlls = {"dinput8": "native,builtin", "d3d9": "native"}; value None removes the override."""
    set_reg(compat, HKCU, r"Software\Wine\DllOverrides", dlls)


def import_reg(compat: str, reg_text: str, proton_path: str = None):
    """
    Import a .reg file the slow, exact way (regedit inside the prefix). Use
    for keys copied from a real Windows install, binary values, many keys.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".reg", delete=False, encoding="utf-16") as f:
        f.write("﻿Windows Registry Editor Version 5.00\r\n\r\n" + reg_text.replace("\n", "\r\n"))
        tmp = f.name
    try:
        r = proton.run(compat, ["regedit", "/S", proton.z_path(tmp)], proton_path, timeout=180)
        return r.returncode == 0
    finally:
        os.unlink(tmp)


def winetricks(compat: str, verbs: list, proton_path: str = None, timeout: int = 1800) -> bool:
    """
    Run winetricks verbs (vcrun2019, d3dx9_43, xact, corefonts...) in a prefix
    with Proton's own wine. Uses protontricks when the prefix is a Steam app
    and protontricks is installed, else winetricks. Returns False when
    neither exists: tell the user, do not fail the whole install.
    """
    appid = os.path.basename(compat.rstrip("/"))
    if appid.isdigit() and int(appid) < 1 << 31 and shutil.which("protontricks"):
        cmd = ["protontricks", appid, "-q", *verbs]
        env = dict(os.environ)
    elif shutil.which("winetricks"):
        p = proton_path or proton.proton_path()
        wine_bin = os.path.join(os.path.dirname(p), "files", "bin")
        env = dict(os.environ, WINEPREFIX=os.path.join(compat, "pfx"), WINE=os.path.join(wine_bin, "wine"),
                   WINESERVER=os.path.join(wine_bin, "wineserver"), WINEDLLOVERRIDES="mscoree,mshtml=")
        cmd = ["winetricks", "-q", *verbs]
    elif shutil.which("flatpak") and subprocess.run(["flatpak", "info", "com.github.Matoking.protontricks"],
                                                    capture_output=True).returncode == 0 and appid.isdigit():
        cmd = ["flatpak", "run", "com.github.Matoking.protontricks", appid, "-q", *verbs]
        env = dict(os.environ)
    else:
        _log.warning("winetricks/protontricks not found; verbs %s skipped", verbs)
        return False
    _log.info("winetricks %s", " ".join(verbs))
    r = subprocess.run(cmd, env=env, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        _log.warning("winetricks failed: %s", r.stderr.decode(errors="replace")[-500:])
    return r.returncode == 0


def copy_dlls_from_default_pfx(compat: str, names: list, proton_path: str = None) -> list:
    """
    Copy named DLLs (e.g. ["d3dx9_43.dll", "xinput1_3.dll"]) from Proton's
    default prefix into this prefix's system32/syswow64. A fast, offline
    substitute for some winetricks verbs: GE-Proton ships many of them.
    """
    src = proton.default_pfx(proton_path)
    done = []
    if not src:
        return done
    for d in ("system32", "syswow64"):
        sdir = os.path.join(src, "drive_c", "windows", d)
        ddir = os.path.join(compat, "pfx", "drive_c", "windows", d)
        if os.path.islink(ddir):
            continue  # shared DLL folder: already the full set
        for n in names:
            s = os.path.join(sdir, n)
            if os.path.isfile(s):
                os.makedirs(ddir, exist_ok=True)
                shutil.copy2(s, os.path.join(ddir, n)); done.append(f"{d}/{n}")
    return done


# Proton / DXVK / VKD3D switches worth knowing (set in the launch option)
PROTON_ENV = {
    "PROTON_USE_WINED3D=1":        "OpenGL instead of DXVK for D3D9-11; fixes some very old games",
    "PROTON_NO_ESYNC=1":           "turn off esync when a game hangs or stutters on sync",
    "PROTON_NO_FSYNC=1":           "same for fsync",
    "PROTON_NO_NTSYNC=1":          "same for ntsync (newer kernels and Proton)",
    "PROTON_ENABLE_NVAPI=1":       "expose NVAPI (DLSS) on NVIDIA",
    "PROTON_LOG=1":                "write ~/steam-<appid>.log for debugging",
    "PROTON_FORCE_LARGE_ADDRESS_AWARE=1": "give 32-bit games 4 GB address space (on by default in many builds)",
    "PROTON_HEAP_DELAY_FREE=1":    "works around use-after-free crashes in some old games",
    "DXVK_FRAME_RATE=60":          "cap frame rate in DXVK (physics tied to FPS in old engines)",
    "DXVK_ASYNC=1":                "async shader compile (GE-Proton only)",
    "DXVK_HUD=fps":                "FPS overlay",
    "VKD3D_CONFIG=dxr":            "D3D12 ray tracing in VKD3D-Proton",
    "WINE_FULLSCREEN_FSR=1":       "FSR upscaling when the game runs below native resolution (GE-Proton)",
    "SteamDeck=1":                 "some games pick Deck-friendly defaults with this",
    "WINEDLLOVERRIDES=\"x=n,b\"":  "load a mod DLL x.dll instead of Wine's",
}
