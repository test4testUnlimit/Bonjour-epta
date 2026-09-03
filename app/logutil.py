"""File + stderr logging for copy-paste debug.

Log file: ~/.bonjour-epta/bonjour.log  (also ./bonjour.log in project if writable)

Timestamps include the date so BUGMARK lookback across sleep/midnight works.
Rotate when a file exceeds ~8 MiB (keeps *.log.prev).
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

_CONFIGURED = False
LOG_NAME = "bonjur"
_ROTATE_BYTES = 8 * 1024 * 1024

# The app sees every scrap of text the user highlights anywhere on the machine.
# Writing it to disk turns the log into a reading history, so content is opt-in:
# set BONJUR_LOG_TEXT=1 when you need to debug a capture. Lengths always log.
LOG_TEXT = os.environ.get("BONJUR_LOG_TEXT") == "1"


def head(text: str | None, n: int = 100) -> str:
    """First `n` chars for a log line — redacted unless BONJUR_LOG_TEXT=1."""
    if not LOG_TEXT:
        return "<hidden>"
    return (text or "")[:n]


def setup() -> logging.Logger:
    global _CONFIGURED
    log = logging.getLogger(LOG_NAME)
    if _CONFIGURED:
        return log

    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    log.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # always stderr (console window if started from terminal)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(fmt)
    log.addHandler(sh)

    paths: list[Path] = []
    home_dir = Path.home() / ".bonjour-epta"
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        paths.append(home_dir / "bonjour.log")
    except Exception:
        pass
    # project-local fallback (easy to find)
    try:
        root = Path(__file__).resolve().parent.parent
        paths.append(root / "bonjour.log")
    except Exception:
        pass

    for p in paths:
        try:
            _rotate_if_huge(p)
            fh = logging.FileHandler(p, encoding="utf-8", mode="a")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            log.addHandler(fh)
            log.debug("log file: %s", p)
        except Exception as exc:
            log.warning("cannot open log %s: %s", p, exc)

    _CONFIGURED = True
    try:
        from . import theme as T

        ver = T.APP_VERSION
    except Exception:
        ver = "?"
    log.info("=== Bonjour session start ver=%s ===", ver)
    return log


def _rotate_if_huge(path: Path) -> None:
    try:
        if not path.is_file() or path.stat().st_size < _ROTATE_BYTES:
            return
        prev = path.with_suffix(path.suffix + ".prev")
        if prev.exists():
            prev.unlink()
        path.replace(prev)
    except Exception:
        pass


def get() -> logging.Logger:
    if not _CONFIGURED:
        return setup()
    return logging.getLogger(LOG_NAME)


def exc(msg: str = "error") -> None:
    get().error("%s\n%s", msg, traceback.format_exc())
