#!/usr/bin/env python3
"""
check.py - offline checks for the NFS-specific code on a fake tree

    python3 tools/check.py

Detection (speed.exe shared by U and MW, U vs U2 folder names), mod staging
(only the kept files land, the Widescreen Fix ini is patched before the
receipt is written), registry values, and shortcut appid stability.
Runs with HOME pointed at a temp folder; touches nothing real.
"""

import os
import sys
import tempfile
import zipfile

tmp = tempfile.mkdtemp(prefix="nfsbl_check_")
os.environ["HOME"] = tmp
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import identity  # noqa: E402
identity.DATA_DIR = os.path.join(tmp, "data")
identity.CONFIG_PATH = os.path.join(tmp, "config.json")

from engine import detect, mods, steam  # noqa: E402
from installers import nfs  # noqa: E402


def touch(*parts):
    p = os.path.join(*parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()


# --- detection
g = os.path.join(tmp, "Games")
touch(g, "Need for Speed Underground", "Speed.exe")
touch(g, "Need for Speed Underground", "TRACKS", "streaml1ra.bun")   # casing differs from the sentinel
touch(g, "NFS_Underground_2", "SPEED2.EXE")
touch(g, "Most Wanted", "inner", "speed.exe")                        # nested one level down
touch(g, "Most Wanted", "inner", "Tracks", "L2RA.BUN")
touch(g, "Carbon Collectors", "NFSC.exe")
touch(g, "Underground fake", "speed.exe")                            # name matches, no sentinel
detect.OWN_SCAN[:] = [g]
found = detect.find_own()
assert sorted(found) == ["nfsc", "nfsmw", "nfsu", "nfsu2"], sorted(found)
assert found["nfsmw"]["install_dir"].endswith("Most Wanted/inner"), found["nfsmw"]["install_dir"]
assert found["nfsu"]["exe_path"].endswith("Speed.exe")
assert found["nfsu2"]["install_dir"].endswith("NFS_Underground_2")

# --- mod staging: the Widescreen Fix keeps dinput8 + scripts/, Extra Options drops its dinput8
def zip_of(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, "[MAIN]\nAutoFitFE = 0\n[MISC]\nImproveGamepadSupport = 1\n" if n.endswith("WidescreenFix.ini") else "x")


zips = os.path.join(tmp, "zips"); os.makedirs(zips)
zip_of(os.path.join(zips, "NFSUnderground.WidescreenFix.zip"),
       ["dinput8.dll", "scripts/NFSUnderground.WidescreenFix.asi", "scripts/NFSUnderground.WidescreenFix.ini"])
zip_of(os.path.join(zips, "NFSU.ExOpts.v3.0.1.1337.zip"),
       ["dinput8.dll", "Read Me.txt", "scripts/NFSUExtraOptions.asi", "scripts/NFSUExtraOptionsSettings.ini"])
zip_of(os.path.join(zips, "Release-UG-Pack.zip"),
       ["dinput8.dll", "README.md", "scripts/NFSU_XtendedInput.asi", "scripts/NFSU_XtendedInput.ini", "Global/UG_ConsoleButtons.tpk"])
mods.download = lambda url, dest, *a, **k: __import__("shutil").copy(os.path.join(zips, os.path.basename(url)), dest)

game = found["nfsu"]["install_dir"]
mods.install_all(game, nfs.mod_list("nfsu"), "nfsu")
files = mods.receipt("nfsu")["files"]
assert files["dinput8.dll"]["mod"] == "widescreen_fix", files["dinput8.dll"]
assert "Read Me.txt" not in files and "README.md" not in files
assert "TRACKS/UG_ConsoleButtons.tpk" not in files and "Global/UG_ConsoleButtons.tpk" in files
ini = open(os.path.join(game, "scripts", "NFSUnderground.WidescreenFix.ini")).read()
assert "AutoFitFE=1" in ini and "ImproveGamepadSupport=0" in ini, ini
assert mods.verify("nfsu", game) == []                               # patched ini matches its receipt
mods.remove_all(game, "nfsu")
assert not os.path.exists(os.path.join(game, "dinput8.dll")) and not os.path.exists(os.path.join(game, "scripts"))

# --- registry values
v = nfs.reg_values("nfsmw", "/run/media/deck/SD/Games/MW", "1280x800")
assert v["g_RacingResolution"] == 0x85000320 and v["Install Dir"] == "Z:\\run\\media\\deck\\SD\\Games\\MW\\"
assert nfs.reg_values("nfsc", "/x", "1920x1200_144hz")["g_RacingResolution"] == nfs.NFSC_RES_INDEX

# --- appid: same formula as the pre-engine shortcut.py (crc32 of quoted exe + name, top bit set)
import binascii  # noqa: E402
gm = found["nfsc"]
old = (binascii.crc32(f'"{gm["exe_path"]}"{gm["name"]}'.encode()) & 0xFFFFFFFF) | 0x80000000
assert nfs.appid(gm) == old == steam.shortcut_appid(f'"{gm["exe_path"]}"', gm["name"])

print("ok")
