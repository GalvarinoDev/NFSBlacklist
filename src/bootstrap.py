"""
bootstrap.py - NFSBlacklist pre-launch asset checker

Verifies that bundled assets (font, grid images) are present before the
PyQt5 UI initialises. Called from BootstrapScreen on a background thread
so the UI can show progress.

Unlike DeckOps, there are no Steam CDN downloads here. These games were
never on Steam so there are no store portrait images to fetch. Grid art
for non-Steam shortcuts is bundled with the repo in assets/images/headers/.

Russo One font is bundled at assets/fonts/RussoOne-Regular.ttf.

Music is NOT downloaded here. If assets/music/background.mp3 is present
it will be played automatically.
"""

import os

# -- Paths ---------------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR    = os.path.join(PROJECT_ROOT, "assets", "fonts")
HEADERS_DIR  = os.path.join(PROJECT_ROOT, "assets", "images", "headers")
MUSIC_DIR    = os.path.join(PROJECT_ROOT, "assets", "music")

os.makedirs(FONTS_DIR,   exist_ok=True)
os.makedirs(HEADERS_DIR, exist_ok=True)
os.makedirs(MUSIC_DIR,   exist_ok=True)

# -- Font ----------------------------------------------------------------------
# Russo One is shipped with the repo in assets/fonts/ - no download needed.

FONT_FILE = "RussoOne-Regular.ttf"

# -- Grid images ---------------------------------------------------------------
# Grid art for non-Steam shortcuts is bundled in assets/images/headers/.
# One image per game key. These are checked but not downloaded - they must
# be committed to the repo.

HEADER_KEYS = ["nfsu", "nfsu2", "nfsmw", "nfsc"]


# -- Public API ----------------------------------------------------------------

def run(on_progress=None, on_complete=None):
    """Check that all required assets are present.

    Since all assets are bundled (no downloads), this is just a verification
    pass. It reports what's present and what's missing.
    """
    if on_progress is None:
        on_progress = lambda pct, msg: print(f"[{pct:3d}%] {msg}")
    if on_complete is None:
        on_complete = lambda ok: None

    checks = []
    failed = 0

    # Font check
    font_path = os.path.join(FONTS_DIR, FONT_FILE)
    if os.path.exists(font_path):
        on_progress(10, f"Font: {FONT_FILE} (ok)")
    else:
        on_progress(10, f"Font: {FONT_FILE} (missing)")
        failed += 1

    # Grid image checks
    total_images = len(HEADER_KEYS)
    for i, key in enumerate(HEADER_KEYS):
        img_path = os.path.join(HEADERS_DIR, f"{key}_grid.jpg")
        pct = 10 + int((i + 1) / total_images * 80)
        if os.path.exists(img_path):
            on_progress(pct, f"Grid: {key}_grid.jpg (ok)")
        else:
            on_progress(pct, f"Grid: {key}_grid.jpg (missing)")
            # Not a hard failure - grid images are nice to have but
            # the app works without them. Don't increment failed.

    on_progress(100, "Assets ready.")
    on_complete(failed == 0)


def fonts_ready() -> bool:
    """Returns True if the bundled Russo One font file is present on disk."""
    return os.path.exists(os.path.join(FONTS_DIR, FONT_FILE))


def headers_ready() -> bool:
    """Returns True if all grid images are present."""
    return all(
        os.path.exists(os.path.join(HEADERS_DIR, f"{key}_grid.jpg"))
        for key in HEADER_KEYS
    )


def all_ready() -> bool:
    return fonts_ready() and headers_ready()
