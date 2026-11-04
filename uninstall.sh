#!/bin/bash
# uninstall.sh - remove the app and undo what it changed
#
# 1. confirm, offer a save backup
# 2. close Steam gracefully (120 s, never SIGKILL)
# 3. python -m engine.uninstall: mods, launch menus, shortcuts, launch
#    options, compat tools, controller entries (the same code that made them)
# 4. remove the app's own folders LAST, so a failed run can be repeated
# Steam game prefixes, save folders and the save backup are never deleted.

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/common.sh"

zenity --question --title="$APP_TITLE" --width=380 \
    --text="Uninstall $APP_TITLE?\n\nMods it installed, its shortcuts and its Steam settings are removed. Your games and saves stay." \
    --ok-label="Uninstall" --cancel-label="Cancel" 2>/dev/null || exit 0

ARGS=()
if zenity --question --title="$APP_TITLE" --text="Back up your saves first?" --width=320 2>/dev/null; then
    ARGS+=(--backup-saves)
fi

info "Closing Steam..."
if ! close_steam; then
    zenity --error --text="Steam did not close within 120 seconds.\nClose Steam and run the uninstaller again." 2>/dev/null
    exit 1
fi

if [ -x "$VENV_PYTHON" ] && [ -d "$INSTALL_DIR/src/engine" ]; then
    info "Undoing changes..."
    (cd "$INSTALL_DIR/src" && "$VENV_PYTHON" -m engine.uninstall "${ARGS[@]}") || {
        zenity --error --text="Some changes could not be undone. See $INSTALL_DIR/logs/install.log.\nNothing was deleted; you can run the uninstaller again." 2>/dev/null
        exit 1
    }
else
    warn "App files are incomplete; only removing folders."
fi

# Project-specific shell cleanup (optional): uninstall_extra.sh next to this script
[ -f "$DIR/uninstall_extra.sh" ] && bash "$DIR/uninstall_extra.sh"

info "Removing $APP_TITLE..."
rm -f "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1
# Keep the save backup; everything else in the data folder goes
if [ -d "$DATA_DIR" ]; then
    find "$DATA_DIR" -mindepth 1 -maxdepth 1 ! -name save_backup -exec rm -rf {} +
    rmdir "$DATA_DIR" 2>/dev/null
fi
rm -rf "$CONF_DIR"
rm -rf "$INSTALL_DIR"
success "$APP_TITLE removed."
zenity --info --title="$APP_TITLE" --text="$APP_TITLE was removed." --width=300 2>/dev/null
exit 0
