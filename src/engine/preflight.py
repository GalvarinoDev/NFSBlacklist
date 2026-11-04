"""
preflight.py - checks to run before a long install, while backing out is free

Run before Steam is closed. Only sizes the project actually knows are
checked: guessing a number and refusing to install because of it is
worse than not checking.
"""

import os
from collections import namedtuple

from .net import online

Check = namedtuple("Check", "level title detail")
OK, WARN, BLOCK = "ok", "warn", "block"


def free_gb(path: str) -> float:
    try:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize / (1 << 30)
    except OSError:
        return 0.0


def _probe(path: str):
    """(filesystem id, nearest existing path) so a not-yet-created folder still checks its drive."""
    p = os.path.abspath(path)
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    try:
        return os.stat(p).st_dev, p
    except OSError:
        return None, p


def on_ac() -> bool:
    """True when any mains or USB supply is online. No readable supply counts as plugged in."""
    base, seen = "/sys/class/power_supply", False
    try:
        names = os.listdir(base)
    except OSError:
        return True
    for n in names:
        try:
            with open(os.path.join(base, n, "type")) as f:
                if f.read().strip() not in ("Mains", "USB"):
                    continue
            with open(os.path.join(base, n, "online")) as f:
                seen = True
                if f.read().strip() == "1":
                    return True
        except OSError:
            continue
    return not seen


def check(space: list = (), notes: list = (), need_network: bool = True) -> list:
    """
    space -- [(path, gb)] needed; entries on the same drive are added up
    notes -- extra Check(WARN, ...) items the project wants shown (e.g. "this takes hours")
    Returns a list of Check; empty means nothing to say.
    """
    per_dev = {}
    for path, gb in space:
        if not path or not gb:
            continue
        dev, probe = _probe(path)
        e = per_dev.setdefault(dev, [0.0, probe])
        e[0] += gb
    out = []
    for want, path in sorted(per_dev.values(), key=lambda e: e[1]):
        have = free_gb(path)
        detail = f"{path}: {have:.1f} GB free, {want:.0f} GB needed"
        out.append(Check(BLOCK if have < want else OK, "Not enough disk space" if have < want else "Disk space", detail))
    out += list(notes)
    if not on_ac():
        out.append(Check(WARN, "On battery", "Plug the device in. Installs can take a long time."))
    if need_network and not online():
        out.append(Check(WARN, "No internet connection", "Downloads will fail. Connect to Wi-Fi first."))
    return out


def worst(checks) -> str:
    for level in (BLOCK, WARN):
        if any(c.level == level for c in checks):
            return level
    return OK
