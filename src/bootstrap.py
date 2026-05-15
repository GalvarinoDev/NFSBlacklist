"""
bootstrap.py - NFSBlacklist pre-launch asset checker

Verifies that bundled assets (font, grid images) are present before the
PyQt5 UI initialises. Called from BootstrapScreen on a background thread
so the UI can show progress.

Unlike DeckOps, there are no Steam CDN downloads here. These games were
never on Steam so there are no store portrait images to fetch. Grid art
for non-Steam shortcuts is bundled with the repo in assets/images/headers/.

Orbitron variable font is bundled at assets/fonts/Orbitron-VariableFont_wght.ttf.

Music is downloaded from archive.org on first run if not already present.
Hero images for management screen cards are downloaded from SteamGridDB.
"""

import os

from log import get_logger

_log = get_logger(__name__)

# -- Paths ---------------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR    = os.path.join(PROJECT_ROOT, "assets", "fonts")
HEADERS_DIR  = os.path.join(PROJECT_ROOT, "assets", "images", "headers")
HEROES_DIR   = os.path.join(PROJECT_ROOT, "assets", "images", "heroes")
MUSIC_DIR    = os.path.join(PROJECT_ROOT, "assets", "music")
MUSIC_PATH   = os.path.join(MUSIC_DIR, "background.mp3")

os.makedirs(FONTS_DIR,   exist_ok=True)
os.makedirs(HEADERS_DIR, exist_ok=True)
os.makedirs(HEROES_DIR,  exist_ok=True)
os.makedirs(MUSIC_DIR,   exist_ok=True)

# -- Font ----------------------------------------------------------------------
# Orbitron is shipped with the repo in assets/fonts/ - no download needed.

FONT_FILE = "Orbitron-VariableFont_wght.ttf"

# -- Grid images ---------------------------------------------------------------
# Grid art for non-Steam shortcuts is bundled in assets/images/headers/.
# One image per game key. These are checked but not downloaded - they must
# be committed to the repo.

HEADER_KEYS = ["nfsu", "nfsu2", "nfsmw", "nfsc"]

# -- Hero images ---------------------------------------------------------------
# Wide banner images from SteamGridDB used as card backgrounds on the
# management screen. Downloaded on first run if not present.

HERO_IMAGES = {
    "nfsu":  {
        "url": "https://cdn2.steamgriddb.com/grid/4ea29595c25ccf7a33d3fdec75630d5a.png",
        "ext": "png",
    },
    "nfsu2": {
        "url": "https://cdn2.steamgriddb.com/grid/c0c783b5fc0d7d808f1d14a6e9c8280d.png",
        "ext": "png",
    },
    "nfsmw": {
        "url": "https://cdn2.steamgriddb.com/grid/6fdb8f7d90e975d5d19959a0fcebf123.png",
        "ext": "png",
    },
    "nfsc":  {
        "url": "https://cdn2.steamgriddb.com/grid/ee955e252af3c85e66e15864e31174fe.png",
        "ext": "png",
    },
}

# -- Music URL -----------------------------------------------------------------
# Same URL used in ui_constants.py. Defined here too so bootstrap doesn't
# need to import from ui_constants (which requires PyQt5 to be loaded).

MUSIC_URL = "https://dn710406.ca.archive.org/0/items/background_20260515/background.mp3"


# -- Public API ----------------------------------------------------------------

def run(on_progress=None, on_complete=None):
    """Check that all required assets are present and download missing ones.

    Font and grid images are bundled with the repo (no download needed).
    Background music and hero images are downloaded on first run.
    """
    if on_progress is None:
        on_progress = lambda pct, msg: print(f"[{pct:3d}%] {msg}")
    if on_complete is None:
        on_complete = lambda ok: None

    failed = 0

    # Font check
    font_path = os.path.join(FONTS_DIR, FONT_FILE)
    if os.path.exists(font_path):
        on_progress(5, f"Font: {FONT_FILE} (ok)")
    else:
        on_progress(5, f"Font: {FONT_FILE} (missing)")
        failed += 1

    # Grid image checks
    total_images = len(HEADER_KEYS)
    for i, key in enumerate(HEADER_KEYS):
        img_path = os.path.join(HEADERS_DIR, f"{key}_grid.jpg")
        pct = 5 + int((i + 1) / total_images * 15)
        if os.path.exists(img_path):
            on_progress(pct, f"Grid: {key}_grid.jpg (ok)")
        else:
            on_progress(pct, f"Grid: {key}_grid.jpg (missing)")
            # Not a hard failure - grid images are nice to have but
            # the app works without them. Don't increment failed.

    # Hero image downloads - fetch from SteamGridDB if not present
    on_progress(25, "Checking hero images...")
    from net import download
    hero_count = len(HERO_IMAGES)
    for i, (key, info) in enumerate(HERO_IMAGES.items()):
        hero_path = os.path.join(HEROES_DIR, f"{key}_hero.{info['ext']}")
        pct = 25 + int((i + 1) / hero_count * 25)
        if os.path.exists(hero_path) and os.path.getsize(hero_path) > 0:
            on_progress(pct, f"Hero: {key} (ok)")
        else:
            on_progress(pct, f"Downloading hero image: {key}...")
            try:
                download(
                    info["url"], hero_path,
                    label=f"{key} hero",
                )
                on_progress(pct, f"Hero: {key} (downloaded)")
                _log.info("bootstrap: downloaded hero image for %s", key)
            except Exception as e:
                on_progress(pct, f"Hero: {key} (download failed)")
                _log.warning("bootstrap: hero download failed for %s: %s", key, e)
                # Not a hard failure - cards work without hero images

    # Music download - fetch from archive.org if not present
    on_progress(55, "Checking background music...")
    if os.path.exists(MUSIC_PATH) and os.path.getsize(MUSIC_PATH) > 0:
        on_progress(90, "Music: background.mp3 (ok)")
    else:
        on_progress(60, "Downloading background music...")
        try:
            download(
                MUSIC_URL, MUSIC_PATH,
                on_progress=lambda pct, lbl: on_progress(
                    60 + int(pct * 0.30), f"Downloading music... {pct}%"
                ),
                label="background music",
            )
            on_progress(90, "Music: background.mp3 (downloaded)")
            _log.info("bootstrap: downloaded background music")
        except Exception as e:
            on_progress(90, "Music: download failed (not critical)")
            _log.warning("bootstrap: music download failed: %s", e)
            # Music is nice to have, not a hard failure

    on_progress(100, "Assets ready.")
    on_complete(failed == 0)


def fonts_ready() -> bool:
    """Returns True if the bundled Orbitron font file is present on disk."""
    return os.path.exists(os.path.join(FONTS_DIR, FONT_FILE))


def headers_ready() -> bool:
    """Returns True if all grid images are present."""
    return all(
        os.path.exists(os.path.join(HEADERS_DIR, f"{key}_grid.jpg"))
        for key in HEADER_KEYS
    )


def heroes_ready() -> bool:
    """Returns True if all hero images are present."""
    return all(
        os.path.exists(os.path.join(HEROES_DIR, f"{key}_hero.{info['ext']}"))
        and os.path.getsize(os.path.join(HEROES_DIR, f"{key}_hero.{info['ext']}")) > 0
        for key, info in HERO_IMAGES.items()
    )


def music_ready() -> bool:
    """Returns True if the background music file is present."""
    return os.path.exists(MUSIC_PATH) and os.path.getsize(MUSIC_PATH) > 0


def all_ready() -> bool:
    return fonts_ready() and headers_ready() and heroes_ready() and music_ready()
