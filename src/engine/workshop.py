"""
workshop.py - Steam Workshop items for games with Workshop support

Steam downloads subscribed items itself into
<library>/steamapps/workshop/content/<appid>/<item id>/; read those first.
For items the user is not subscribed to (a curated pack, dedicated
servers), SteamCMD can download public items anonymously for many games:

    steamcmd +login anonymous +workshop_download_item <appid> <item> +quit

Some games only allow downloads by owners; then SteamCMD needs a login and
this app should send the user to the Workshop page instead
(steam://url/CommunityFilePage/<item>).
"""

import glob
import os
import shutil
import subprocess
import tarfile

import identity
from . import steam
from .log import get_logger
from .net import download

_log = get_logger(__name__)

STEAMCMD_DIR = os.path.join(identity.DATA_DIR, "steamcmd")
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"


def subscribed(appid, steam_root: str = None) -> dict:
    """{item id: folder} of Workshop items Steam already downloaded for appid."""
    out = {}
    for lib in steam.library_dirs(steam_root):
        for d in glob.glob(os.path.join(lib, "workshop", "content", str(appid), "*")):
            if os.path.isdir(d):
                out[os.path.basename(d)] = d
    return out


def steamcmd(on_progress=None) -> str:
    exe = shutil.which("steamcmd")
    if exe:
        return exe
    sh = os.path.join(STEAMCMD_DIR, "steamcmd.sh")
    if not os.path.isfile(sh):
        os.makedirs(STEAMCMD_DIR, exist_ok=True)
        tgz = os.path.join(STEAMCMD_DIR, "steamcmd.tar.gz")
        download(STEAMCMD_URL, tgz, on_progress, "SteamCMD")
        with tarfile.open(tgz) as t:
            t.extractall(STEAMCMD_DIR, filter="data")
        os.remove(tgz)
    return sh


def download_item(appid, item, on_line=None, timeout: int = 3600) -> str | None:
    """Anonymous SteamCMD download. Returns the item folder, or None if refused."""
    exe = steamcmd()
    cmd = [exe, "+login", "anonymous", "+workshop_download_item", str(appid), str(item), "validate", "+quit"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if on_line:
        for l in p.stdout.splitlines():
            on_line(l)
    base = os.path.dirname(exe) if exe.endswith(".sh") else os.path.expanduser("~/.local/share/Steam")
    for root in (base, os.path.expanduser("~/Steam"), os.path.expanduser("~/.steam/steamcmd")):
        d = os.path.join(root, "steamapps", "workshop", "content", str(appid), str(item))
        if os.path.isdir(d):
            return d
    _log.warning("workshop item %s not downloaded: %s", item, p.stdout[-300:])
    return None


def page_uri(item) -> str:
    return f"steam://url/CommunityFilePage/{item}"
