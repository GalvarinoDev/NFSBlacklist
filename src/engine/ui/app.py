"""
app.py - main window, screen registry, navigation

The window wraps a QStackedWidget. Screens register by class name and are
reached with go_to(stack, "Name") / get_screen(stack, "Name"), never by
index, so adding a screen never breaks navigation.
"""

import os
import sys

import identity
from .. import config, inhibit
from ..log import get_logger
from ..qt import *
from .theme import T, stylesheet
from .widgets import get_bridge

_log = get_logger("ui")


def go_to(stack: QStackedWidget, name: str):
    w = get_screen(stack, name)
    if hasattr(w, "on_show"):
        w.on_show()
    stack.setCurrentWidget(w)


def get_screen(stack: QStackedWidget, name: str):
    return stack.screens[name]


class Window(QMainWindow):
    def __init__(self, screens: list):
        super().__init__()
        self.setWindowTitle(identity.APP_TITLE)
        icon = os.path.join(identity.PROJECT_ROOT, "assets", "images", "icon.png")
        if os.path.isfile(icon):
            self.setWindowIcon(QIcon(icon))
        self.stack = QStackedWidget(); self.stack.screens = {}
        for cls in screens:
            w = cls(self.stack)
            self.stack.screens[cls.__name__] = w
            self.stack.addWidget(w)
        self.setCentralWidget(self.stack)
        self.resize(1280, 800)

    def closeEvent(self, e):
        inhibit.stop()
        super().closeEvent(e)


_player = None


def music(on: bool = None):
    """
    Loop assets/music/background.mp3 while the app runs (config music_enabled).
    PyQt6 only: Qt Multimedia on PyQt5 needs system codecs that are often missing.
    """
    global _player
    on = config.get("music_enabled", True) if on is None else on
    path = os.path.join(identity.PROJECT_ROOT, "assets", "music", "background.mp3")
    if _player is None:
        if not on or not QT6 or not os.path.isfile(path):
            return
        try:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return
        _player = QMediaPlayer(); out = QAudioOutput(); out.setVolume(float(config.get("music_volume", 0.4)))
        _player.setAudioOutput(out); _player._out = out
        _player.setSource(QUrl.fromLocalFile(path)); _player.setLoops(QMediaPlayer.Loops.Infinite)
    _player.play() if on else _player.pause()


def run(extra_screens: list = (), first: str = "BootstrapScreen"):
    from . import screens as s
    app = QApplication(sys.argv)
    app.setApplicationName(identity.APP_TITLE); app.setStyle("Fusion"); app.setStyleSheet(stylesheet())
    font_dir = os.path.join(identity.PROJECT_ROOT, "assets", "fonts")
    if os.path.isdir(font_dir):
        for f in os.listdir(font_dir):
            if f.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(font_dir, f))
    get_bridge()  # created on the UI thread
    all_screens = [s.BootstrapScreen, s.SetupScreen, s.GamesScreen, s.InstallScreen,
                   s.ManageScreen, s.SettingsScreen, s.UpdateScreen, *extra_screens]
    win = Window(all_screens)
    go_to(win.stack, first)
    win.showMaximized()
    music()
    sys.exit(app.exec())
