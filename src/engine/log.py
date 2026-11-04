"""
log.py - one rotating log for the whole app, with personal data masked

    from engine.log import get_logger
    _log = get_logger(__name__)

Call setup_logging() once from each entry point (main.py, prelaunch.py,
uninstall.py) before other work.

Logs get pasted into public chats and issue trackers, so the Linux user
name, Steam account names and IDs and the device serial are masked on the
way out. Path structure stays readable.
"""

import logging
import os
import re
from logging.handlers import RotatingFileHandler

from identity import APP_ID, LOG_DIR

LOG_PATH = os.path.join(LOG_DIR, "install.log")
_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 3
_FORMAT = "[%(asctime)s] %(name)s  %(levelname)s  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_REDACT = [
    (re.compile(r"(?:/var)?/home/[^/\s'\"]+"), "~"),
    (re.compile(r"([A-Za-z]:\\+)(?:var\\+)?home\\+[^\\\s'\"]+"), r"\1~"),
    (re.compile(r"(/(?:run/)?media/)[^/\s'\"]+"), r"\1<user>"),
    (re.compile(r"(-username\s+)\S+"), r"\1***"),
    (re.compile(r"((?:userdata|Steam Controller Configs)[/\\]+)\d+"), r"\1<uid>"),
    (re.compile(r"\b((?:uid|user) )\d{3,}\b"), r"\1<uid>"),
    (re.compile(r"(configset_)(?!controller_)[^./\s'\"]+(\.vdf)"), r"\1<serial>\2"),
]
_secrets = set()
_done = False


def redact_also(word: str):
    """Mask this exact word in later output (a captured account name). Under 3 chars is ignored."""
    if word and len(word) >= 3:
        _secrets.add(re.escape(word))


def redact(text: str) -> str:
    for pat, rep in _REDACT:
        text = pat.sub(rep, text)
    if _secrets:
        text = re.sub(r"\b(?:" + "|".join(_secrets) + r")\b", "***", text)
    return text


class _Formatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def setup_logging(level: int = logging.DEBUG):
    global _done
    if _done:
        return
    _done = True
    os.makedirs(LOG_DIR, exist_ok=True)
    root = logging.getLogger(APP_ID)
    root.setLevel(level)
    fmt = _Formatter(_FORMAT, datefmt=_DATE_FMT)
    try:
        fh = RotatingFileHandler(LOG_PATH, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
        fh.setLevel(logging.DEBUG); fh.setFormatter(fmt); root.addHandler(fh)
    except OSError:
        pass  # read-only or full disk: stderr only
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO); sh.setFormatter(fmt); root.addHandler(sh)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{APP_ID}.{name.rsplit('.', 1)[-1]}")


def tail_for_report(lines: int = 200, errors: int = 50) -> str:
    """
    Last `lines` log lines, preceded by up to `errors` earlier ERROR lines.
    A long install can push its first failure out of the tail, and that
    first failure is usually the one that matters.
    """
    try:
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            all_lines = f.read().splitlines()
    except OSError:
        return ""
    tail = all_lines[-lines:]
    early = [l for l in all_lines[:-lines] if " ERROR " in l or "✗" in l][-errors:]
    out = (["--- earlier errors ---"] + early + ["--- last lines ---"]) if early else []
    return "\n".join(out + tail)
