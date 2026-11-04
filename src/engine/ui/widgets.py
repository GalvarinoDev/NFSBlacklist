"""
widgets.py - shared widgets, dialogs and the worker-thread bridge

Long work never runs on the UI thread. run_in_thread() starts a plain
Python thread; anything it needs to show goes through Bridge, which runs a
callable on the UI thread and waits for its result (used for the download
Retry / Manual / Skip dialog in the middle of an install).
"""

import threading

from ..qt import *
from .theme import T


def label(text: str = "", name: str = None, wrap: bool = True) -> QLabel:
    l = QLabel(text); l.setWordWrap(wrap)
    if name:
        l.setObjectName(name)
    return l


def button(text: str, on_click=None, kind: str = None, tip: str = None) -> QPushButton:
    b = QPushButton(text); b.setMinimumHeight(44); b.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        b.setObjectName(kind)
    if on_click:
        b.clicked.connect(lambda *_: on_click())
    if tip:
        b.setToolTip(tip)
    return b


def card() -> tuple:
    f = QFrame(); f.setObjectName("card")
    lay = QVBoxLayout(f); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)
    return f, lay


def header(title: str, subtitle: str = "", back=None) -> QWidget:
    w = QWidget(); lay = QHBoxLayout(w); lay.setContentsMargins(0, 0, 0, 8)
    if back:
        lay.addWidget(button("‹ Back", back))
    col = QVBoxLayout(); col.addWidget(label(title, "title"))
    if subtitle:
        col.addWidget(label(subtitle, "subtitle"))
    lay.addLayout(col, 1)
    return w


class Bridge(QObject):
    """Run callables on the UI thread from worker threads and wait for the result."""
    _call = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(self._run)

    def _run(self, job):
        fn, box, ev = job
        try:
            box.append(fn())
        except Exception as ex:
            box.append(ex)
        ev.set()

    def ask(self, fn):
        if threading.current_thread() is threading.main_thread():
            return fn()
        box, ev = [], threading.Event()
        self._call.emit((fn, box, ev))
        ev.wait()
        if isinstance(box[0], Exception):
            raise box[0]
        return box[0]

    def post(self, fn):
        """Run on the UI thread without waiting (progress updates, log lines)."""
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            self._call.emit((fn, [], threading.Event()))


bridge = None


def get_bridge() -> Bridge:
    global bridge
    if bridge is None:
        bridge = Bridge()
    return bridge


def run_in_thread(fn, done=None, failed=None):
    """fn() in a daemon thread; done(result) / failed(exc) back on the UI thread."""
    b = get_bridge()

    def work():
        try:
            r = fn()
            if done:
                b.post(lambda: done(r))
        except Exception as ex:
            if failed:
                b.post(lambda: failed(ex))
            else:
                import traceback
                from ..log import get_logger
                get_logger("ui").error("background task failed\n%s", traceback.format_exc())

    t = threading.Thread(target=work, daemon=True); t.start()
    return t


class LogView(QPlainTextEdit):
    def __init__(self):
        super().__init__(); self.setReadOnly(True); self.setMaximumBlockCount(5000)

    def add(self, line: str):
        self.appendPlainText(line)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


def message(parent, title: str, text: str, buttons: list) -> str:
    """Simple touch-friendly dialog. buttons = labels; returns the label clicked."""
    d = QDialog(parent); d.setWindowTitle(title); d.setMinimumWidth(460)
    lay = QVBoxLayout(d); lay.addWidget(label(f"<b>{title}</b>")); lay.addWidget(label(text))
    row = QHBoxLayout(); out = {"v": buttons[-1]}
    for i, b in enumerate(buttons):
        btn = button(b, kind="primary" if i == 0 else None)
        btn.clicked.connect(lambda _=False, v=b: (out.update(v=v), d.accept()))
        row.addWidget(btn)
    lay.addLayout(row); d.exec()
    return out["v"]


def download_failed_dialog(parent, err) -> tuple:
    """Retry / Manual / Skip for a net.DownloadError. Returns (choice, path)."""
    from ..pipeline import ABORT, MANUAL_FILE, RETRY, SKIP
    import os
    name = os.path.basename(err.dest)
    text = (f"{err.label or name} could not be downloaded.\n\n{err.cause}\n\n"
            f"Manual: open this link in a browser, download the file ({name}), then pick it.\n{err.url}")
    choice = message(parent, "Download failed", text, ["Retry", "Manual", "Skip", "Cancel Install"])
    if choice == "Manual":
        QDesktopServices.openUrl(QUrl(err.url))
        path, _ = QFileDialog.getOpenFileName(parent, f"Pick {name}", os.path.expanduser("~/Downloads"))
        return (MANUAL_FILE, path) if path else (RETRY, None)
    return {"Retry": (RETRY, None), "Skip": (SKIP, None)}.get(choice, (ABORT, None))


def preflight_dialog(parent, checks) -> bool:
    """Show preflight results. Returns True to continue. BLOCK items allow only Back."""
    from ..preflight import BLOCK, OK, worst
    if worst(checks) == OK:
        return True
    colour = {"ok": T["ok"], "warn": T["warn"], "block": T["bad"]}
    text = "<br>".join(f"<span style='color:{colour[c.level]}'>●</span> <b>{c.title}</b><br>{c.detail}" for c in checks)
    btns = ["Back"] if worst(checks) == BLOCK else ["Continue", "Back"]
    return message(parent, "Before you start", text, btns) == "Continue"


def qr_pixmap(text: str, scale: int = 6, xstep: int = 2) -> QPixmap:
    """
    Turn a terminal QR code (half-block characters) into a pixmap. Two rows
    per character: ▀ top, ▄ bottom. xstep 2 for printers that draw each
    module two characters wide (DepotDownloader does).
    """
    rows = [r[::xstep] for r in text.splitlines() if r.strip()]
    w = max((len(r) for r in rows), default=0)
    img = QImage(w * scale, len(rows) * 2 * scale, QImage.Format.Format_RGB32); img.fill(QColor("white"))
    p = QPainter(img)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            top = ch in "█▀"; bottom = ch in "█▄"
            if top:
                p.fillRect(x * scale, y * 2 * scale, scale, scale, QColor("black"))
            if bottom:
                p.fillRect(x * scale, (y * 2 + 1) * scale, scale, scale, QColor("black"))
    p.end()
    return QPixmap.fromImage(img)


def copy_text(text: str):
    """Clipboard that survives the app closing in Game Mode: wl-copy/xclip first, Qt as fallback."""
    import shutil, subprocess
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), timeout=5); return
            except Exception:
                pass
    QApplication.clipboard().setText(text)
