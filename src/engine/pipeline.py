"""
pipeline.py - run an install as ordered steps, UI-agnostic

An install is a list of Step objects. The runner:
  - holds the sleep inhibit for the whole run
  - runs steps marked steam=OPEN first, then closes Steam once (gracefully,
    with the 120 s wait) before the first step marked steam=CLOSED
  - turns a net.DownloadError into a question for the UI: Retry, Manual
    (the user picks the file they downloaded; net.MANUAL makes the retry use
    it), or Skip
  - turns any other exception into Skip / Abort, logged with traceback
  - reports progress per step, weighted, so the bar never jumps backwards

Order that works (and why):
  OPEN   GE-Proton, prefixes, downloads, depot downgrade (needs Steam running
         for the console path), anything the user must click through
  CLOSED launch options, compat tools, shortcuts, controller configsets,
         appinfo launch menus. Steam rewrites these files on exit, so they
         are only safe with Steam closed.
Files-only work (mod updates) can run with Steam open: mark it OPEN.
"""

import traceback
from dataclasses import dataclass, field

from . import appinfo, inhibit, steam  # appinfo: re-adds launch menus whenever Steam closes
from .log import get_logger
from .net import MANUAL, DownloadError

_log = get_logger(__name__)

OPEN, CLOSED = "open", "closed"
RETRY, MANUAL_FILE, SKIP, ABORT = "retry", "manual", "skip", "abort"


@dataclass
class Step:
    name: str              # unique within a run: results are keyed by it
    fn: callable           # fn(ctx) ; raise to fail
    steam: str = OPEN      # OPEN: may run with Steam running; CLOSED: needs Steam closed
    weight: int = 1        # share of the progress bar
    required: bool = False # failure aborts the run instead of offering Skip
    key: str = None        # game key this step belongs to (None = shared step)


@dataclass
class Context:
    games: dict                          # key -> detected game dict (engine.detect)
    steam_root: str = None
    data: dict = field(default_factory=dict)  # steps share results here
    progress: callable = None            # UI: progress(percent, message) for the current step
    log: callable = None                 # UI: log(line)
    _step: callable = None

    def step(self, percent: int, msg: str = ""):
        """Steps report progress here (0-100 of the step); also fits on_progress callbacks."""
        if self._step:
            self._step(percent, msg)

    def say(self, msg: str):
        _log.info(msg)
        if self.log:
            self.log(msg)


class Aborted(Exception):
    pass


def games_ok(steps: list, results: dict) -> list:
    """Game keys whose own steps all succeeded and which had at least one step."""
    keys = {s.key for s in steps if s.key}
    return [k for k in keys if all(results.get(s.name) == "ok" for s in steps if s.key == k)]


def run(steps: list, ctx: Context, ask_download=None, ask_error=None, on_overall=None) -> dict:
    """
    Run steps in order (OPEN steps keep their place; Steam closes before the
    first CLOSED step). Returns {step name: "ok" | "skipped" | "failed"}.

    ask_download(err)    -> (RETRY|SKIP|ABORT, None) or (MANUAL_FILE, path)
    ask_error(step, exc) -> SKIP | ABORT
    on_overall(percent, step name)
    Defaults (no UI): retry once, then skip.
    """
    total = sum(s.weight for s in steps) or 1
    done_w, results, closed = 0, {}, False
    inhibit.start()
    try:
        for s in steps:
            if s.steam == CLOSED and not closed:
                ctx.say("Closing Steam...")
                try:
                    steam.kill_steam(ctx.say)
                except TimeoutError as ex:
                    ctx.say(f"✗ {ex}")
                    raise Aborted("Steam did not close") from ex
                closed = True
            base = done_w

            def prog(pc, msg="", _b=base, _w=s.weight):
                if on_overall:
                    on_overall(int((_b + _w * max(0, min(pc, 100)) / 100) * 100 / total), s.name)
                if ctx.progress:
                    ctx.progress(pc, msg)

            ctx._step = prog
            ctx.say(f"--- {s.name}")
            tries = 0
            while True:
                try:
                    s.fn(ctx)
                    results[s.name] = "ok"
                    break
                except DownloadError as err:
                    tries += 1
                    _log.error("%s: %s", s.name, err)
                    choice, path = (ask_download(err) if ask_download else ((RETRY, None) if tries < 2 else (SKIP, None)))
                    if choice == MANUAL_FILE and path:
                        MANUAL[err.url] = path
                        continue
                    if choice == RETRY:
                        continue
                    if choice == ABORT or s.required:
                        raise Aborted(s.name)
                    results[s.name] = "skipped"
                    ctx.say(f"✗ {s.name} skipped")
                    break
                except Aborted:
                    raise
                except Exception as ex:
                    _log.error("%s failed: %s\n%s", s.name, ex, traceback.format_exc())
                    ctx.say(f"✗ {s.name}: {ex}")
                    if s.required or (ask_error and ask_error(s, ex) == ABORT):
                        raise Aborted(s.name)
                    results[s.name] = "failed"
                    break
            done_w += s.weight
            prog(100)
    finally:
        inhibit.stop()
    return results
