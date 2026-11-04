#!/bin/bash
# launcher.sh - entry point (desktop entry, the downloadable .desktop bootstrap)
#
# Not installed yet: download and run install.sh. Installed: offer
# Launch / Uninstall, check for an update first, start the app detached.
# The update logic mirrors src/engine/selfupdate.py; keep the two in sync.

# Written by tools/new_project.py; must match project.env
GITHUB_USER="${GITHUB_USER:-GalvarinoDev}"
GITHUB_REPO="${GITHUB_REPO:-NFSBlacklist}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
INSTALL_DIR_NAME="${INSTALL_DIR_NAME:-NFSBlacklist}"

INSTALLED="$HOME/$INSTALL_DIR_NAME"
LOCK="$HOME/.${INSTALL_DIR_NAME}_installing"
SELF="$(readlink -f "$0")"

# The .desktop bootstrap runs a downloaded copy from /tmp; hand over to the installed one
if [ -f "$INSTALLED/launcher.sh" ] && [ ! -f "$LOCK" ] && [ "$SELF" != "$(readlink -f "$INSTALLED/launcher.sh")" ]; then
    exec bash "$INSTALLED/launcher.sh" "$@"
fi
if [ ! -f "$INSTALLED/project.env" ] || [ -f "$LOCK" ]; then
    touch "$LOCK"
    curl -sfL "https://raw.githubusercontent.com/$GITHUB_USER/$GITHUB_REPO/$GITHUB_BRANCH/install.sh" \
        | GITHUB_USER="$GITHUB_USER" GITHUB_REPO="$GITHUB_REPO" GITHUB_BRANCH="$GITHUB_BRANCH" INSTALL_DIR_NAME="$INSTALL_DIR_NAME" bash
    rm -f "$LOCK"
    exit 0
fi

# shellcheck disable=SC1091
source "$INSTALLED/common.sh"
VERSION_FILE="$INSTALL_DIR/VERSION"
STAGE="$INSTALL_DIR/.update"

check_for_updates() {
    local LOCAL REMOTE FILES COUNT HINT=""
    LOCAL="$(tr -d '[:space:]' < "$VERSION_FILE" 2>/dev/null)"; LOCAL="${LOCAL:-0}"
    REMOTE=$(curl -sf --max-time 10 "https://api.github.com/repos/$GITHUB_USER/$GITHUB_REPO/commits/$GITHUB_BRANCH" | grep -m1 '"sha"' | cut -d'"' -f4)
    [ -z "$REMOTE" ] || [ "$LOCAL" = "$REMOTE" ] && return 0

    if [ "$LOCAL" != "0" ]; then
        # filename and previous_filename both match: renames delete the old path
        FILES=$(curl -sf --max-time 15 "https://api.github.com/repos/$GITHUB_USER/$GITHUB_REPO/compare/${LOCAL}...${REMOTE}" \
            | grep -E '"(previous_)?filename"' | cut -d'"' -f4)
        [ -z "$FILES" ] && return 0
        COUNT=$(echo "$FILES" | wc -l)
        if echo "$FILES" | grep -qx 'src/config.py' || [ "$(echo "$FILES" | grep -c '^src/')" -gt 3 ]; then
            HINT="\n\nThis update changed a lot. If anything acts up, use Settings > Reset Config."
        fi
    else
        COUNT="all"
    fi

    zenity --question --title="$APP_TITLE" --text="An update is available ($COUNT files).\n\nUpdate now?" \
        --ok-label="Update" --cancel-label="Skip" --width=320 2>/dev/null || return 0

    rm -rf "$STAGE"; mkdir -p "$STAGE"
    local REMOVED="" FAILED=0
    if [ "$LOCAL" = "0" ]; then
        local Z X; Z="$(mktemp --suffix=.zip)"; X="$(mktemp -d)"
        if ! curl -sfL --max-time 300 "https://github.com/$GITHUB_USER/$GITHUB_REPO/archive/$REMOTE.zip" -o "$Z"; then
            rm -rf "$Z" "$X" "$STAGE"; zenity --error --text="Update download failed." 2>/dev/null; return 0
        fi
        unzip -qq "$Z" -d "$X"; rm -f "$Z"
        cp -r "$(find "$X" -mindepth 1 -maxdepth 1 -type d | head -1)"/. "$STAGE"/; rm -rf "$X"
        FILES=$(cd "$STAGE" && find . -type f | sed 's|^\./||')
    else
        while IFS= read -r f; do
            [ -z "$f" ] && continue
            is_protected "$f" && continue
            mkdir -p "$STAGE/$(dirname "$f")"
            code=$(curl -s --max-time 30 -w '%{http_code}' "https://raw.githubusercontent.com/$GITHUB_USER/$GITHUB_REPO/$REMOTE/$f" -o "$STAGE/$f")
            if [ "$code" = "404" ]; then
                # Deleted or renamed upstream: remove the local copy at apply time
                rm -f "$STAGE/$f"; REMOVED="$REMOVED$f"$'\n'
            elif [ "$code" != "200" ]; then
                FAILED=1; break
            fi
        done <<< "$FILES"
    fi
    if [ "$FAILED" -ne 0 ]; then
        rm -rf "$STAGE"; zenity --error --text="Update download failed. Continuing with this version." 2>/dev/null; return 0
    fi
    # Refuse an update whose Python does not compile
    if [ -d "$STAGE/src" ] && ! "$VENV_PYTHON" -m compileall -q "$STAGE/src" >/dev/null 2>&1; then
        rm -rf "$STAGE"; zenity --error --text="The update looks broken and was not applied." 2>/dev/null; return 0
    fi
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        is_protected "$f" && continue
        if [ -f "$STAGE/$f" ]; then mkdir -p "$INSTALL_DIR/$(dirname "$f")"; cp "$STAGE/$f" "$INSTALL_DIR/$f"; fi
    done <<< "$FILES"
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        is_protected "$f" || rm -f "$INSTALL_DIR/$f"
    done <<< "$REMOVED"
    rm -rf "$STAGE"
    echo "$REMOTE" > "$VERSION_FILE"
    chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null
    zenity --info --title="$APP_TITLE" --text="Update complete.$HINT" --width=320 2>/dev/null
}

choice=$(zenity --list --title="$APP_TITLE" --text="What would you like to do?" --column="Action" --hide-header \
    "Launch $APP_TITLE" "Uninstall" --width=320 --height=220 2>/dev/null) || exit 0

case "$choice" in
    "Launch $APP_TITLE")
        check_for_updates
        if [ -x "$VENV_PYTHON" ] && [ -f "$ENTRY_POINT" ]; then
            # Detached so closing the terminal or launcher never closes the app
            setsid nohup "$VENV_PYTHON" "$ENTRY_POINT" >/dev/null 2>&1 &
            disown
        else
            zenity --error --text="$APP_TITLE looks incomplete. Reinstall it." 2>/dev/null
        fi
        ;;
    "Uninstall")
        bash "$INSTALL_DIR/uninstall.sh"
        ;;
esac
exit 0
