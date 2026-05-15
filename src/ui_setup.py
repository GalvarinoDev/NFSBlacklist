"""
ui_setup.py - First-run setup flow for NFSBlacklist

Unified progressive disclosure flow:
    OS -> Device -> Gyro -> Name -> Done (route to OwnScanScreen)

Simpler than DeckOps: no source choice (always own), no Decky install,
no docked controller section. Gyro is for steering assist, not aiming.
"""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage, QColor

import config as cfg

from ui_constants import (
    C_BG, C_CARD, C_ACCENT1, C_ACCENT2, C_DIM, C_DARK_BTN, C_BLUE_BTN,
    font, _btn, _lbl, _hdiv, _title_block, _Sigs,
    go_to, get_screen,
    PROJECT_ROOT,
)


# -- Paths --------------------------------------------------------------------

M3_IMAGE_PATH = os.path.join(PROJECT_ROOT, "assets", "images", "m3.png")


# -- Background removal -------------------------------------------------------

def _remove_grey_bg(path: str, threshold: int = 30) -> QPixmap:
    """
    Load an image and make near-grey/near-white background pixels transparent.

    Works by sampling the four corners to determine the background colour,
    then flood-filling outward from each corner replacing pixels within
    `threshold` distance (per channel) of that colour with transparency.
    Returns a QPixmap with an alpha channel, or None if the file can't be read.
    """
    img = QImage(path)
    if img.isNull():
        return None

    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()

    # Sample corners to get background colour - average them
    corners = [
        img.pixelColor(0, 0),
        img.pixelColor(w - 1, 0),
        img.pixelColor(0, h - 1),
        img.pixelColor(w - 1, h - 1),
    ]
    bg_r = sum(c.red()   for c in corners) // 4
    bg_g = sum(c.green() for c in corners) // 4
    bg_b = sum(c.blue()  for c in corners) // 4

    def _is_bg(color):
        return (
            abs(color.red()   - bg_r) <= threshold and
            abs(color.green() - bg_g) <= threshold and
            abs(color.blue()  - bg_b) <= threshold
        )

    transparent = QColor(0, 0, 0, 0)

    # BFS flood fill from all four corners simultaneously
    visited = set()
    queue = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for pos in queue:
        visited.add(pos)

    while queue:
        next_queue = []
        for x, y in queue:
            if _is_bg(img.pixelColor(x, y)):
                img.setPixelColor(x, y, transparent)
                for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        visited.add((nx, ny))
                        next_queue.append((nx, ny))
        queue = next_queue

    return QPixmap.fromImage(img)


# -- Device definitions --------------------------------------------------------
#
# Each device maps to: deck_model, other_device (resolution key),
# other_device_type (controller template group), has_gyro.

DEVICES = {
    "sd_lcd":       {"label": "Steam Deck LCD",       "deck_model": "lcd",   "other_device": None,              "other_device_type": None,            "has_gyro": True},
    "sd_oled":      {"label": "Steam Deck OLED",      "deck_model": "oled",  "other_device": None,              "other_device_type": None,            "has_gyro": True},
    "legion_go":    {"label": "Lenovo Legion Go",     "deck_model": "other", "other_device": "1920x1200",       "other_device_type": "legion_go",     "has_gyro": True},
    "legion_go_s":  {"label": "Lenovo Legion Go S",   "deck_model": "other", "other_device": "1920x1200",       "other_device_type": "legion_go_s",   "has_gyro": True},
    "legion_go_2":  {"label": "Lenovo Legion Go 2",   "deck_model": "other", "other_device": "1920x1200_144hz", "other_device_type": "legion_go_2",   "has_gyro": True},
    "rog_ally":     {"label": "ROG Ally",              "deck_model": "other", "other_device": "1920x1080",       "other_device_type": "2btn",          "has_gyro": True},
    "rog_ally_x":   {"label": "ROG Ally X",            "deck_model": "other", "other_device": "1920x1080",       "other_device_type": "2btn",          "has_gyro": True},
    "xbox_ally_x":  {"label": "ROG Xbox Ally X",       "deck_model": "other", "other_device": "1920x1080",       "other_device_type": "2btn",          "has_gyro": True},
    "msi_claw_8":   {"label": "MSI Claw 8",           "deck_model": "other", "other_device": "1920x1200",       "other_device_type": "2btn",          "has_gyro": True},
    "general_pc":   {"label": "PC",                    "deck_model": "other", "other_device": None,              "other_device_type": "generic",       "has_gyro": False},
    "steam_machine":{"label": "Steam Machine",         "deck_model": "steam_machine", "other_device": None,      "other_device_type": "steam_machine", "has_gyro": False},
}


