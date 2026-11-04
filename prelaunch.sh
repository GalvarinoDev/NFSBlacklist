#!/bin/bash
# Steam launch option wrapper:  bash "<install>/prelaunch.sh" <game key> %command%
# Runs the project's pre-launch handler (games.PRELAUNCH) silently, then
# starts the game exactly as Steam would have. The game always starts,
# even if the handler fails, times out or there is no network.

DIR="$(dirname "$(readlink -f "$0")")"
KEY="$1"; shift

# Steam's launch environment (overlay preload, runtime libraries) is meant
# for the game, not the host Python; drop it for the handler only.
if [ -x "$DIR/.venv/bin/python3" ]; then
    (cd "$DIR/src" && timeout "${PRELAUNCH_TIMEOUT:-120}" env -u LD_PRELOAD -u LD_LIBRARY_PATH -u PYTHONHOME -u PYTHONPATH \
        "$DIR/.venv/bin/python3" -m engine.prelaunch "$KEY" "$@") >/dev/null 2>&1
fi

# Launch menu fallback: MENU_SWAP="<stock exe>=<mod file> ..." in the launch
# option. While our appinfo menu is present the stock entry carries the
# vanilla tag; Steam drops tag and menu together on a refresh, so an
# untagged stock exe means "menu lost" and is swapped for the mod file,
# the same command the menu entry would have run. MENU_ARGS is appended.
if [ -n "$MENU_SWAP" ]; then
    # shellcheck disable=SC1091
    source "$DIR/project.env" 2>/dev/null
    TAG="${MENU_TAG:--${APP_ID}_vanilla}"   # engine.appinfo.VANILLA_TAG
    args=(); tagged=
    for a in "$@"; do
        if [ "$a" = "$TAG" ]; then tagged=1; else args+=("$a"); fi
    done
    [ -n "$tagged" ] && exec "${args[@]}"
    for p in $MENU_SWAP; do
        for i in "${!args[@]}"; do
            a=${args[$i]}
            if [ "${a##*/}" = "${p%%=*}" ] && [ -f "${a%/*}/${p#*=}" ]; then
                args[$i]="${a%/*}/${p#*=}"
                # shellcheck disable=SC2086
                exec "${args[@]}" $MENU_ARGS
            fi
        done
    done
fi
exec "$@"
