"""Configurable global hotkey — double-tap or mod+key (scan-code based)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .win_hotkeys import HotkeySpec

try:
    import keyboard
except ImportError:  # pragma: no cover
    keyboard = None  # type: ignore

OEM3_SCAN = 41
DEFAULT_DOUBLE_MS = 400


class TranslateHotkey:
    """Fires on_fire() when configured gesture matches."""

    def __init__(
        self,
        on_fire: Callable[[], None],
        spec: HotkeySpec | None = None,
        double_ms: int = DEFAULT_DOUBLE_MS,
    ) -> None:
        self.on_fire = on_fire
        self.spec = spec or HotkeySpec()
        self.double_ms = double_ms
        self._last_ts = 0.0
        self._hook = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if keyboard is None:
            raise RuntimeError("package 'keyboard' is not installed")
        self.stop()

        spec = self.spec

        def _handler(event: object) -> None:
            if getattr(event, "event_type", None) != "down":
                return
            try:
                sc = int(getattr(event, "scan_code", -1))
            except Exception:  # noqa: BLE001
                return
            if sc != int(spec.scan_code):
                return

            # read mod state at press
            try:
                ctrl = bool(keyboard.is_pressed("ctrl"))
                shift = bool(keyboard.is_pressed("shift"))
                alt = bool(keyboard.is_pressed("alt"))
                win = bool(keyboard.is_pressed("windows") or keyboard.is_pressed("cmd"))
            except Exception:  # noqa: BLE001
                ctrl = shift = alt = win = False

            if spec.mode == "combo":
                if (
                    ctrl == spec.ctrl
                    and shift == spec.shift
                    and alt == spec.alt
                    and win == spec.win
                ):
                    self._fire()
                return

            # double-tap mode: prefer bare key (no mod required, ignore accidental mod-less only)
            # allow double-tap even if mod held if user configured mods on double (rare)
            if spec.ctrl or spec.shift or spec.alt or spec.win:
                if not (
                    ctrl == spec.ctrl
                    and shift == spec.shift
                    and alt == spec.alt
                    and win == spec.win
                ):
                    return
            now = time.perf_counter()
            with self._lock:
                delta_ms = (now - self._last_ts) * 1000.0
                self._last_ts = now
            if 0 < delta_ms <= self.double_ms:
                with self._lock:
                    self._last_ts = 0.0
                self._fire()

        self._hook = keyboard.hook(_handler, suppress=False)

    def _fire(self) -> None:
        try:
            self.on_fire()
        except Exception:  # noqa: BLE001
            pass

    def reconfigure(self, spec: HotkeySpec) -> None:
        self.spec = spec
        if self._hook is not None:
            self.start()

    def stop(self) -> None:
        if keyboard is None or self._hook is None:
            return
        try:
            keyboard.unhook(self._hook)
        except Exception:  # noqa: BLE001
            pass
        self._hook = None


# backward-compatible alias
DoubleTapHotkey = TranslateHotkey