class SetupFlowScreen(QWidget):
    """
    Unified first-run setup. One QWidget with show/hide sections
    for progressive disclosure. screen_name = "SetupFlowScreen".
    """

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.screen_name = "SetupFlowScreen"
        self._selected_os = None      # "steamos", "bazzite", "cachyos"
        self._selected_device = None  # key from DEVICES
        self._is_general_pc = False
        self._is_steam_machine = False

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)

        # -- 1. OS section -----------------------------------------------------
        # Two-column layout: left = title + info + buttons, right = M3 GTR image
        self._os_section = QWidget()
        os_outer = QHBoxLayout(self._os_section)
        os_outer.setContentsMargins(0, 0, 0, 0)
        os_outer.setSpacing(0)

        # Left column: all the text and buttons
        left_panel = QWidget()
        lay = QVBoxLayout(left_panel)
        lay.setContentsMargins(80, 60, 40, 60); lay.setSpacing(16)
        _title_block(lay)
        lay.addSpacing(8)
        lay.addWidget(_lbl(
            "NFSBlacklist sets up your classic Black Box NFS games with "
            "widescreen fixes, controller profiles, and Proton prefixes - "
            "so you can boot into Game Mode and just play.",
            14, "#CCCCCC"))
        lay.addSpacing(6)
        for warn in [
            "\u26A0   NFSBlacklist will automatically create Proton prefixes for your games. "
            "You do NOT need to launch each game through Steam first.",
            "\u26A0   Make sure your game files are in ~/Games, ~/NFS, or on an SD card "
            "before continuing. NFSBlacklist will scan for them automatically.",
            "\u26A0   Make sure you have a stable internet connection before installing. "
            "Mods and GE-Proton will be downloaded during setup.",
        ]:
            lay.addWidget(_lbl(warn, 13, C_ACCENT2, align=Qt.AlignLeft))
        lay.addSpacing(16)
        lay.addWidget(_lbl("What operating system are you running?", 15, "#CCC"))
        lay.addSpacing(12)

        os_row = QHBoxLayout(); os_row.setSpacing(20)
        for os_key, label in [
            ("steamos", "SteamOS"),
            ("bazzite", "Bazzite"),
            ("cachyos", "CachyOS"),
        ]:
            b = _btn(label, C_ACCENT1, h=56)
            b.clicked.connect(lambda _, k=os_key: self._pick_os(k))
            os_row.addWidget(b)
        lay.addLayout(os_row)
        os_outer.addWidget(left_panel, stretch=3)

        # Right column: M3 GTR image
        right_panel = QWidget()
        rlay = QVBoxLayout(right_panel)
        rlay.setContentsMargins(0, 60, 60, 60)
        rlay.addStretch()
        self._m3_label = QLabel()
        self._m3_label.setAlignment(Qt.AlignCenter)
        self._m3_label.setStyleSheet("background: transparent;")
        if os.path.exists(M3_IMAGE_PATH):
            px = _remove_grey_bg(M3_IMAGE_PATH)
            if px and not px.isNull():
                # Scale to reasonable size, keep aspect ratio
                scaled = px.scaledToWidth(420, Qt.SmoothTransformation)
                self._m3_label.setPixmap(scaled)
        rlay.addWidget(self._m3_label)
        rlay.addStretch()
        os_outer.addWidget(right_panel, stretch=2)

        main_lay.addWidget(self._os_section)

        # -- 2. Device model section -------------------------------------------
        self._model_section = QWidget(); self._model_section.setVisible(False)
        ml = QVBoxLayout(self._model_section)
        ml.setContentsMargins(80, 60, 80, 60); ml.setSpacing(16)
        self._back_os_btn = _btn("\u2190 Back", C_DARK_BTN, size=10, h=30)
        self._back_os_btn.setFixedWidth(80)
        self._back_os_btn.clicked.connect(self._back_to_os)
        brow = QHBoxLayout(); brow.addWidget(self._back_os_btn); brow.addStretch()
        ml.addLayout(brow)
        ml.addSpacing(40)
        _title_block(ml)
        ml.addStretch()
        ml.addWidget(_lbl("Which device do you have?", 15, "#CCC"))
        ml.addSpacing(12)
        mrow = QHBoxLayout(); mrow.setSpacing(20)
        lcd_btn  = _btn("Steam Deck LCD",  C_ACCENT1, h=56)
        oled_btn = _btn("Steam Deck OLED", C_ACCENT1, h=56)
        sm_btn   = _btn("Steam Machine",   C_ACCENT1, h=56)
        other_btn = _btn("Other Device",   C_ACCENT2, h=56)
        lcd_btn.clicked.connect(lambda _: self._pick_device("sd_lcd"))
        oled_btn.clicked.connect(lambda _: self._pick_device("sd_oled"))
        sm_btn.clicked.connect(lambda _: self._pick_device("steam_machine"))
        other_btn.clicked.connect(self._show_device_picker)
        mrow.addWidget(lcd_btn); mrow.addWidget(oled_btn); mrow.addWidget(sm_btn); mrow.addWidget(other_btn)
        ml.addLayout(mrow)
        ml.addSpacing(40)
        main_lay.addWidget(self._model_section)

        # -- 3. Specific device picker (Other) ---------------------------------
        self._device_section = QWidget(); self._device_section.setVisible(False)
        dvl = QVBoxLayout(self._device_section)
        dvl.setContentsMargins(80, 60, 80, 60); dvl.setSpacing(16)
        self._back_model_btn = _btn("\u2190 Back", C_DARK_BTN, size=10, h=30)
        self._back_model_btn.setFixedWidth(80)
        self._back_model_btn.clicked.connect(self._back_to_model)
        brow2 = QHBoxLayout(); brow2.addWidget(self._back_model_btn); brow2.addStretch()
        dvl.addLayout(brow2)
        dvl.addSpacing(40)
        _title_block(dvl)
        dvl.addStretch()
        dvl.addWidget(_lbl("Select your device", 15, "#CCC"))
        dvl.addSpacing(4)
        dvl.addWidget(_lbl(
            "Pick the device closest to yours. This sets the display resolution, "
            "refresh rate, and controller profile group.",
            13, C_DIM, align=Qt.AlignLeft))
        dvl.addSpacing(12)

        dev_cols = QHBoxLayout(); dev_cols.setSpacing(20)

        # Left column: Lenovo
        col_lenovo = QVBoxLayout(); col_lenovo.setSpacing(10)
        col_lenovo.addWidget(_lbl("Lenovo", 12, C_DIM, bold=True))
        for dev_key in ("legion_go", "legion_go_s", "legion_go_2"):
            b = _btn(DEVICES[dev_key]["label"], C_DARK_BTN, h=48)
            b.clicked.connect(lambda _, k=dev_key: self._pick_device(k))
            col_lenovo.addWidget(b)
        dev_cols.addLayout(col_lenovo)

        # Middle column: ASUS
        col_asus = QVBoxLayout(); col_asus.setSpacing(10)
        col_asus.addWidget(_lbl("ASUS", 12, C_DIM, bold=True))
        for dev_key in ("rog_ally", "rog_ally_x", "xbox_ally_x"):
            b = _btn(DEVICES[dev_key]["label"], C_DARK_BTN, h=48)
            b.clicked.connect(lambda _, k=dev_key: self._pick_device(k))
            col_asus.addWidget(b)
        dev_cols.addLayout(col_asus)

        # Right column: MSI + PC
        col_right = QVBoxLayout(); col_right.setSpacing(10)
        col_right.addWidget(_lbl("MSI", 12, C_DIM, bold=True))
        msi_btn = _btn(DEVICES["msi_claw_8"]["label"], C_DARK_BTN, h=48)
        msi_btn.clicked.connect(lambda _: self._pick_device("msi_claw_8"))
        col_right.addWidget(msi_btn)
        col_right.addSpacing(10)
        col_right.addWidget(_lbl("Other", 12, C_DIM, bold=True))
        pc_btn = _btn("PC", C_DARK_BTN, h=48)
        pc_btn.clicked.connect(lambda _: self._pick_device("general_pc"))
        col_right.addWidget(pc_btn)
        dev_cols.addLayout(col_right)

        dvl.addLayout(dev_cols)
        dvl.addSpacing(40)
        main_lay.addWidget(self._device_section)

        # -- 4. Gyro section ---------------------------------------------------
        self._gyro_section = QWidget(); self._gyro_section.setVisible(False)
        gl = QVBoxLayout(self._gyro_section)
        gl.setContentsMargins(80, 60, 80, 60); gl.setSpacing(16)
        self._back_device_gyro_btn = _btn("\u2190 Back", C_DARK_BTN, size=10, h=30)
        self._back_device_gyro_btn.setFixedWidth(80)
        self._back_device_gyro_btn.clicked.connect(self._back_to_device_from_gyro)
        brow3 = QHBoxLayout(); brow3.addWidget(self._back_device_gyro_btn); brow3.addStretch()
        gl.addLayout(brow3)
        gl.addSpacing(40)
        _title_block(gl)
        gl.addStretch()
        gl.addWidget(_lbl("Do you want gyro steering?", 15, "#CCC"))
        gl.addSpacing(4)
        gl.addWidget(_lbl(
            "Tilt your device to steer. Works as a subtle steering assist "
            "alongside the left stick. Can be turned off later.",
            13, C_DIM, align=Qt.AlignLeft))
        gl.addSpacing(12)
        grow = QHBoxLayout(); grow.setSpacing(20)
        gyro_yes = _btn("Yes", C_ACCENT1, h=56)
        gyro_no  = _btn("No",  C_DARK_BTN, h=56)
        gyro_yes.clicked.connect(lambda _: self._pick_gyro("on"))
        gyro_no.clicked.connect(lambda _: self._pick_gyro("off"))
        grow.addWidget(gyro_yes); grow.addWidget(gyro_no)
        gl.addLayout(grow)
        gl.addSpacing(40)
        main_lay.addWidget(self._gyro_section)

        # -- 5. Player name section --------------------------------------------
        self._name_section = QWidget(); self._name_section.setVisible(False)
        nl = QVBoxLayout(self._name_section)
        nl.setContentsMargins(80, 60, 80, 60); nl.setSpacing(16)
        self._back_gyro_name_btn = _btn("\u2190 Back", C_DARK_BTN, size=10, h=30)
        self._back_gyro_name_btn.setFixedWidth(80)
        self._back_gyro_name_btn.clicked.connect(self._back_to_gyro_from_name)
        brow4 = QHBoxLayout(); brow4.addWidget(self._back_gyro_name_btn); brow4.addStretch()
        nl.addLayout(brow4)
        nl.addSpacing(40)
        _title_block(nl)
        nl.addStretch()
        nl.addWidget(_lbl("What's your player name?", 15, "#CCC"))
        nl.addSpacing(4)
        nl.addWidget(_lbl(
            "Your Steam display name is filled in by default. "
            "Change it to whatever you want.",
            13, C_DIM, align=Qt.AlignLeft))
        nl.addSpacing(12)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Player")
        self._name_input.setMaxLength(32)
        self._name_input.setFixedHeight(48)
        self._name_input.setFont(font(14))
        self._name_input.setStyleSheet(
            f"QLineEdit{{background:{C_CARD};color:#FFF;border:2px solid #33333F;"
            f"border-radius:8px;padding:0 16px;}}"
            f"QLineEdit:focus{{border-color:{C_ACCENT1};}}"
        )
        nl.addWidget(self._name_input)
        nl.addSpacing(16)
        name_cont = _btn("Continue >>", C_ACCENT1, h=52)
        name_cont.setFixedWidth(260)
        name_cont.clicked.connect(self._save_player_name)
        nc_row = QHBoxLayout(); nc_row.addStretch(); nc_row.addWidget(name_cont); nc_row.addStretch()
        nl.addLayout(nc_row)
        nl.addSpacing(40)
        main_lay.addWidget(self._name_section)

        # -- 6. Resolution section (Steam Machine + General PC) ----------------
        self._resolution_section = QWidget(); self._resolution_section.setVisible(False)
        rl = QVBoxLayout(self._resolution_section)
        rl.setContentsMargins(80, 60, 80, 60); rl.setSpacing(16)
        self._back_res_btn = _btn("\u2190 Back", C_DARK_BTN, size=10, h=30)
        self._back_res_btn.setFixedWidth(80)
        self._back_res_btn.clicked.connect(self._back_to_name_from_res)
        brow_res = QHBoxLayout(); brow_res.addWidget(self._back_res_btn); brow_res.addStretch()
        rl.addLayout(brow_res)
        rl.addSpacing(40)
        _title_block(rl)
        rl.addStretch()
        rl.addWidget(_lbl("What resolution is your display?", 15, "#CCC"))
        rl.addSpacing(4)
        rl.addWidget(_lbl(
            "Pick the resolution that matches your monitor or TV, "
            "or choose My Own to set it yourself in-game.",
            13, C_DIM, align=Qt.AlignLeft))
        rl.addSpacing(12)

        res_cols = QHBoxLayout(); res_cols.setSpacing(20)
        col_1610 = QVBoxLayout(); col_1610.setSpacing(10)
        col_1610.addWidget(_lbl("16:10", 13, C_ACCENT1, bold=True))
        for res_key, label in [("1280x800", "1280 x 800"), ("1920x1200", "1920 x 1200")]:
            b = _btn(label, C_DARK_BTN, h=52)
            b.clicked.connect(lambda _, k=res_key: self._pick_resolution(k))
            col_1610.addWidget(b)
        res_cols.addLayout(col_1610)

        col_169 = QVBoxLayout(); col_169.setSpacing(10)
        col_169.addWidget(_lbl("16:9", 13, C_ACCENT1, bold=True))
        for res_key, label in [("1280x720", "1280 x 720"), ("1920x1080", "1920 x 1080")]:
            b = _btn(label, C_DARK_BTN, h=52)
            b.clicked.connect(lambda _, k=res_key: self._pick_resolution(k))
            col_169.addWidget(b)
        res_cols.addLayout(col_169)

        rl.addLayout(res_cols)
        rl.addSpacing(8)
        own_res = _btn("My Own", C_DARK_BTN, h=44)
        own_res.setFixedWidth(200)
        own_res.clicked.connect(lambda _: self._pick_resolution("own"))
        own_row = QHBoxLayout(); own_row.addStretch(); own_row.addWidget(own_res); own_row.addStretch()
        rl.addLayout(own_row)
        rl.addSpacing(40)
        main_lay.addWidget(self._resolution_section)

    # -- Section visibility helpers --------------------------------------------

    def _hide_all(self):
        for attr in dir(self):
            if attr.endswith("_section") and hasattr(getattr(self, attr), "setVisible"):
                getattr(self, attr).setVisible(False)

    def _show(self, section_name):
        self._hide_all()
        getattr(self, section_name).setVisible(True)

    # -- Navigation logic ------------------------------------------------------

    def _pick_os(self, os_key):
        self._selected_os = os_key
        cfg.set_os_type(os_key)
        if os_key in ("bazzite", "cachyos"):
            # Non-SteamOS users go straight to device picker
            self._show("_device_section")
        else:
            self._show("_model_section")

    def _back_to_os(self):
        self._show("_os_section")

    def _pick_device(self, dev_key):
        self._selected_device = dev_key
        dev = DEVICES[dev_key]
        self._is_general_pc = (dev_key == "general_pc")
        self._is_steam_machine = (dev_key == "steam_machine")

        # Save device config
        cfg.set_deck_model(dev["deck_model"])
        if dev["other_device"]:
            cfg.set_other_device(dev["other_device"])
        if dev["other_device_type"]:
            cfg.set_other_device_type(dev["other_device_type"])

        # Next: gyro (if device has it) or name
        if dev["has_gyro"]:
            self._show("_gyro_section")
        else:
            cfg.set_gyro_mode("off")
            self._show_name_section()

    def _show_device_picker(self):
        self._show("_device_section")

    def _back_to_model(self):
        if self._selected_os in ("bazzite", "cachyos"):
            # Non-SteamOS users skipped the model screen - go back to OS
            self._show("_os_section")
        else:
            self._show("_model_section")

    def _back_to_device_from_gyro(self):
        dev = DEVICES.get(self._selected_device, {})
        if self._selected_os in ("bazzite", "cachyos"):
            self._show("_device_section")
        elif dev.get("deck_model") in ("lcd", "oled", "steam_machine"):
            self._show("_model_section")
        else:
            self._show("_device_section")

    def _pick_gyro(self, mode):
        cfg.set_gyro_mode(mode)
        self._show_name_section()

    def _back_to_gyro_from_name(self):
        dev = DEVICES.get(self._selected_device, {})
        if not dev.get("has_gyro"):
            # No gyro section to go back to, go to device
            self._back_to_device_from_gyro()
            return
        self._show("_gyro_section")

    def _show_name_section(self):
        """Show the player name input, pre-filled with Steam display name."""
        if not self._name_input.text():
            saved = cfg.get_player_name()
            if saved:
                self._name_input.setText(saved)
            else:
                steam_name = cfg.get_steam_display_name()
                if steam_name:
                    self._name_input.setText(steam_name)
        self._show("_name_section")

    def _save_player_name(self):
        name = self._name_input.text().strip()
        cfg.set_player_name(name if name else "Player")
        # Steam Machine and General PC need resolution
        if self._is_steam_machine or self._is_general_pc:
            self._show("_resolution_section")
        else:
            self._finish()

    def _back_to_name_from_res(self):
        self._show("_name_section")

    def _pick_resolution(self, resolution):
        if self._is_steam_machine:
            # Steam Machine: store resolution in other_device for config dir
            cfg.set_other_device(resolution)
        else:
            cfg.set_docked_resolution(resolution)
        self._finish()

    # -- Finish ----------------------------------------------------------------

    def _finish(self):
        """Route to the game scan screen. Always own-game."""
        go_to(self.stack, "OwnScanScreen")
