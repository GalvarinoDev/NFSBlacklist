"""
identity.py - project names and paths, read from ../project.env

The engine imports this module by name. Everything that differs between
projects (or between a nightly and a stable repo of one project) comes
from project.env, which the shell scripts read too, so there is one source.
"""

import os
import shlex

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = " ".join(shlex.split(v)) if v.strip() else ""
    except OSError:
        pass
    return out


_E = _env(os.path.join(PROJECT_ROOT, "project.env"))

APP_ID = _E.get("APP_ID", "myproject")
APP_TITLE = _E.get("APP_TITLE", "My Project")
GITHUB_USER = _E.get("GITHUB_USER", "yourname")
GITHUB_REPO = _E.get("GITHUB_REPO", "MyProject")
GITHUB_BRANCH = _E.get("GITHUB_BRANCH", "main")
BUILD_BADGE = _E.get("BUILD_BADGE", "")
PROTECTED_PATHS = tuple(_E.get("PROTECTED", "").split())

INSTALL_DIR = PROJECT_ROOT
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
# Outside the install folder: survives updates; the uninstaller keeps save_backup/
DATA_DIR = os.path.expanduser(f"~/.local/share/{APP_ID}")
LEDGER_PATH = os.path.expanduser(f"~/.config/{APP_ID}/steam_edits.json")

try:
    VERSION = open(os.path.join(PROJECT_ROOT, "VERSION")).read().strip()[:7] or "dev"
except OSError:
    VERSION = "dev"

# Tag on every non-Steam shortcut this app makes (how it finds its own)
SHORTCUT_TAG = APP_TITLE

# Brand colours for engine.ui (see engine/ui/theme.py for every token)
# M3 GTR palette carried over from the pre-engine UI: navy, racing blue, silver
THEME = {
    "bg": "#0a0e17",
    "panel": "#141c2b",
    "panel_hi": "#1e2a3d",
    "accent": "#3b7dd8",
    "muted": "#7a8599",
    "border": "#2a3a52",
    "bad": "#7a1515",
    "font": "Orbitron",
}

# Extra config keys this project stores (engine.config merges them into its defaults)
CONFIG_DEFAULTS = {
    "choices": {},
}
