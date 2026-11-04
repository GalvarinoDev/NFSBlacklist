"""
nfs.py - the four Black Box NFS games: ASI mods, registry, shortcut

Mod stack per game, lowest layer first (each plugin needs the ASI loader
the Widescreen Fix ships as dinput8.dll):
    Widescreen Fix (ThirteenAG)   dinput8.dll + scripts/
    Extra Options (ExOptsTeam)    scripts/*.asi + ini
    XtendedInput (xan1242)        scripts/ + button textures (Global/ or GLOBAL/)
    XenonEffects (xan1242)        NFSMW only; Carbon's Widescreen Fix has FixXenonEffects built in

Every pack bundles its own dinput8.dll; only the Widescreen Fix's is kept,
since it is the newest. The packs' READMEs and txt files are not deployed.
"""

import os
import shutil

from engine import config, controller, launch, mods, proton, shortcuts, steam, wine
from engine.files import ci_path
from engine.game_config import set_ini

_WSF = "https://github.com/ThirteenAG/WidescreenFixesPack/releases/download"


class _Pick(mods.UrlMod):
    """A fixed-URL zip of which only `keep` (files or folders under `root`) is deployed."""
    root = ""
    keep = ()
    ini = None  # (path, {section: {key: value}}): patched in staging so the receipt hash matches what lands

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def stage(self, workdir, staging, option, prog):
        tmp = os.path.join(workdir, "x")
        super().stage(workdir, tmp, option, prog)
        for rel in self.keep:
            src = ci_path(os.path.join(tmp, self.root), rel)
            dst = os.path.join(staging, rel)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            else:
                raise RuntimeError(f"{self.name}: {rel} missing from {os.path.basename(self.url)}")
        if self.ini:
            path, sections = self.ini
            for section, values in sections.items():
                set_ini(os.path.join(staging, path), values, section, create=False)
        return self.version


def _mod(id_, name, layer, url, keep, root="", ini=None, version="1"):
    return _Pick(id=id_, name=name, layer=layer, url=url, keep=keep, root=root, ini=ini, version=version)


# ImproveGamepadSupport off: XtendedInput handles the pad. AutoFitFE on: UI fits 16:10 screens.
# NFSU2's stock ini already has ImproveGamepadSupport = 4 (None); MW and Carbon ship AutoFitFE = 1.
def _wsf(slug, tag, gamepad=True, autofit=True):
    ini = {}
    if gamepad:
        ini["MISC"] = {"ImproveGamepadSupport": "0"}
    if autofit:
        ini["MAIN"] = {"AutoFitFE": "1"}
    # The per-game tags are re-uploaded with every fix; take the whole scripts/ folder
    return _mod("widescreen_fix", "Widescreen Fix", 10, f"{_WSF}/{tag}/{slug}.WidescreenFix.zip",
                ("dinput8.dll", "scripts"), ini=(f"scripts/{slug}.WidescreenFix.ini", ini))


def _exopts(game, repo_ver, root=""):
    url = f"https://github.com/ExOptsTeam/{game}ExOpts/releases/download/v{repo_ver}/{game}.ExOpts.v{repo_ver}.zip"
    return _mod("extra_options", "Extra Options", 20, url,
                (f"scripts/{game}ExtraOptions.asi", f"scripts/{game}ExtraOptionsSettings.ini"), root, version=repo_ver)


def _xinput(repo, ver, pack, asi, extra=()):
    url = f"https://github.com/xan1242/{repo}/releases/download/{ver}/Release-{pack}-Pack.zip"
    return _mod("xtended_input", "XtendedInput", 30, url, (f"scripts/{asi}.asi", f"scripts/{asi}.ini", *extra), version=ver)


_MW_XI = ("scripts/NFS_XtendedInput.default.ini", "scripts/nfs_cursor.cur", "GLOBAL/XtendedInputButtons.tpk")


