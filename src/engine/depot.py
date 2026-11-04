"""
depot.py - download old game versions from Steam (depot downgrade)

Many community clients only work with an older build of a game (a 32-bit
exe, a pre-update data format). Steam keeps every old build as a depot
manifest. Two ways to get one, both need the user's own Steam license:

  QR (recommended)  DepotDownloader logs in with a QR code the user scans
                    with the Steam mobile app; no password is typed into
                    this app. Later depots reuse the session (-remember-password).
  manual            open the Steam console (steam://open/console) and paste
                    download_depot <app> <depot> <manifest>; Steam puts the
                    files in ubuntu12_32/steamapps/content/app_<app>/depot_<depot>/.

Merge into a sub folder (game_dir/downgrade/) when the stock game must keep
working, or over the game when it does not. Either way write a receipt
listing every merged file and its size: it is how a later run knows the
downgrade is still in place (Steam Verify or an update silently undoes it)
without trusting the app's own config, which a reset would lose.

Depot and manifest ids are per game: find them on SteamDB (depot history)
or in community gists, and put them in games.py.
"""

import os
import re
import shutil
import subprocess

import identity
from . import steam
from .detect_hw import detect_arch
from .files import read_json, write_json
from .log import get_logger, redact_also
from .net import download, github_asset

_log = get_logger(__name__)

DD_DIR = os.path.join(identity.DATA_DIR, "depotdownloader")
RECEIPT = f"{identity.APP_ID}_depot.json"
# Data files only: exes and dlls get replaced by mod clients afterwards
_NOT_TRACKED = (".exe", ".dll", ".asi", ".ini", ".cfg", ".txt", ".json", ".log")


def install_depotdownloader(on_progress=None) -> str:
    arch = "linux-arm64" if detect_arch() == "aarch64" else "linux-x64"
    exe = os.path.join(DD_DIR, "DepotDownloader")
    if os.path.isfile(exe):
        return exe
    url, digest = github_asset("SteamRE/DepotDownloader", f"{arch}.zip")
    os.makedirs(DD_DIR, exist_ok=True)
    z = os.path.join(DD_DIR, "dd.zip")
    download(url, z, on_progress, "DepotDownloader", digest=digest)
    from .files import extract
    extract(z, DD_DIR)
    os.remove(z)
    os.chmod(exe, 0o755)
    return exe


def run_depotdownloader(app: int, depot: int, manifest: str, out_dir: str, username: str = None,
                        on_qr=None, on_line=None, files: list = None) -> tuple:
    """
    Download one depot manifest into out_dir. Returns (ok, username).

    on_qr(text)   -- QR code text block to show (convert with ui.qr_pixmap); it
                     refreshes on its own while the user is slow, so keep showing
                     whatever came last
    on_line(text) -- every output line (progress, errors)
    files         -- optional file list filter (DepotDownloader -filelist)
    username      -- from a previous call: reuse the remembered session
    """
    exe = install_depotdownloader()
    cmd = [exe, "-app", str(app), "-depot", str(depot), "-manifest", str(manifest), "-dir", out_dir, "-remember-password"]
    cmd += ["-username", username] if username else ["-qr"]
    flist = None
    if files:
        flist = os.path.join(DD_DIR, f"filelist_{depot}.txt")
        with open(flist, "w") as f:
            f.write("\n".join(files))
        cmd += ["-filelist", flist]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=DD_DIR)
    qr, user = [], username
    for line in p.stdout:
        line = line.rstrip("\n")
        if "▀" in line or "▄" in line or "█" in line:
            qr.append(line)
            continue
        if qr and on_qr:
            on_qr("\n".join(qr)); qr = []
        m = re.search(r"Logging '([^']+)' into Steam3", line)
        if m:
            user = m.group(1)
            redact_also(user)
        if on_line:
            on_line(line)
    ok = p.wait() == 0
    return ok, user


def console_commands(app: int, depots: list) -> str:
    """Text for the manual path: one download_depot line per (depot, manifest)."""
    return "\n".join(f"download_depot {app} {d} {m}" for d, m in depots)


def console_content_dir(app: int, depot: int, steam_root: str = None) -> str:
    return os.path.join(steam_root or steam.STEAM_ROOT, "ubuntu12_32", "steamapps", "content", f"app_{app}", f"depot_{depot}")


def merge(staging: str, target: str, on_progress=None) -> list:
    """
    Move staged depot files over target (delete-then-move, so free space
    never needs two copies of a big file). Writes the receipt. Returns rel paths.
    """
    prog = on_progress or (lambda *a: None)
    files = []
    for d, _, names in os.walk(staging):
        for n in names:
            if n.startswith(".DepotDownloader"):
                continue
            files.append(os.path.relpath(os.path.join(d, n), staging))
    files = [f for f in files if ".DepotDownloader" not in f.split(os.sep)]
    for i, rel in enumerate(files):
        src, dst = os.path.join(staging, rel), os.path.join(target, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.lexists(dst):
            os.remove(dst)
        shutil.move(src, dst)
        if i % 25 == 0:
            prog(int(i * 100 / max(len(files), 1)), f"Merging {i}/{len(files)}")
    rec = {rel.replace(os.sep, "/"): os.path.getsize(os.path.join(target, rel))
           for rel in files if not rel.lower().endswith(_NOT_TRACKED)}
    write_json(os.path.join(target, RECEIPT), {"files": rec})
    prog(100, f"Merged {len(files)} files")
    return files


def still_applied(target: str) -> bool | None:
    """True if every receipt file is present with its size, False if not, None without a receipt."""
    r = read_json(os.path.join(target, RECEIPT))
    if not r:
        return None
    return all(os.path.getsize(os.path.join(target, rel)) == size
               if os.path.isfile(os.path.join(target, rel)) else False
               for rel, size in r.get("files", {}).items())


def clear_receipt(target: str):
    try: os.remove(os.path.join(target, RECEIPT))
    except OSError: pass


def cleanup():
    """DepotDownloader keeps a login token; remove it when the downgrade is done."""
    shutil.rmtree(DD_DIR, ignore_errors=True)
