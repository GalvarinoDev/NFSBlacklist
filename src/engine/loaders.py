"""
loaders.py - ready-made Mod classes for common loaders and wrappers

Each class is an engine.mods.Mod. Subclass and set what differs (dest,
dll name, layer). Every loader that drops a DLL Windows would normally
load from system32 needs a DLL override under Proton; after_deploy writes
it into the prefix when the game's compatdata is known, and dll_option()
gives the launch option form for Steam games.

    UltimateAsiLoader  ThirteenAG's ASI loader (dinput8/d3d9/winmm/... proxy);
                       loads *.asi plugins: widescreen fixes, FPS unlocks
    Dxvk               D3D8/9/10/11 to Vulkan, for non-Proton launchers or an
                       older/newer DXVK than Proton ships
    DgVoodoo2          Glide / DirectDraw / D3D1-7 to D3D11; very old games
    BepInEx            Unity mod loader (winhttp.dll proxy) for Mono games
    MelonLoader        Unity loader (version.dll proxy), Mono and IL2CPP
"""

import os

from .mods import GitHubMod, UrlMod
from .launch import dll_overrides


class _DllLoader(GitHubMod):
    dlls = {}              # {"dinput8": "n,b"}: overrides this loader needs
    compat = None          # game's compatdata; set by the project before install

    def after_deploy(self, game_dir, option, prog):
        if self.compat and os.path.isdir(os.path.join(self.compat, "pfx")):
            from .wine import set_dll_overrides
            set_dll_overrides(self.compat, {k: "native,builtin" if v == "n,b" else v for k, v in self.dlls.items()})
            prog(f"  DLL overrides set: {', '.join(self.dlls)}")

    def dll_option(self, command: str = "%command%") -> str:
        return dll_overrides(self.dlls, command)


class UltimateAsiLoader(_DllLoader):
    """
    Pick the proxy name the game actually imports (check its imports or the
    mod's readme): dinput8 for most DirectInput games, d3d9 / winmm / dsound
    / version otherwise. 32-bit games need the Win32 build.
    """
    id, name, layer = "asi_loader", "Ultimate ASI Loader", 5
    repo = "ThirteenAG/Ultimate-ASI-Loader"
    proxy = "dinput8"
    x64 = False

    @property
    def pattern(self):
        return r"^Ultimate-ASI-Loader_x64\.zip$" if self.x64 else r"^Ultimate-ASI-Loader\.zip$"

    @property
    def dlls(self):
        return {self.proxy: "n,b"}

    def stage(self, workdir, staging, option, prog):
        ver = super().stage(workdir, staging, option, prog)
        src = os.path.join(staging, "dinput8.dll")
        if os.path.exists(src) and self.proxy != "dinput8":
            os.replace(src, os.path.join(staging, f"{self.proxy}.dll"))
        return ver


class Dxvk(_DllLoader):
    """Copies x32 or x64 DLLs next to the exe; Steam/Proton games already have DXVK."""
    id, name, layer = "dxvk", "DXVK", 4
    repo, pattern = "doitsujin/dxvk", r"^dxvk-[\d.]+\.tar\.gz$"   # not dxvk-native
    x64 = True
    apis = ("d3d8", "d3d9", "d3d10core", "d3d11", "dxgi")

    @property
    def dlls(self):
        return {a: "n" for a in self.apis}

    def stage(self, workdir, staging, option, prog):
        tmp = os.path.join(workdir, "x")
        ver = super().stage(workdir, tmp, option, prog)
        arch = "x64" if self.x64 else "x32"
        for d, _, names in os.walk(tmp):
            if os.path.basename(d) == arch:
                os.makedirs(staging, exist_ok=True)
                for n in names:
                    if n[:-4] in self.apis:
                        os.replace(os.path.join(d, n), os.path.join(staging, n))
        return ver


class DgVoodoo2(_DllLoader):
    """
    dgVoodoo2 for DirectDraw/D3D1-7/Glide games. Ships MS/x86 DLLs plus
    dgVoodoo.conf; edit the conf (resolution, scaling) in after_deploy.
    """
    id, name, layer = "dgvoodoo2", "dgVoodoo2", 4
    repo, pattern = "dege-diosg/dgVoodoo2", r"^dgVoodoo2_[\d_]+\.zip$"   # not _dbg / _dev64 / API
    apis = ("DDraw", "D3DImm", "D3D8", "D3D9")

    @property
    def dlls(self):
        return {a.lower(): "n" for a in self.apis}

    def stage(self, workdir, staging, option, prog):
        tmp = os.path.join(workdir, "x")
        ver = super().stage(workdir, tmp, option, prog)
        os.makedirs(staging, exist_ok=True)
        for d, _, names in os.walk(tmp):
            for n in names:
                p = os.path.join(d, n)
                if n == "dgVoodoo.conf" or (d.replace("\\", "/").endswith("MS/x86") and n[:-4] in self.apis):
                    os.replace(p, os.path.join(staging, n))
        return ver


class BepInEx(_DllLoader):
    """
    BepInEx 5 for Unity Mono games (x64 build by default). Plugins go in
    BepInEx/plugins/. Under Proton it needs winhttp overridden.
    """
    id, name, layer = "bepinex", "BepInEx", 5
    repo = "BepInEx/BepInEx"
    x64 = True
    dlls = {"winhttp": "n,b"}

    @property
    def pattern(self):
        return r"^BepInEx_win_x64_5[\d.]+\.zip$" if self.x64 else r"^BepInEx_win_x86_5[\d.]+\.zip$"


class MelonLoader(_DllLoader):
    """MelonLoader for Unity (Mono and IL2CPP). Mods go in Mods/."""
    id, name, layer = "melonloader", "MelonLoader", 5
    repo = "LavaGang/MelonLoader"
    x64 = True
    dlls = {"version": "n,b"}

    @property
    def pattern(self):
        return r"^MelonLoader\.x64\.zip$" if self.x64 else r"^MelonLoader\.x86\.zip$"


class FileDrop(UrlMod):
    """One file (a fix DLL, a patched exe kept beside the original) from a URL."""
    id, name, layer = "file", "File", 20
