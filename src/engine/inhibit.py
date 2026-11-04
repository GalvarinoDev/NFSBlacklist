"""
inhibit.py - keep the device awake during long installs

A handheld that suspends mid-install leaves a half-written prefix or game
folder. Two locks because they cover different things: logind blocks
suspend and idle actions (what matters in Game Mode), and
org.freedesktop.ScreenSaver blocks the KDE locker in Desktop Mode.
Both are best effort; nothing here is ever fatal.
"""

import atexit
import subprocess

import identity
from .log import get_logger

_log = get_logger(__name__)

# Bounded so a leaked child can't hold the machine awake forever
MAX_HOLD = "6h"

_proc = None
_cookie = None


def _ss_iface():
    from .qt import QDBusConnection, QDBusInterface
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    iface = QDBusInterface("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
                           "org.freedesktop.ScreenSaver", bus)
    return iface if iface.isValid() else None


def start(why: str = None) -> bool:
    global _proc, _cookie
    why = why or f"{identity.APP_TITLE} is installing"
    if _proc is None:
        try:
            # Deliberately not detached (unlike every other child process):
            # the lock must die with the app, never outlive it
            _proc = subprocess.Popen(
                ["systemd-inhibit", "--what=idle:sleep:handle-lid-switch", f"--who={identity.APP_TITLE}",
                 f"--why={why}", "--mode=block", "sleep", MAX_HOLD],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _log.info("sleep inhibited (%s)", why)
        except Exception as ex:
            _log.debug("systemd-inhibit unavailable: %s", ex)
    if _cookie is None:
        try:
            iface = _ss_iface()
            args = iface.call("Inhibit", identity.APP_TITLE, why).arguments() if iface else []
            _cookie = args[0] if args else None
        except Exception as ex:
            _log.debug("screensaver inhibit unavailable: %s", ex)
    return bool(_proc or _cookie)


def stop():
    global _proc, _cookie
    if _proc is not None:
        try:
            _proc.terminate(); _proc.wait(timeout=5)
        except Exception:
            try: _proc.kill()
            except Exception: pass
        _proc = None
        _log.info("sleep inhibit released")
    if _cookie is not None:
        try:
            iface = _ss_iface()
            if iface:
                iface.call("UnInhibit", _cookie)
        except Exception:
            pass
        _cookie = None


atexit.register(stop)
