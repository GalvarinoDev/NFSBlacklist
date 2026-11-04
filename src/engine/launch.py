"""
launch.py - build Steam launch options

Launch options are the least invasive way to change how a Steam game
starts: nothing in the game folder is replaced, Steam's file verification
and game updates cannot undo it, and clearing the option restores stock.

Prefer, in order:
  1. launch menu entry (engine.appinfo): plain Play stays the original game
  2. launch option that swaps the exe (swap_exe): mod exe next to the stock one
  3. replacing a file in the game folder: last resort; Steam Verify undoes
     it and some mod exes need the original exe intact (they map it into
     memory through PE imports, so it must stay a real exe, not a script)

%command% is the full command Steam would run (Proton, runtime and exe).
Steam only substitutes it when the app has a compatibility tool set.
"""

import shlex

import identity


def swap_exe(original: str, replacement: str, args: str = "") -> str:
    """
    Run replacement instead of original when Steam starts original:
        bash -c 'exec "${@/game.exe/mod.exe}" -flag' -- %command%
    Safe on an appid shared by several exes (SP and MP in one app): the
    substitution only matches when Steam launches `original`.
    """
    extra = f" {args}" if args else ""
    return f"bash -c 'exec \"${{@/{original}/{replacement}}}\"{extra}' -- %command%"


def env(vars: dict, command: str = "%command%") -> str:
    """VAR=value ... %command%. Values are shell-quoted."""
    return " ".join(f"{k}={shlex.quote(str(v))}" for k, v in vars.items()) + f" {command}"


def dll_overrides(dlls: dict, command: str = "%command%") -> str:
    """WINEDLLOVERRIDES="dinput8=n,b;d3d9=n,b" %command%"""
    val = ";".join(f"{k}={v}" for k, v in dlls.items())
    return f'WINEDLLOVERRIDES="{val}" {command}'


def gamescope(args: str = "-f", command: str = "%command%") -> str:
    """
    Nested gamescope for Desktop Mode / non-Deck PCs (resolution, FSR,
    frame limit). Game Mode already runs inside gamescope: do not nest there.
    """
    return f"gamescope {args} -- {command}"


def prelaunch(key: str, command: str = "%command%") -> str:
    """
    Run the app's pre-launch hook (silent mod update, menu fallback) and then
    the game: bash "<install>/prelaunch.sh" <key> %command%. The game always
    starts, even when the hook fails or there is no network.
    """
    return f'bash "{identity.PROJECT_ROOT}/prelaunch.sh" {key} {command}'


def chain(*parts: str) -> str:
    """
    Combine wrappers left to right, each wrapping what follows:
        chain(env({"DXVK_ASYNC": 1}), prelaunch("game"), swap_exe("a.exe", "b.exe"))
    Every part ends in %command%; all but the last lose it.
    """
    out = [p.replace("%command%", "").strip() for p in parts[:-1]]
    return " ".join([*out, parts[-1]]).strip()


def args(*a: str) -> str:
    """Plain arguments after %command% (e.g. "-windowed", "+set r_mode 6")."""
    return "%command% " + " ".join(a)
