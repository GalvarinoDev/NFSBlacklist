"""
ui_manage.py - Post-install management screens for NFSBlacklist

Screens: ManagementScreen, SetupCompleteScreen, ConfigureScreen,
         AboutScreen, LogViewerScreen, UpdateScreen
"""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSlider, QPlainTextEdit, QMessageBox,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QPainter, QLinearGradient, QColor, QBrush

import config as cfg
from identity import APP_TITLE, INSTALL_DIR, GITHUB_USER, GITHUB_REPO
from ui_constants import (
    C_BG, C_CARD, C_ACCENT1, C_ACCENT2, C_DIM, C_DARK_BTN, C_RED_BTN,
    font, _btn, _lbl, _title_block, _wordmark,
    ALL_GAMES, LOG_PATH, HEROES_DIR,
    go_to, get_screen,
    _set_audio_volume, _set_audio_enabled,
    _start_audio, _kill_audio,
)


# -- Hero image helper --------------------------------------------------------

def _hero_path(key: str) -> str:
    """Return the path to the hero image for a game key."""
    # Try png first, then jpg
    for ext in ("png", "jpg"):
        path = os.path.join(HEROES_DIR, f"{key}_hero.{ext}")
        if os.path.exists(path):
            return path
    return ""


# -- SetupCompleteScreen -------------------------------------------------------

