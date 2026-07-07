"""File + stderr logging for copy-paste debug.

Log file: ~/.bonjur-epta/bonjur.log  (also ./bonjur.log in project if writable)
"""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

_CONFIGURED = False
LOG_NAME = "bonjur"


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
        datefmt="%H:%M:%S",
    )

    # always stderr (console window if started from terminal)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(fmt)
    log.addHandler(sh)

    paths: list[Path] = []
    home_dir = Path.home() / ".bonjur-epta"
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        paths.append(home_dir / "bonjur.log")
    except Exception:
        pass
    # project-local fallback (easy to find)
    try:
        root = Path(__file__).resolve().parent.parent
        paths.append(root / "bonjur.log")
    except Exception:
        pass

    for p in paths:
        try:
            fh = logging.FileHandler(p, encoding="utf-8", mode="a")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            log.addHandler(fh)
            log.debug("log file: %s", p)
        except Exception as exc:
            log.warning("cannot open log %s: %s", p, exc)

    _CONFIGURED = True
    log.info("=== bonjur session start ===")
    return log


def get() -> logging.Logger:
    if not _CONFIGURED:
        return setup()
    return logging.getLogger(LOG_NAME)


def exc(msg: str = "error") -> None:
    get().error("%s\n%s", msg, traceback.format_exc())
