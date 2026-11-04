"""
theme.py - colour tokens, fonts and the app stylesheet

Override any token with identity.THEME = {"accent": "#ff7a00", ...}.
Sizes are for touch: buttons at least 40-44 px tall, smallest text 10 pt,
everything readable at 1280x800 without scrolling where possible.
"""

import identity

TOKENS = {
    "bg": "#121417",
    "panel": "#1c2026",
    "panel_hi": "#252a32",
    "text": "#e8eaed",
    "muted": "#9aa0a6",
    "accent": "#4f8cff",
    "accent_text": "#ffffff",
    "ok": "#3ccf7a",
    "warn": "#f2b33d",
    "bad": "#ef5350",
    "border": "#2f353e",
    "font": "Noto Sans",
    "font_size": 11,
}
TOKENS.update(getattr(identity, "THEME", {}))
T = TOKENS


def stylesheet() -> str:
    t = TOKENS
    return f"""
    QWidget {{ background: {t['bg']}; color: {t['text']}; font-family: "{t['font']}"; font-size: {t['font_size']}pt; }}
    QLabel#title {{ font-size: {t['font_size'] + 9}pt; font-weight: 700; }}
    QLabel#subtitle {{ color: {t['muted']}; font-size: {t['font_size'] + 1}pt; }}
    QLabel#badge {{ background: {t['accent']}; color: {t['accent_text']}; border-radius: 6px; padding: 2px 8px; font-size: 9pt; font-weight: 700; }}
    QFrame#card {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QPushButton {{ background: {t['panel_hi']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 8px 16px; min-height: 28px; }}
    QPushButton:hover, QPushButton:focus {{ border-color: {t['accent']}; }}
    QPushButton:disabled {{ color: {t['muted']}; background: {t['panel']}; }}
    QPushButton#primary {{ background: {t['accent']}; color: {t['accent_text']}; border: none; font-weight: 700; }}
    QPushButton#danger {{ background: {t['bad']}; color: white; border: none; }}
    QCheckBox, QRadioButton {{ spacing: 10px; padding: 6px 0; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 22px; height: 22px; }}
    QLineEdit, QComboBox {{ background: {t['panel_hi']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 8px; min-height: 26px; }}
    QProgressBar {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 8px; height: 22px; text-align: center; }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 7px; }}
    QPlainTextEdit {{ background: #0c0d0f; border: 1px solid {t['border']}; border-radius: 8px; font-family: monospace; font-size: 9pt; }}
    QScrollArea {{ border: none; }}
    QToolTip {{ background: {t['panel_hi']}; color: {t['text']}; border: 1px solid {t['border']}; }}
    """