class SetupCompleteScreen(QWidget):
    """
    Shown at the end of the install pipeline (after OwnInstallScreen).
    Simple completion message with two buttons: Launch Steam or go to My Games.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "SetupCompleteScreen"
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        content = QWidget()
        clay = QVBoxLayout(content); clay.setContentsMargins(60, 40, 60, 40); clay.setSpacing(20)

        _title_block(clay, main_size=36)
        clay.addSpacing(16)

        msg = _lbl(
            "All set! Your games are ready to play.",
            size=16, color=C_DIM, bold=False
        )
        clay.addWidget(msg)

        clay.addSpacing(32)

        # Button group
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()

        launch_btn = _btn("Launch Steam", C_ACCENT1, size=13, h=52)
        launch_btn.setFixedWidth(220)
        launch_btn.clicked.connect(self._launch_steam)
        btn_lay.addWidget(launch_btn)

        btn_lay.addSpacing(16)

        games_btn = _btn("Go to My Games", C_DARK_BTN, size=13, h=52)
        games_btn.setFixedWidth(220)
        games_btn.clicked.connect(self._go_management)
        btn_lay.addWidget(games_btn)

        btn_lay.addStretch()
        clay.addLayout(btn_lay)

        clay.addStretch()
        lay.addWidget(content, stretch=1)

    def _launch_steam(self):
        """Restart Steam so shortcuts and compat tool changes take effect."""
        os.system("gtk-launch steam.desktop &")

    def _go_management(self):
        """Route to ManagementScreen."""
        go_to(self.stack, "ManagementScreen")


# -- HeroCard -----------------------------------------------------------------

class _HeroCard(QWidget):
    """
    Game card with a hero image background. The image is drawn scaled to
    fill the card width with a dark gradient overlay from bottom to top
    so text on the lower portion stays readable.

    Falls back to a plain dark card if no hero image is available.
    """
    def __init__(self, pixmap=None):
        super().__init__()
        self._pixmap = pixmap
        self.setMinimumHeight(140)
        if not pixmap:
            # No image - use standard card background
            self.setStyleSheet(
                f"QWidget {{ background: {C_CARD}; border-radius: 8px; "
                f"border: 1px solid rgba(255,255,255,0.12); }}"
            )

    def paintEvent(self, event):
        if not self._pixmap:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = self.width(), self.height()

        # Scale image to fill card width, crop vertically from center
        scaled = self._pixmap.scaledToWidth(w, Qt.SmoothTransformation)
        src_h = scaled.height()
        # Center crop vertically
        y_offset = max(0, (src_h - h) // 2)
        painter.drawPixmap(0, 0, scaled, 0, y_offset, w, h)

        # Dark gradient overlay - heavier at bottom for text readability
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0.0, QColor(10, 14, 23, 120))   # light tint at top
        gradient.setColorAt(0.4, QColor(10, 14, 23, 160))   # mid
        gradient.setColorAt(1.0, QColor(10, 14, 23, 230))   # heavy at bottom
        painter.fillRect(0, 0, w, h, QBrush(gradient))

        # Rounded corners via clipping would need more work, so we draw
        # a thin border to match the other cards visually
        painter.setPen(QColor(255, 255, 255, 20))
        painter.drawRoundedRect(0, 0, w - 1, h - 1, 8, 8)

        painter.end()


# -- ManagementScreen ---------------------------------------------------------

class ManagementScreen(QWidget):
    """
    Post-install home. Shows 4 game cards in a 2x2 grid.
    Each card displays game name, setup status, and a Reinstall button
    with a hero image background when available.

    Cards are rebuilt every time the screen is shown (via showEvent) so
    status badges stay in sync after reinstalls or config changes.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "ManagementScreen"
        self._game_keys = [g["key"] for g in ALL_GAMES]

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        content = QWidget()
        self._clay = QVBoxLayout(content)
        self._clay.setContentsMargins(60, 40, 60, 40)
        self._clay.setSpacing(20)

        _wordmark(self._clay)
        self._clay.addSpacing(8)

        self._clay.addWidget(_lbl("My Games", size=14, color=C_DIM, bold=False))

        # Grid container - holds the game cards, rebuilt on every show
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(16)
        self._grid_layout.setColumnStretch(0, 1)
        self._grid_layout.setColumnStretch(1, 1)
        self._clay.addWidget(self._grid_container, stretch=1)

        # Bottom button row: View Logs | Settings | About
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()

        logs_btn = _btn("View Logs", C_DARK_BTN, size=12, h=44)
        logs_btn.setFixedWidth(130)
        logs_btn.clicked.connect(lambda: go_to(self.stack, "LogViewerScreen"))
        btn_lay.addWidget(logs_btn)
        btn_lay.addSpacing(12)

        settings_btn = _btn("Settings", C_DARK_BTN, size=12, h=44)
        settings_btn.setFixedWidth(130)
        settings_btn.clicked.connect(lambda: go_to(self.stack, "ConfigureScreen"))
        btn_lay.addWidget(settings_btn)
        btn_lay.addSpacing(12)

        about_btn = _btn("About", C_DARK_BTN, size=12, h=44)
        about_btn.setFixedWidth(130)
        about_btn.clicked.connect(lambda: go_to(self.stack, "AboutScreen"))
        btn_lay.addWidget(about_btn)

        btn_lay.addStretch()
        self._clay.addLayout(btn_lay)

        lay.addWidget(content, stretch=1)

        # Pre-load hero pixmaps (once, reused across rebuilds)
        self._hero_pixmaps = {}
        for game in ALL_GAMES:
            key = game["key"]
            path = _hero_path(key)
            if path:
                px = QPixmap(path)
                if not px.isNull():
                    self._hero_pixmaps[key] = px

        # Build cards for the first time
        self._rebuild_cards()

    def showEvent(self, e):
        """Rebuild game cards every time the screen is shown so status
        badges reflect current config (e.g. after a reinstall)."""
        super().showEvent(e)
        # Reload hero images in case bootstrap downloaded them since init
        for game in ALL_GAMES:
            key = game["key"]
            if key not in self._hero_pixmaps:
                path = _hero_path(key)
                if path:
                    px = QPixmap(path)
                    if not px.isNull():
                        self._hero_pixmaps[key] = px
        self._rebuild_cards()

    def _rebuild_cards(self):
        """Clear and recreate all game cards from current config state."""
        # Remove existing cards from the grid
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Build fresh cards
        for i, game in enumerate(ALL_GAMES):
            card = self._make_card(game)
            row, col = divmod(i, 2)
            self._grid_layout.addWidget(card, row, col)

    def _make_card(self, game):
        """Create a single game card widget with hero image background."""
        key = game["key"]
        pixmap = self._hero_pixmaps.get(key)

        card = _HeroCard(pixmap)
        clay = QVBoxLayout(card)
        clay.setContentsMargins(20, 20, 20, 20)
        clay.setSpacing(12)

        # Game name
        name_lbl = _lbl(game["base"], size=15, color="#FFF", bold=True, align=Qt.AlignLeft)
        clay.addWidget(name_lbl)

        # Year
        year_lbl = _lbl(str(game.get("year", "")), size=11, color=C_DIM, align=Qt.AlignLeft)
        clay.addWidget(year_lbl)

        # Status badge
        is_setup = cfg.is_game_setup(key)
        if is_setup:
            badge = QLabel("Installed")
            badge.setFont(font(11, bold=True))
            badge.setStyleSheet(
                f"QLabel {{ color: {C_ACCENT1}; background: rgba(59,125,216,0.25); "
                f"border-radius: 4px; padding: 3px 10px; }}"
            )
            clay.addWidget(badge)
        else:
            not_setup = QLabel("Not installed")
            not_setup.setFont(font(11))
            not_setup.setStyleSheet(
                f"QLabel {{ color: {C_DIM}; background: transparent; }}"
            )
            clay.addWidget(not_setup)

        clay.addStretch()

        # Reinstall button
        reinstall_btn = _btn("Reinstall", C_ACCENT1, size=12, h=40)
        reinstall_btn.clicked.connect(lambda: self._reinstall_game(key))
        clay.addWidget(reinstall_btn)

        return card

    def _reinstall_game(self, key):
        """Unmark the game and route to OwnInstallScreen for reinstall."""
        cfg.unmark_game_setup(key)
        # Tell OwnInstallScreen to route back here instead of SetupCompleteScreen
        install_screen = get_screen(self.stack, "OwnInstallScreen")
        if install_screen:
            install_screen._return_to_management = True
        go_to(self.stack, "OwnScanScreen")


