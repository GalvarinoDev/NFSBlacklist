"""
games.py - the four Black Box NFS games and how they are set up

None were sold on Steam: the user provides the files, we find them, mod
them, write their registry and add a non-Steam shortcut. NFSU and NFSMW
both run speed.exe, so the sentinels (track files) tell them apart.
"""

import os

from engine import detect, proton
from engine.pipeline import CLOSED, OPEN, Step
from installers import nfs

# Users also keep these games in ~/NFS or NFS/ on a card (scanned before the engine existed)
detect.OWN_SCAN += [os.path.expanduser("~/NFS"), "/run/media/*/*/NFS", "/run/media/*/NFS"]

# Separators include _ and -: folders look like "NFS_Carbon_v1.4"
_B, _E = r"(?<![a-z0-9])", r"(?![a-z0-9])"
_GRID = "https://cdn2.steamgriddb.com"


def _art(icon, grid, wide, hero, logo):
    return {"icon": f"{_GRID}/icon/{icon}", "grid": f"{_GRID}/grid/{grid}", "wide": f"{_GRID}/grid/{wide}",
            "hero": f"{_GRID}/hero/{hero}", "logo": f"{_GRID}/logo/{logo}"}


GAMES = {
    "nfsu": {
        "name": "Need for Speed: Underground", "appid": None, "exe": "speed.exe",
        "sentinels": ["Tracks/STREAML1RA.BUN"],
        "own_folders": ["need for speed underground", "need for speed - underground", "nfs underground", "nfsu"],
        "own_keywords": [_B + r"(underground(?![\s_-]*2)|nfsu|ug1)" + _E],  # never an Underground 2 folder
        "profile": "gamepad",
        "art": _art("e939d0b700e0a09fe2b8c2c9e31ef0e3.ico", "0959494b92b81147796ce901ea4f9927.png",
                    "4ea29595c25ccf7a33d3fdec75630d5a.png", "ccc81a97c1535f9a631b9db584a264e4.png",
                    "750263dbb2fb8547bdd810ee11a08c7a.png"),
    },
    "nfsu2": {
        "name": "Need for Speed: Underground 2", "appid": None, "exe": "SPEED2.exe",
        "sentinels": ["SPEED2.exe"],
        "own_folders": ["need for speed underground 2", "need for speed - underground 2", "nfs underground 2", "nfsu2"],
        "own_keywords": [_B + r"(underground[\s_-]*2|nfsu2|ug2)" + _E],
        "profile": "gamepad",
        "art": _art("2131f8ecf18db66a758f718dc729e00e.ico", "8763b03d427d69f413df44433092276c.png",
                    "c0c783b5fc0d7d808f1d14a6e9c8280d.png", "8c2d7d2728733cad5681b6b79ae799e4.png",
                    "7a614fd06c325499f1680b9896beedeb.png"),
    },
    "nfsmw": {
        "name": "Need for Speed: Most Wanted", "appid": None, "exe": "speed.exe",
        "sentinels": ["TRACKS/L2RA.BUN"],
        "own_folders": ["need for speed most wanted", "need for speed most wanted black edition", "nfs most wanted",
                        "nfs most wanted black edition", "nfsmw", "most wanted", "most wanted black edition"],
        "own_keywords": [_B + r"(most[\s_-]*wanted|nfsmw|mw)" + _E],
        "profile": "gamepad",
        "art": _art("604cd803586d40e36a15c53a230c93ec.ico", "a86cc0b404ab003e0badb9ed96b55ace.png",
                    "6fdb8f7d90e975d5d19959a0fcebf123.png", "822b440edda4c46a5e1dad463eaf8ebd.png",
                    "eb9fc349601c69352c859c1faa287874.png"),
    },
    "nfsc": {
        "name": "Need for Speed: Carbon", "appid": None, "exe": "NFSC.exe",
        "sentinels": ["NFSC.exe"],
        "own_folders": ["need for speed carbon", "need for speed - carbon", "nfs carbon", "nfsc"],
        "own_keywords": [_B + r"(carbon|nfsc)" + _E],
        "profile": "gamepad",
        "art": _art("59dfd4106ab71d11b48a4246ba153331.ico", "8eb8c14637ad7f04b17390e3c4b16ec9.png",
                    "ee955e252af3c85e66e15864e31174fe.png", "4dff7cccfc092f41b8170fc6d7dc93c0.jpg",
                    "fdf1bc5669e8ff5ba45d02fded729feb.png"),
    },
}


def build_steps(selected: dict, choices: dict) -> list:
    steps = [Step("GE-Proton", lambda ctx: ctx.data.update(proton_tool=proton.install_ge_proton(ctx.step)), OPEN, 3, required=True)]
    games = []
    for key, g in selected.items():
        g = dict(g, key=key)
        g["compatdata"] = nfs.compatdata(g)
        games.append(g)
        n = g["name"]
        steps += [
            Step(f"{n}: prefix", lambda ctx, g=g: proton.ensure_prefixes([g["compatdata"]], ctx.say, ctx.steam_root), OPEN, 2, key=key),
            Step(f"{n}: mods", lambda ctx, g=g: nfs.install(ctx, g["key"], g), OPEN, 4, key=key),
            Step(f"{n}: display settings", lambda ctx, g=g: nfs.registry(ctx, g["key"], g), OPEN, 1, key=key),
            Step(f"{n}: shortcut", lambda ctx, g=g: nfs.shortcut(ctx, g["key"], g), CLOSED, 1, key=key),
        ]
    steps.append(Step("Controller templates", lambda ctx: nfs.assign_controllers(ctx, games), CLOSED, 1))
    return steps


def controller_targets(found: dict) -> list:
    return [nfs.controller_target(g) for g in found.values()]


def repair(found: dict, say):
    """Settings > Repair (Steam closed): re-add shortcuts Steam lost."""
    from engine.pipeline import Context
    ctx = Context(games=found, log=say)
    for key, g in found.items():
        nfs.shortcut(ctx, key, dict(g, key=key))
