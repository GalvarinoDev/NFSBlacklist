"""
prelaunch.py - work done right before a game starts, then the game

Steam runs:  bash <install>/prelaunch.sh <key> <original command...>
prelaunch.sh runs this module (with a time limit, Steam's LD_PRELOAD and
runtime library paths removed for the host Python only), then execs the
original command, so the game always starts.

Handlers come from the project: games.PRELAUNCH = {key: fn(key, cmd)}.
Typical uses: update a mod client from its manifest (one quick try, a few
seconds when offline), refresh files another tool may have replaced, pick
which exe to run when Steam dropped a launch menu.

Rules for handlers: never open a window, never ask anything, never block
for long, log instead of raising. Output goes to the log only.
"""

import sys
import time

from .log import get_logger, setup_logging

_log = get_logger("prelaunch")


def main(argv: list) -> int:
    setup_logging()
    if not argv:
        return 0
    try:
        import games
        handlers = getattr(games, "PRELAUNCH", {})
    except Exception as ex:
        _log.warning("prelaunch: games.py failed to load: %s", ex)
        return 0
    fn = handlers.get(argv[0])
    if not fn:
        return 0
    t0 = time.monotonic()
    try:
        fn(argv[0], argv[1:])
    except Exception as ex:
        _log.warning("prelaunch %s skipped: %s", argv[0], ex)
    _log.info("prelaunch %s: %.1fs", argv[0], time.monotonic() - t0)
    return 0


def exe_in(cmd: list, name: str) -> str | None:
    """The argument of the launch command that ends with name (case-insensitive), e.g. the game exe."""
    low = name.lower()
    return next((a for a in cmd if a.lower().endswith(low)), None)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