# -- ConfigureScreen ----------------------------------------------------------

class ConfigureScreen(QWidget):
    """
    Settings screen with audio controls, re-run setup option, and reset.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "ConfigureScreen"

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(80, 40, 80, 40)
        clay.setSpacing(20)

        # Back button at top-left
        back_btn = _btn("<- Back", C_DARK_BTN, size=10, h=30)
        back_btn.setFixedWidth(80)
        back_btn.clicked.connect(lambda: go_to(self.stack, "ManagementScreen"))
        brow = QHBoxLayout(); brow.addWidget(back_btn); brow.addStretch()
        clay.addLayout(brow)

        _wordmark(clay)
        clay.addSpacing(8)
        clay.addWidget(_lbl("Settings", size=16, color=C_DIM))
        clay.addSpacing(16)

        # -- Audio section -----------------------------------------------------
        audio_card = self._make_section_card()
        al = QVBoxLayout(audio_card); al.setContentsMargins(24, 20, 24, 20); al.setSpacing(14)

        al.addWidget(_lbl("Audio", size=14, color="#FFF", bold=True, align=Qt.AlignLeft))

        # Music toggle
        self._music_btn = _btn("", C_ACCENT1, size=12, h=40)
        self._music_btn.clicked.connect(self._toggle_music)
        al.addWidget(self._music_btn)

        # Volume slider
        vol_row = QHBoxLayout(); vol_row.setSpacing(12)
        vol_row.addWidget(_lbl("Volume", size=12, color=C_DIM, align=Qt.AlignLeft, wrap=False))
        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setMinimum(0)
        self._vol_slider.setMaximum(100)
        self._vol_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{background:#1e2a3d;height:6px;border-radius:3px;}}"
            f"QSlider::handle:horizontal {{background:{C_ACCENT1};width:16px;margin:-5px 0;"
            f"border-radius:8px;}}"
            f"QSlider::sub-page:horizontal {{background:{C_ACCENT1};border-radius:3px;}}"
        )
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        vol_row.addWidget(self._vol_slider, stretch=1)
        self._vol_label = _lbl("40%", size=12, color=C_DIM, align=Qt.AlignRight, wrap=False)
        self._vol_label.setFixedWidth(40)
        vol_row.addWidget(self._vol_label)
        al.addLayout(vol_row)

        clay.addWidget(audio_card)

        # -- Setup section -----------------------------------------------------
        setup_card = self._make_section_card()
        sl = QVBoxLayout(setup_card); sl.setContentsMargins(24, 20, 24, 20); sl.setSpacing(14)

        sl.addWidget(_lbl("Setup", size=14, color="#FFF", bold=True, align=Qt.AlignLeft))
        sl.addWidget(_lbl(
            "Re-run the first-time setup wizard to change your device "
            "or OS.",
            size=12, color=C_DIM, align=Qt.AlignLeft))

        rerun_btn = _btn("Re-run Setup", C_DARK_BTN, size=12, h=44)
        rerun_btn.setFixedWidth(200)
        rerun_btn.clicked.connect(self._rerun_setup)
        sl.addWidget(rerun_btn)

        clay.addWidget(setup_card)

        # -- Danger zone -------------------------------------------------------
        danger_card = self._make_section_card()
        dl = QVBoxLayout(danger_card); dl.setContentsMargins(24, 20, 24, 20); dl.setSpacing(14)

        dl.addWidget(_lbl("Danger Zone", size=14, color=C_RED_BTN, bold=True, align=Qt.AlignLeft))
        dl.addWidget(_lbl(
            "Reset all settings and start fresh. This does not remove "
            "installed mods or game files.",
            size=12, color=C_DIM, align=Qt.AlignLeft))

        reset_btn = _btn("Reset Config", C_RED_BTN, size=12, h=44)
        reset_btn.setFixedWidth(200)
        reset_btn.clicked.connect(self._reset_config)
        dl.addWidget(reset_btn)

        clay.addWidget(danger_card)

        clay.addStretch()
        lay.addWidget(content, stretch=1)

    def showEvent(self, e):
        """Refresh controls to reflect current config when screen is shown."""
        super().showEvent(e)
        enabled = cfg.get_music_enabled()
        self._music_btn.setText("Music: On" if enabled else "Music: Off")
        self._music_btn.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT1 if enabled else C_DARK_BTN};"
            f"color:#FFF;border:none;border-radius:8px;padding:0 18px;}}"
            f"QPushButton:hover{{background:{C_ACCENT1 if enabled else C_DARK_BTN}CC;}}"
        )
        vol = int(cfg.get_music_volume() * 100)
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(vol)
        self._vol_slider.blockSignals(False)
        self._vol_label.setText(f"{vol}%")

    def _make_section_card(self):
        """Create a styled card container for a settings section."""
        card = QWidget()
        card.setStyleSheet(
            f"QWidget {{ background: {C_CARD}; border-radius: 8px; "
            f"border: 1px solid rgba(255,255,255,0.12); }}"
        )
        return card

    def _toggle_music(self):
        enabled = cfg.get_music_enabled()
        new_state = not enabled
        _set_audio_enabled(new_state)
        if new_state:
            _start_audio()
        else:
            _kill_audio()
        # Refresh button appearance
        self._music_btn.setText("Music: On" if new_state else "Music: Off")
        self._music_btn.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT1 if new_state else C_DARK_BTN};"
            f"color:#FFF;border:none;border-radius:8px;padding:0 18px;}}"
            f"QPushButton:hover{{background:{C_ACCENT1 if new_state else C_DARK_BTN}CC;}}"
        )

    def _on_volume_changed(self, value):
        vol = value / 100.0
        _set_audio_volume(vol)
        self._vol_label.setText(f"{value}%")

    def _rerun_setup(self):
        reply = QMessageBox.question(
            self, "Re-run Setup",
            "This will take you through the setup wizard again.\n"
            "Your installed games and mods will not be affected.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            c = cfg.load()
            c["first_run_complete"] = False
            cfg.save(c)
            go_to(self.stack, "SetupFlowScreen")

    def _reset_config(self):
        reply = QMessageBox.warning(
            self, "Reset Config",
            "This will erase all NFSBlacklist settings and return to "
            "the first-run setup.\n\n"
            "Installed mods and game files are NOT removed.\n\n"
            "Are you sure?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            cfg.reset()
            go_to(self.stack, "SetupFlowScreen")


# -- AboutScreen --------------------------------------------------------------

class AboutScreen(QWidget):
    """
    Shows build info, version, GitHub link, and license.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "AboutScreen"

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(80, 40, 80, 40)
        clay.setSpacing(20)

        # Back button
        back_btn = _btn("<- Back", C_DARK_BTN, size=10, h=30)
        back_btn.setFixedWidth(80)
        back_btn.clicked.connect(lambda: go_to(self.stack, "ManagementScreen"))
        brow = QHBoxLayout(); brow.addWidget(back_btn); brow.addStretch()
        clay.addLayout(brow)

        _wordmark(clay)
        clay.addSpacing(16)
        build_info = self._read_build_file()
        clay.addWidget(_lbl(f"Build: {build_info}", size=13, color=C_DIM))

        clay.addSpacing(8)

        # Info card
        info_card = QWidget()
        info_card.setStyleSheet(
            f"QWidget {{ background: {C_CARD}; border-radius: 8px; "
            f"border: 1px solid rgba(255,255,255,0.12); }}"
        )
        il = QVBoxLayout(info_card); il.setContentsMargins(24, 20, 24, 20); il.setSpacing(12)

        il.addWidget(_lbl(
            "NFSBlacklist automates setup of classic EA Black Box "
            "Need for Speed titles on Steam Deck and Linux handhelds.",
            size=13, color="#CCC", align=Qt.AlignLeft))

        il.addWidget(_lbl(
            f"GitHub: {GITHUB_USER}/{GITHUB_REPO}",
            size=12, color=C_ACCENT1, align=Qt.AlignLeft))

        il.addWidget(_lbl("License: MIT", size=12, color=C_DIM, align=Qt.AlignLeft))

        il.addWidget(_lbl(
            "Widescreen fixes by ThirteenAG, Extra Options by ExOpts Team, "
            "XtendedInput by xan1242. GE-Proton by GloriousEggroll.",
            size=11, color=C_DIM, align=Qt.AlignLeft))

        clay.addWidget(info_card)

        # Device info
        device_card = QWidget()
        device_card.setStyleSheet(
            f"QWidget {{ background: {C_CARD}; border-radius: 8px; "
            f"border: 1px solid rgba(255,255,255,0.12); }}"
        )
        dcl = QVBoxLayout(device_card); dcl.setContentsMargins(24, 20, 24, 20); dcl.setSpacing(8)
        dcl.addWidget(_lbl("Current Config", size=13, color="#FFF", bold=True, align=Qt.AlignLeft))
        self._config_label = _lbl("", size=12, color=C_DIM, align=Qt.AlignLeft)
        dcl.addWidget(self._config_label)
        clay.addWidget(device_card)

        clay.addStretch()
        lay.addWidget(content, stretch=1)

    def showEvent(self, e):
        """Refresh config summary when screen is shown."""
        super().showEvent(e)
        c = cfg.load()
        lines = []
        if c.get("os_type"):
            lines.append(f"OS: {c['os_type']}")
        model = c.get("deck_model")
        if model:
            lines.append(f"Device: {model}")
        other = c.get("other_device")
        if other:
            lines.append(f"Resolution: {other}")
        ge = c.get("ge_proton_version")
        if ge:
            lines.append(f"GE-Proton: {ge}")
        setup = c.get("setup_games", {})
        if setup:
            lines.append(f"Games set up: {len(setup)}")
        self._config_label.setText("\n".join(lines) if lines else "No config yet")

    def _read_build_file(self):
        """Read the BUILD file for build hash and date."""
        build_path = os.path.join(INSTALL_DIR, "BUILD")
        try:
            with open(build_path, "r") as f:
                return f.read().strip()
        except (IOError, OSError):
            return "unknown"


