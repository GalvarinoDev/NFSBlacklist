"""
proton.py - GE-Proton install, Proton prefixes, running Windows programs

No Proton version is ever hardcoded. install_ge_proton() saves whatever it
downloaded or found as config "ge_proton_version"; proton_path() prefers
that, then the newest GE-Proton on disk, then the newest Valve Proton.

Prefixes: Steam makes a game's prefix (compatdata/<appid>/pfx) on first
launch, but installers often need it before that (registry keys, files in
AppData, running a setup.exe). Initialising one with `proton run` takes
60-180 s. ensure_prefixes() initialises one donor and clones it to the
rest in about 2 s each, with system32/syswow64 symlinked to one shared copy
(~725 MB per prefix down to ~120 MB).
"""

import os
import re
import shutil
import subprocess
import tempfile
import time

import identity
from . import config, steam
from .detect_hw import detect_arch
from .log import get_logger
from .net import download, fetch, github_release

_log = get_logger(__name__)

GE_REPO = "GloriousEggroll/proton-ge-custom"
COMPAT_DIRS = [os.path.join(steam.HOME, ".local/share/Steam/compatibilitytools.d"),
               os.path.join(steam.STEAM_ROOT, "compatibilitytools.d")]
COMPAT_DIR = COMPAT_DIRS[0]
SHARED_DLLS = os.path.join(identity.DATA_DIR, "shared_dlls")


def _vkey(name: str):
    return tuple(int(p) for p in re.findall(r"\d+", name))


def newest_proton_dir(parent: str, prefix: str) -> str | None:
    """Newest <prefix>* folder with a proton script; numeric sort (9-28 > 9-5, 10 > 9)."""
    if not os.path.isdir(parent):
        return None
    names = [d for d in os.listdir(parent) if d.startswith(prefix) and os.path.exists(os.path.join(parent, d, "proton"))]
    return max(names, key=_vkey, default=None)


