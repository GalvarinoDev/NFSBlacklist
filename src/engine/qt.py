"""
qt.py - Qt import shim

PyQt6 when the venv has it, else PyQt5. UI code imports Qt from here and
only uses names both accept: fully scoped enums (Qt.AlignmentFlag.AlignLeft),
exec() not exec_(), toggled(bool) not stateChanged(int). The int compare
in stateChanged silently fails on PyQt6.

PyQt5 stays as a fallback: some ARM or old systems get a PyQt6 wheel that
installs but cannot open a window.
"""

try:
    from PyQt6.QtCore import *
    from PyQt6.QtGui import *
    from PyQt6.QtWidgets import *
    QT6 = True
except ImportError:
    from PyQt5.QtCore import *
    from PyQt5.QtGui import *
    from PyQt5.QtWidgets import *
    QT6 = False

# Optional: engine.inhibit treats a missing QtDBus as "no screensaver bus"
try:
    if QT6:
        from PyQt6.QtDBus import *
    else:
        from PyQt5.QtDBus import *
except ImportError:
    pass
