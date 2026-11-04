"""
Modding Engine - shared code for Linux / SteamOS game mod installers.

Copied into a project as src/engine/. The engine never imports game code.
It reads two project modules that live next to it in src/:

    identity.py  - names, paths, repo (see template/src/identity.py)
    games.py     - the games, their files and their installers

See ENGINE.md for the contract and docs/ for how everything works.
"""

ENGINE_VERSION = "0.1.0"
