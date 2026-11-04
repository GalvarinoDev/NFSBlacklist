#!/bin/bash
# install.sh - first install. Runs curl-piped from launcher.sh, so it must
# not depend on any other file until the repo is extracted.
#
# Steps: check tools, download the repo zip (not git clone: no git needed),
# extract, Python venv with PyQt6 (PyQt5 if PyQt6 cannot open a window here),
# extra requirements, desktop entries, record the installed commit, start
# the app detached.

# Written by tools/new_project.py; must match project.env
GITHUB_USER="${GITHUB_USER:-GalvarinoDev}"
GITHUB_REPO="${GITHUB_REPO:-NFSBlacklist}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
INSTALL_DIR_NAME="${INSTALL_DIR_NAME:-NFSBlacklist}"
APP_TITLE="${APP_TITLE:-NFSBlacklist}"

INSTALL_DIR="$HOME/$INSTALL_DIR_NAME"
B='\033[1m'; C='\033[0;36m'; G='\033[0;32m'; Y='\033[0;33m'; R='\033[0;31m'; X='\033[0m'
info() { printf "${C}${B}[%s]${X} %s\n" "$APP_TITLE" "$1"; }
ok()   { printf "${G}${B}[  OK  ]${X} %s\n" "$1"; }
warn() { printf "${Y}${B}[ WARN ]${X} %s\n" "$1"; }
die()  { printf "${R}${B}[ERROR ]${X} %s\n" "$1"; echo; read -r -p "  Press Enter to close..."; exit 1; }

echo; echo -e "  ${B}$APP_TITLE${X} - installer"; echo

info "Checking tools..."
for t in python3 curl unzip; do command -v "$t" >/dev/null || die "$t is not installed."; done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10 or newer is needed."
python3 -c 'import venv, ensurepip' 2>/dev/null || warn "python venv/ensurepip missing; venv creation may fail."
ok "Tools found."

info "Downloading..."
TMPZIP="$(mktemp --suffix=.zip)"
curl -fL --progress-bar "https://github.com/$GITHUB_USER/$GITHUB_REPO/archive/refs/heads/$GITHUB_BRANCH.zip" -o "$TMPZIP" \
    || die "Download failed. Check your internet connection."

info "Installing to $INSTALL_DIR..."
TMPX="$(mktemp -d)"
unzip -qq "$TMPZIP" -d "$TMPX" || die "Could not extract the download."
rm -f "$TMPZIP"
SRC="$(find "$TMPX" -mindepth 1 -maxdepth 1 -type d | head -1)"
mkdir -p "$INSTALL_DIR"
# Over the top of an earlier install: the repo has no config.json or logs, so those stay
cp -r "$SRC"/. "$INSTALL_DIR"/
rm -rf "$TMPX"
ok "Files installed."

# shellcheck disable=SC1091
source "$INSTALL_DIR/common.sh" || die "common.sh missing from the download."

if [ -n "$MUSIC_URL" ] && [ ! -f "$INSTALL_DIR/assets/music/background.mp3" ]; then
    mkdir -p "$INSTALL_DIR/assets/music"
    curl -sSfL "$MUSIC_URL" -o "$INSTALL_DIR/assets/music/background.mp3" || warn "Background music not downloaded."
fi

info "Setting up Python..."
[ -d "$VENV_DIR" ] || python3 -m venv "$VENV_DIR" || die "Could not create the Python environment."
PIP="$VENV_DIR/bin/pip"
QT_OK=0
if "$VENV_PYTHON" -c "from PyQt6.QtWidgets import QApplication" &>/dev/null; then
    QT_OK=1
else
    info "Installing PyQt6 (about a minute)..."
    if "$PIP" install -q --disable-pip-version-check PyQt6; then
        # A wheel that installs but cannot load its platform plugin would crash the app
        if ("$VENV_PYTHON" -c "from PyQt6.QtWidgets import QApplication; QApplication([])") &>/dev/null; then
            QT_OK=1
        else
            "$PIP" uninstall -y -q PyQt6 PyQt6-Qt6 PyQt6-sip &>/dev/null
            touch "$VENV_DIR/.qt6_unsupported"
            warn "PyQt6 cannot open a window here; using PyQt5."
        fi
    else
        warn "PyQt6 install failed; using PyQt5."
    fi
fi
if [ "$QT_OK" = 0 ] && ! "$VENV_PYTHON" -c "from PyQt5.QtWidgets import QApplication" &>/dev/null; then
    "$PIP" install -q --disable-pip-version-check PyQt5 || die "Could not install PyQt6 or PyQt5."
fi
[ -f "$INSTALL_DIR/requirements.txt" ] && "$PIP" install -q --disable-pip-version-check -r "$INSTALL_DIR/requirements.txt" \
    || true
ok "Python ready."

info "Creating shortcuts..."
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<DEOF
[Desktop Entry]
Name=$APP_TITLE
Comment=$APP_COMMENT
Exec=bash "$INSTALL_DIR/launcher.sh"
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Game;Utility;
StartupNotify=true
DEOF
chmod +x "$DESKTOP_FILE"
if [ -d "$HOME/Desktop" ]; then cp "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"; chmod +x "$DESKTOP_SHORTCUT"; fi
chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null
ok "Shortcuts created."

# So the first launch does not offer an "update" to the same version
SHA=$(curl -sf --max-time 10 "https://api.github.com/repos/$GITHUB_USER/$GITHUB_REPO/commits/$GITHUB_BRANCH" | grep -m1 '"sha"' | cut -d'"' -f4)
echo "${SHA:-0}" > "$INSTALL_DIR/VERSION"

echo; echo -e "  ${G}${B}Installed. Starting $APP_TITLE...${X}"; echo
# Detached: closing this terminal must not close the app
setsid nohup "$VENV_PYTHON" "$ENTRY_POINT" >/dev/null 2>&1 &
disown
exit 0
