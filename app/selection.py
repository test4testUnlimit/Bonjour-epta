"""Grab currently selected text via clipboard round-trip (Ctrl+C)."""

from __future__ import annotations

import time

import pyperclip

try:
    import keyboard
except ImportError:  # pragma: no cover
    keyboard = None  # type: ignore


def get_selected_text(restore_clipboard: bool = True, settle_s: float = 0.08) -> str:
    """
    Copy active selection with Ctrl+C, read clipboard, optionally restore previous clip.
    Works in most apps/browsers; fails silently for protected fields.
    """
    previous = ""
    try:
        previous = pyperclip.paste()
    except Exception:  # noqa: BLE001
        previous = ""

    # Marker so we can detect "nothing new was copied"
    marker = f"__bonjur_{time.time_ns()}__"
    try:
        pyperclip.copy(marker)
    except Exception:  # noqa: BLE001
        pass

    if keyboard is None:
        return ""

    keyboard.send("ctrl+c")
    time.sleep(settle_s)

    try:
        current = pyperclip.paste()
    except Exception:  # noqa: BLE001
        current = ""

    selected = ""
    if current and current != marker:
        selected = current.strip()

    if restore_clipboard:
        try:
            pyperclip.copy(previous)
        except Exception:  # noqa: BLE001
            pass

    return selected
