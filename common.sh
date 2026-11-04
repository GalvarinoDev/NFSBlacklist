#!/bin/bash
# common.sh - sourced by launcher.sh, uninstall.sh and prelaunch helpers
# from the install folder. install.sh is self-contained (it runs curl-piped
# before anything is on disk) and only sources this after extracting.

_here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
[ -f "$_here/project.env" ] || { echo "project.env missing in $_here"; exit 1; }
# shellcheck disable=SC1091
source "$_here/project.env"

GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
GITHUB_RAW="https://raw.githubusercontent.com/$GITHUB_USER/$GITHUB_REPO/$GITHUB_BRANCH"
INSTALL_DIR="$HOME/$INSTALL_DIR_NAME"
VENV_DIR="$INSTALL_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python3"
ENTRY_POINT="$INSTALL_DIR/src/main.py"
ICON_PATH="$INSTALL_DIR/assets/images/icon.png"
DATA_DIR="$HOME/.local/share/$APP_ID"
CONF_DIR="$HOME/.config/$APP_ID"
DESKTOP_FILE="$HOME/.local/share/applications/$APP_ID.desktop"
DESKTOP_SHORTCUT="$HOME/Desktop/$INSTALL_DIR_NAME.desktop"

RED='\033[0;31m'; YELLOW='\033[0;33m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; CLEAR='\033[0m'
info()    { printf "${CYAN}${BOLD}[%s]${CLEAR} %s\n" "$APP_TITLE" "$1"; }
success() { printf "${GREEN}${BOLD}[  OK  ]${CLEAR} %s\n" "$1"; }
warn()    { printf "${YELLOW}${BOLD}[ WARN ]${CLEAR} %s\n" "$1"; }
die()     { printf "${RED}${BOLD}[ERROR ]${CLEAR} %s\n" "$1"; echo; read -r -p "  Press Enter to close..."; exit 1; }

is_protected() {
    local p
    for p in $PROTECTED; do
        case "$1" in "$p"|"$p"*) return 0 ;; esac
    done
    return 1
}

# Graceful Steam shutdown. Never SIGKILL: a killed Steam can leave its VDFs
# half written or trigger the SteamOS first-run wizard.
close_steam() {
    if ! pgrep -f "ubuntu12_32/steam" >/dev/null 2>&1; then
        return 0
    fi
    steam -shutdown >/dev/null 2>&1 || pkill -TERM -f "ubuntu12_32/steam"
    local deadline=$((SECONDS + 120))
    while pgrep -f "ubuntu12_32/steam" >/dev/null 2>&1; do
        [ $SECONDS -ge $deadline ] && return 1
        sleep 1
    done
    sleep 3; sync
    return 0
}