def mod_list(key: str) -> list:
    return {
        "nfsu": [_wsf("NFSUnderground", "nfsu"),
                 _exopts("NFSU", "3.0.1.1337"),
                 _xinput("NFSU-XtendedInput", "2.7", "UG", "NFSU_XtendedInput", ("Global/UG_ConsoleButtons.tpk",))],
        "nfsu2": [_wsf("NFSUnderground2", "nfsu2", gamepad=False),
                  _exopts("NFSU2", "5.1.0.1340"),
                  _xinput("NFSU-XtendedInput", "2.7", "UG2", "NFSU_XtendedInput")],
        "nfsmw": [_wsf("NFSMostWanted", "nfsmw", autofit=False),
                  _exopts("NFSMW", "10.0.1.1337"),
                  _xinput("NFS-XtendedInput", "1.22", "MW", "NFS_XtendedInput", _MW_XI),
                  _mod("xenon_effects", "XenonEffects", 40,
                       "https://github.com/xan1242/NFSMW_XenonEffects/releases/download/1.02/NFSMW_XenonEffects.zip",
                       ("scripts/NFSMW_XenonEffects.asi", "scripts/NFSMW_XenonEffects.ini", "GLOBAL/XenonEffects.tpk"),
                       version="1.02")],
        "nfsc": [_wsf("NFSCarbon", "nfsc", autofit=False),
                 _exopts("NFSC", "3.0.1.1338", root="Main Files"),  # Carbon's zip nests everything under Main Files/
                 _xinput("NFS-XtendedInput", "1.22", "Carbon", "NFS_XtendedInput", _MW_XI)],
    }[key]


def install(ctx, key, game):
    mods.install_all(game["install_dir"], mod_list(key), key, on_progress=ctx.say)


# --- registry
# Without these the games start at their minimum resolution (320x200 for MW)
# or crash when graphics settings are changed (Carbon on Proton 9+). Values
# are what each game writes on a real first launch, tuned for handheld APUs.

REG_KEYS = {
    "nfsu": [r"Software\EA Games\Need For Speed Underground"],
    "nfsu2": [r"Software\EA Games\Need for Speed Underground 2"],
    "nfsmw": [r"Software\EA Games\Need for Speed Most Wanted"],
    # Carbon also reads its Spanish-locale key
    "nfsc": [r"Software\Electronic Arts\Need for Speed Carbon", r"Software\Electronic Arts\Need for Speed Carbono"],
}

GRAPHICS = {
    "nfsu": dict(g_AnimatedTextureEnable=1, g_BleachByPassEnable=1, g_CarEnvironmentMapEnable=1,
                 g_CarEnvironmentMapUpdateData=1, g_CarLodLevel=1, g_FSAALevel=0, g_MotionBlurEnable=1,
                 g_OverBrightEnable=1, g_ParticleSystemEnable=1, g_PerformanceLevel=3, g_RainEnable=1,
                 g_RoadReflectionEnable=0, g_TextureFiltering=1, g_VisualTreatment=1, g_VSyncOn=0, g_WorldLodLevel=2),
    "nfsu2": dict(g_AnimatedTextureEnable=1, g_BleachByPassEnable=1, g_CarDamageEnable=0, g_CarEnvironmentMapEnable=3,
                  g_CarEnvironmentMapUpdateData=1, g_CarHeadlightEnable=1, g_CarLightingEnable=0, g_CarLodLevel=1,
                  g_CarShadowEnable=2, g_CrowdEnable=1, g_DepthOfFieldEnable=1, g_FogEnable=1, g_FSAALevel=2,
                  g_HorizonFogEnable=1, g_LightGlowEnable=1, g_LightStreaksEnable=1, g_MotionBlurEnable=1,
                  g_OverBrightEnable=1, g_ParticleSystemEnable=1, g_PerformanceLevel=5, g_RainEnable=1,
                  g_RoadReflectionEnable=3, g_TextureFiltering=2, g_TintingEnable=1, g_VSyncOn=0, g_WorldLodLevel=3,
                  NotFirstTime=1),
    "nfsmw": dict(g_CarEnvironmentMapEnable=0, g_CarEnvironmentMapUpdateData=0, g_CarLodLevel=0, g_FSAALevel=0,
                  g_MotionBlurEnable=1, g_OverBrightEnable=0, g_ParticleSystemEnable=1, g_PerformanceLevel=1,
                  g_RainEnable=1, g_RoadReflectionEnable=0, g_ShadowDetail=0, g_TextureFiltering=0,
                  g_VisualTreatment=1, g_VSyncOn=0, g_WorldLodLevel=0, FirstTime=1),
    "nfsc": dict(g_AudioMode=0, g_Brightness=0, g_CarEnvironmentMapEnable=3, g_CarLodLevel=1, g_FSAALevel=2,
                 g_MotionBlurEnable=1, g_ParticleSystemEnable=1, g_PerformanceLevel=5, g_RainEnable=1,
                 g_RoadReflectionEnable=2, g_ShaderDetailLevel=3, g_ShadowDetail=0, g_TextureFiltering=2,
                 g_VisualTreatment=1, g_VSyncOn=0, g_WorldLodLevel=3, FirstTime=0),
}

