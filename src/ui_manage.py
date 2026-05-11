"""
ui_manage.py - Post-install management screens for NFSBlacklist

Screens: ManagementScreen, SetupCompleteScreen, ConfigureScreen, UpdateScreen
"""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QMessageBox,
)
from PyQt5.QtCore import Qt

import config as cfg
from ui_constants import (
    C_BG, C_CARD, C_ACCENT1, C_DIM, C_DARK_BTN,
    font, _btn, _lbl, _title_block,
    ALL_GAMES,
    go_to,
)


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


# -- ManagementScreen ---------------------------------------------------------

class ManagementScreen(QWidget):
    """
    Post-install home. Shows 4 game cards in a 2x2 grid.
    Each card displays game name, setup status, and a Reinstall button.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "ManagementScreen"
        self._game_keys = [g["key"] for g in ALL_GAMES]

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        content = QWidget()
        clay = QVBoxLayout(content); clay.setContentsMargins(60, 40, 60, 40); clay.setSpacing(20)

        _title_block(clay, main_size=36)
        clay.addSpacing(8)

        clay.addWidget(_lbl("My Games", size=14, color=C_DIM, bold=False))

        # Game grid (2 cols x 2 rows)
        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        for i, game in enumerate(ALL_GAMES):
            card = self._make_card(game)
            row, col = divmod(i, 2)
            grid.addWidget(card, row, col)

        clay.addLayout(grid, stretch=1)

        # Settings button at bottom
        settings_btn = _btn("Settings", C_DARK_BTN, size=13, h=48)
        settings_btn.setFixedWidth(140)
        settings_btn.clicked.connect(lambda: go_to(self.stack, "ConfigureScreen"))
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_lay.addWidget(settings_btn)
        btn_lay.addStretch()
        clay.addLayout(btn_lay)

        lay.addWidget(content, stretch=1)

    def _make_card(self, game):
        """Create a single game card widget."""
        card = QWidget()
        card.setStyleSheet(
            f"QWidget {{ background: {C_CARD}; border-radius: 8px; "
            f"border: 0.5px solid rgba(255,255,255,0.08); }}"
        )
        clay = QVBoxLayout(card); clay.setContentsMargins(20, 20, 20, 20); clay.setSpacing(12)

        # Game name
        name_lbl = _lbl(game["base"], size=15, color="#FFF", bold=True, align=Qt.AlignLeft)
        clay.addWidget(name_lbl)

        # Status badge
        key = game["key"]
        is_setup = cfg.is_game_setup(key)
        if is_setup:
            badge = QLabel("Installed")
            badge.setFont(font(11, bold=True))
            badge.setStyleSheet(
                f"QLabel {{ color: {C_ACCENT1}; background: rgba(59,125,216,0.15); "
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
        # TODO: Set OwnInstallScreen to pre-select just this game
        # For now, just route there and user will see all detected games
        go_to(self.stack, "OwnScanScreen")


# -- ConfigureScreen ----------------------------------------------------------

class ConfigureScreen(QWidget):
    """
    Settings stub. Shows placeholder message.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "ConfigureScreen"
        lay = QVBoxLayout(self); lay.setContentsMargins(80, 80, 80, 80); lay.setSpacing(20)

        _title_block(lay, main_size=36)
        lay.addSpacing(20)

        msg = _lbl("Settings coming soon.", size=16, color=C_DIM)
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


# -- UpdateScreen -------------------------------------------------------------

class UpdateScreen(QWidget):
    """
    Update check stub. Shows placeholder message.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "UpdateScreen"
        lay = QVBoxLayout(self); lay.setContentsMargins(80, 80, 80, 80); lay.setSpacing(20)

        _title_block(lay, main_size=36)
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