# -- LogViewerScreen ----------------------------------------------------------

class LogViewerScreen(QWidget):
    """
    Read-only view of the install log file. Reloads the log every time
    the screen is shown so it always shows the latest content.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "LogViewerScreen"

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(60, 40, 60, 40)
        clay.setSpacing(16)

        # Back button
        back_btn = _btn("<- Back", C_DARK_BTN, size=10, h=30)
        back_btn.setFixedWidth(80)
        back_btn.clicked.connect(lambda: go_to(self.stack, "ManagementScreen"))
        brow = QHBoxLayout(); brow.addWidget(back_btn); brow.addStretch()
        clay.addLayout(brow)

        _wordmark(clay)
        clay.addSpacing(8)
        clay.addWidget(_lbl("Install Log", size=14, color=C_DIM))

        # Log text area
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(font(10))
        self._log_view.setStyleSheet(
            f"QPlainTextEdit{{color:{C_ACCENT2};background:{C_CARD};"
            f"border:1px solid rgba(255,255,255,0.12);border-radius:8px;"
            f"padding:12px;}}"
        )
        clay.addWidget(self._log_view, stretch=1)

        # Log file path for reference
        clay.addWidget(_lbl(LOG_PATH, size=10, color=C_DIM))

        lay.addWidget(content, stretch=1)

    def showEvent(self, e):
        """Reload log file contents every time the screen is shown."""
        super().showEvent(e)
        try:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self._log_view.setPlainText(content)
            # Scroll to bottom to show most recent entries
            sb = self._log_view.verticalScrollBar()
            sb.setValue(sb.maximum())
        except (IOError, OSError):
            self._log_view.setPlainText("(no log file found)")


# -- UpdateScreen -------------------------------------------------------------

class UpdateScreen(QWidget):
    """
    Update check stub. Shows placeholder message.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "UpdateScreen"
        lay = QVBoxLayout(self); lay.setContentsMargins(80, 80, 80, 80); lay.setSpacing(20)

        _wordmark(lay)
        lay.addSpacing(20)

        msg = _lbl("You are up to date.", size=16, color=C_DIM)
        lay.addWidget(msg)

        lay.addStretch()

        back_btn = _btn("Back", C_DARK_BTN, size=13, h=48)
        back_btn.setFixedWidth(140)
        back_btn.clicked.connect(lambda: go_to(self.stack, "ManagementScreen"))
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_lay.addWidget(back_btn)
        btn_lay.addStretch()
        lay.addLayout(btn_lay)
