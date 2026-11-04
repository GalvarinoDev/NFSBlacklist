"""
main.py - entry point: logging, Qt check, UI
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.log import get_logger, setup_logging

setup_logging()
_log = get_logger("main")


def _ensure_qt6():
    # Updates only copy files, so a venv made with PyQt5 never gains PyQt6 by
    # itself. Try once per launch until it works; a wheel that installs but
    # cannot open a window here is removed and remembered, PyQt5 keeps running.
    try:
        import PyQt6.QtWidgets  # noqa: F401
        return
    except ImportError:
        pass
    import subprocess
    venv = os.path.dirname(os.path.dirname(sys.executable))
    pip, marker = os.path.join(venv, "bin", "pip"), os.path.join(venv, ".qt6_unsupported")
    if not os.path.exists(pip) or os.path.exists(marker):
        return
    try:
        if subprocess.run([pip, "install", "-q", "--disable-pip-version-check", "PyQt6"], capture_output=True, timeout=900).returncode:
            return
        if subprocess.run([sys.executable, "-c", "from PyQt6.QtWidgets import QApplication; QApplication([])"],
                          capture_output=True, timeout=60).returncode:
            subprocess.run([pip, "uninstall", "-y", "-q", "PyQt6", "PyQt6-Qt6", "PyQt6-sip"], capture_output=True)
            open(marker, "w").close()
            return
        import importlib; importlib.invalidate_caches()
    except Exception as ex:
        _log.warning("PyQt6 install skipped: %s", ex)


if __name__ == "__main__":
    _ensure_qt6()
    from engine.ui import app
    app.run()