# Carbon stores a table index, not a size; 2 = 1024x768. The Widescreen Fix renders widescreen on top.
NFSC_RES_INDEX = 2


def reg_values(key: str, install_dir: str, resolution: str) -> dict:
    w, h = (int(n) for n in resolution.split("_")[0].split("x"))
    path = proton.z_path(install_dir) + "\\"
    return {
        # U, U2, MW: packed dword 0x80000000 | width << 16 | height
        "g_RacingResolution": NFSC_RES_INDEX if key == "nfsc" else 0x80000000 | (w << 16) | h,
        "Install Dir": path, "InstallDir": path, "Path": path,
        "@": "INSERTYOURCDKEYHERE", "CD Drive": "D:\\", "Language": "English US",
        "CacheSize": 0xFFFFFFFF, "StreamingInstall": 0, "SwapSize": 0x04600000, "VERSION": 1, "SIZE": 0x64,
        **GRAPHICS[key],
    }


def registry(ctx, key, game):
    res = config.resolution()
    for reg_key in REG_KEYS[key]:
        wine.set_reg(game["compatdata"], wine.HKCU, reg_key, reg_values(key, game["install_dir"], res))
    ctx.say(f"  {game['name']}: display settings for {res}")


# --- shortcut
# None of these games were sold on Steam: every copy is a non-Steam shortcut.
# appid = crc32('"<exe>"' + name), the same formula the pre-engine app used,
# so existing prefixes, artwork and play time carry over.

def appid(game) -> int:
    return steam.shortcut_appid(shortcuts.quote(game["exe_path"]), game["name"])


def compatdata(game, steam_root=None) -> str:
    return steam.compatdata(appid(game), steam_root)


def shortcut(ctx, key, game):
    """Steam closed."""
    shortcuts.add(game["name"], game["exe_path"], start_dir=game["install_dir"],
                  launch_options=launch.dll_overrides({"dinput8": "n,b"}),  # the ASI loader proxy
                  art=game.get("art"), compat_tool=ctx.data.get("proton_tool") or proton.tool_name(),
                  on_progress=ctx.say, steam_root=ctx.steam_root)


def controller_target(game) -> dict:
    return {"appid": appid(game), "title": game["name"], "profile": game.get("profile", "gamepad")}


def assign_controllers(ctx, games: list):
    controller.install_templates(ctx.say, ctx.steam_root)
    ext = config.get("external_controller") if config.get("play_mode") == "docked" else None
    controller.assign([controller_target(g) for g in games], external=ext, on_progress=ctx.say, steam_root=ctx.steam_root)