def install_ge_proton(on_progress=None) -> str:
    """
    Make sure the latest GE-Proton is in compatibilitytools.d and return its
    folder name (what Steam's CompatToolMapping needs). Picks the asset for
    this CPU (x86_64 / aarch64) and checks it against the release sha512sum.
    """
    prog = on_progress or (lambda *a: None)
    prog(0, "Checking GE-Proton...")
    arch = detect_arch()
    try:
        rel = github_release(GE_REPO)
    except Exception as ex:
        local = newest_proton_dir(COMPAT_DIR, "GE-Proton")
        if local:
            _log.warning("GE-Proton lookup failed (%s), using %s", ex, local)
            config.put("ge_proton_version", local)
            return local
        raise
    tar = next((a for a in rel["assets"] if a["name"].endswith(f"-{arch}.tar.gz")), None) \
        or next((a for a in rel["assets"] if a["name"].endswith(".tar.gz") and arch == "x86_64"), None)
    if not tar:
        raise RuntimeError(f"no {arch} GE-Proton build in {rel['tag_name']}")
    # Newer tarballs extract to the asset name (GE-Proton11-7-x86_64), not the tag;
    # Steam registers tools by folder name, so use what the archive contains
    name = tar["name"][:-len(".tar.gz")]
    for cand in (name, rel["tag_name"]):
        if any(os.path.exists(os.path.join(d, cand, "proton")) for d in COMPAT_DIRS):
            config.put("ge_proton_version", cand)
            prog(100, f"{cand} is up to date")
            return cand
    sums = next((a for a in rel["assets"] if a["name"] == tar["name"].replace(".tar.gz", ".sha512sum")), None)
    digest = None
    if sums:
        try:
            digest = "sha512:" + fetch(sums["browser_download_url"]).decode().split()[0]
        except Exception:
            _log.warning("GE-Proton checksum unavailable, installing unverified")
    os.makedirs(COMPAT_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ge_") as tmp:
        path = os.path.join(tmp, tar["name"])
        download(tar["browser_download_url"], path, lambda p, m: prog(int(p * 0.85), m), name, digest=digest)
        prog(88, f"Extracting {name}...")
        # system tar: much faster and lighter than tarfile on a 500 MB archive
        r = subprocess.run(["tar", "-xzf", path, "-C", COMPAT_DIR], capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f"GE-Proton extract failed: {r.stderr.decode(errors='replace')[:200]}")
    got = name if os.path.isdir(os.path.join(COMPAT_DIR, name)) else rel["tag_name"]
    config.put("ge_proton_version", got)
    prog(100, f"{got} installed")
    return got


def proton_path(steam_root=None) -> str | None:
    """Path to the proton script to use: saved GE-Proton, newest GE-Proton, newest Valve Proton."""
    pinned = config.get("ge_proton_version")
    dirs = COMPAT_DIRS + ([os.path.join(steam_root, "compatibilitytools.d")] if steam_root else [])
    if pinned:
        for d in dirs:
            if os.path.exists(os.path.join(d, pinned, "proton")):
                return os.path.join(d, pinned, "proton")
    for d in dirs:
        n = newest_proton_dir(d, "GE-Proton")
        if n:
            return os.path.join(d, n, "proton")
    best = None
    for lib in steam.library_dirs(steam_root):
        common = os.path.join(lib, "common")
        n = newest_proton_dir(common, "Proton")
        if n and (not best or _vkey(n) > _vkey(os.path.basename(os.path.dirname(best)))):
            best = os.path.join(common, n, "proton")
    return best


def tool_name(proton: str = None) -> str | None:
    """Compat tool name for CompatToolMapping (the folder name for custom tools)."""
    p = proton or proton_path()
    return os.path.basename(os.path.dirname(p)) if p else None


def default_pfx(proton: str = None) -> str | None:
    p = proton or proton_path()
    d = p and os.path.join(os.path.dirname(p), "files", "share", "default_pfx")
    return d if d and os.path.isdir(d) else None


# --- running things

def env_for(compat: str, proton: str = None, extra: dict = None, steam_root=None) -> dict:
    env = dict(os.environ)
    env["STEAM_COMPAT_DATA_PATH"] = compat
    # Proton finds steamclient through this; the Steam root, not Proton's folder
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = steam_root or steam.STEAM_ROOT
    env.setdefault("SteamAppId", os.path.basename(compat.rstrip("/")))
    env.update(extra or {})
    return env


def run(compat: str, args: list, proton: str = None, timeout: int = 600, verb: str = "run",
        cwd: str = None, env: dict = None, steam_root=None) -> subprocess.CompletedProcess:
    """
    Run a Windows program in a prefix and wait: proton run <exe> <args...>.
    Use for installers and one-off tools. verb "waitforexitandrun" also
    waits for every process left in the prefix (a setup.exe that spawns a child).
    """
    proton = proton or proton_path(steam_root)
    if not proton:
        raise RuntimeError("no Proton found")
    os.makedirs(compat, exist_ok=True)
    _log.info("proton %s %s", verb, " ".join(map(str, args)))
    return subprocess.run([proton, verb, *map(str, args)], env=env_for(compat, proton, env, steam_root),
                          cwd=cwd, capture_output=True, timeout=timeout)


def run_detached(compat: str, args: list, proton: str = None, env: dict = None, steam_root=None) -> subprocess.Popen:
    """Start a Windows program (a launcher the user logs into) without waiting. Detached on purpose."""
    proton = proton or proton_path(steam_root)
    return subprocess.Popen([proton, "run", *map(str, args)], env=env_for(compat, proton, env, steam_root),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def wineserver_wait(compat: str, proton: str = None, kill: bool = False):
    """Wait for (or kill) every process in a prefix, e.g. before copying files out of it."""
    proton = proton or proton_path()
    ws = os.path.join(os.path.dirname(proton), "files", "bin", "wineserver")
    if os.path.exists(ws):
        env = env_for(compat, proton); env["WINEPREFIX"] = os.path.join(compat, "pfx")
        subprocess.run([ws, "-k" if kill else "-w"], env=env, capture_output=True, timeout=120)


# --- prefixes

def is_initialised(compat: str) -> bool:
    return os.path.isdir(os.path.join(compat, "pfx", "drive_c"))


def init_prefix(compat: str, proton: str = None, steam_root=None) -> bool:
    """Create a real prefix with Proton itself (the slow path, 60-180 s)."""
    t = time.time()
    r = run(compat, ["cmd", "/c", "exit"], proton, timeout=600, steam_root=steam_root)
    _log.info("prefix %s initialised in %.0fs (rc %s)", compat, time.time() - t, r.returncode)
    return is_initialised(compat)


def _finish_clone(donor: str, dest: str, proton: str):
    with open(os.path.join(dest, "version"), "w") as f:
        f.write(tool_name(proton) + "\n")
    # Proton crashes in update_builtin_libs() (FileNotFoundError) without tracked_files
    tf = os.path.join(donor, "tracked_files")
    if os.path.isfile(tf):
        shutil.copy2(tf, os.path.join(dest, "tracked_files"))


def _ensure_shared(proton: str) -> bool:
    src = default_pfx(proton)
    if not src:
        return False
    win = os.path.join(src, "drive_c", "windows")
    marker = os.path.join(SHARED_DLLS, "source")
    try:
        if open(marker).read().strip() == tool_name(proton):
            return True
    except OSError:
        pass
    tmp = SHARED_DLLS + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for d in ("system32", "syswow64"):
        shutil.copytree(os.path.join(win, d), os.path.join(tmp, d), symlinks=True)
    with open(os.path.join(tmp, "source"), "w") as f:
        f.write(tool_name(proton) + "\n")
    # Prefixes already link to the old copy: swap in place, never leave a gap
    old = SHARED_DLLS + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(SHARED_DLLS):
        os.replace(SHARED_DLLS, old)
    os.replace(tmp, SHARED_DLLS)
    shutil.rmtree(old, ignore_errors=True)
    return True


def clone_prefix(donor: str, dest: str, proton: str = None, share_dlls: bool = True) -> bool:
    """Copy donor's pfx/ to dest (a new compatdata folder), DLL folders symlinked when possible."""
    proton = proton or proton_path()
    src = os.path.join(donor, "pfx")
    share = share_dlls and _ensure_shared(proton)

    def ignore(d, names):
        return [n for n in names if n in ("system32", "syswow64")] if share and os.path.basename(d) == "windows" else []

    try:
        os.makedirs(dest, exist_ok=True)
        shutil.copytree(src, os.path.join(dest, "pfx"), symlinks=True, ignore=ignore)
        if share:
            win = os.path.join(dest, "pfx", "drive_c", "windows")
            for d in ("system32", "syswow64"):
                os.symlink(os.path.join(SHARED_DLLS, d), os.path.join(win, d))
        _finish_clone(donor, dest, proton)
        return True
    except Exception as ex:
        _log.warning("prefix clone to %s failed: %s", dest, ex)
        shutil.rmtree(os.path.join(dest, "pfx"), ignore_errors=True)
        return False


def ensure_prefixes(compats: list, on_progress=None, steam_root=None) -> int:
    """
    Make sure every compatdata path in compats has an initialised prefix.
    Existing prefixes are left alone. Returns how many are ready.
    """
    prog = on_progress or (lambda *a: None)
    proton = proton_path(steam_root)
    if not proton:
        prog("  No Proton found, prefixes not created")
        return 0
    todo = [c for c in dict.fromkeys(compats) if c]
    ready = [c for c in todo if is_initialised(c)]
    missing = [c for c in todo if c not in ready]
    if not missing:
        return len(ready)
    donor = next((c for c in ready if not os.path.islink(os.path.join(c, "pfx", "drive_c", "windows", "system32"))), None)
    if not donor:
        donor = missing.pop(0)
        prog(f"  Creating prefix {os.path.basename(donor)} (first one takes a minute or two)...")
        if init_prefix(donor, proton, steam_root):
            ready.append(donor)
        else:
            prog("  Prefix creation failed")
            return len(ready)
    for c in missing:
        if clone_prefix(donor, c, proton) or init_prefix(c, proton, steam_root):
            ready.append(c)
            prog(f"  Prefix {os.path.basename(c)} ready")
    return len(ready)


def drive_c(compat: str) -> str:
    return os.path.join(compat, "pfx", "drive_c")


def user_dir(compat: str, *parts) -> str:
    """drive_c/users/steamuser/... (Proton always names the user steamuser)."""
    return os.path.join(drive_c(compat), "users", "steamuser", *parts)


def appdata_local(compat: str, *parts) -> str:
    return user_dir(compat, "AppData", "Local", *parts)


def appdata_roaming(compat: str, *parts) -> str:
    return user_dir(compat, "AppData", "Roaming", *parts)


def documents(compat: str, *parts) -> str:
    return user_dir(compat, "Documents", *parts)


# --- Windows paths

def z_path(linux_path: str) -> str:
    """Z:\\... form. Wine maps the whole Linux filesystem under Z:."""
    return "Z:" + os.path.normpath(linux_path).replace("/", "\\")


def wine_path_for_prefix(linux_path: str, compat: str) -> str:
    """
    The Windows path a program inside this prefix should see. Files on a
    removable drive's Steam library get that library's drive letter (D: on
    a Deck), which some launchers insist on: one refused to start a game
    passed as Z:\\run\\media\\... and worked with D:\\steamapps\\...
    Paths under home always stay Z:, because Proton and other launchers
    remap letters between runs (a letter that meant home at install meant
    the SD card at launch).
    """
    z = z_path(linux_path)
    path = os.path.realpath(linux_path)
    dos = os.path.join(compat, "pfx", "dosdevices")
    home = os.path.realpath(steam.HOME)
    if not os.path.isdir(dos) or path == home or path.startswith(home + "/"):
        return z
    drives = {n: os.path.realpath(os.path.join(dos, n)) for n in os.listdir(dos)
              if re.fullmatch(r"[a-y]:", n) and n != "c:"}
    hits = sorted(((len(t), n) for n, t in drives.items() if t != "/" and (path == t or path.startswith(t + "/"))),
                  key=lambda h: (-h[0], h[1]))
    if hits:
        letter = hits[0][1]
    else:
        parts = path.split("/")
        if "steamapps" not in parts:
            return z
        root = "/".join(parts[:parts.index("steamapps")]) or "/"
        free = [f"{c}:" for c in "defghijklmnopqrstuvwxy" if f"{c}:" not in drives]
        if root == "/" or not free:
            return z
        letter = free[0]
        try:
            os.symlink(root, os.path.join(dos, letter))
        except OSError:
            return z
        drives[letter] = root
    rel = os.path.relpath(path, drives[letter])
    return f"{letter.upper()}\\" + ("" if rel == "." else rel.replace("/", "\\"))
