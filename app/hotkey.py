"""Global double-tap of physical key ` / ё (layout-independent scan code).

VK_OEM_3 / scan code 0x29 (41) is the key left of 1 on standard PC keyboards:
- EN: ` ~
- RU: ё Ё
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

try:
    import keyboard
except ImportError:  # pragma: no cover
    keyboard = None  # type: ignore

# PS/2 / USB HID scan code for the key left of "1"
OEM3_SCAN = 41
DEFAULT_DOUBLE_MS = 380


class DoubleTapHotkey:
    def __init__(
        self,
        on_double: Callable[[], None],
        double_ms: int = DEFAULT_DOUBLE_MS,
        scan_code: int = OEM3_SCAN,
    ) -> None:
        self.on_double = on_double
        self.double_ms = double_ms
        self.scan_code = scan_code
        self._last_ts = 0.0
        self._hook = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if keyboard is None:
            raise RuntimeError("package 'keyboard' is not installed")
        if self._hook is not None:
            return

        def _handler(event: object) -> None:
            # keyboard.KeyboardEvent
            if getattr(event, "event_type", None) != "down":
                return
            if int(getattr(event, "scan_code", -1)) != self.scan_code:
                return
            now = time.perf_counter()
            with self._lock:
                delta_ms = (now - self._last_ts) * 1000.0
                self._last_ts = now
            if 0 < delta_ms <= self.double_ms:
                # reset so triple-tap doesn't fire twice
                with self._lock:
                    self._last_ts = 0.0
                try:
                    self.on_double()
                except Exception:  # noqa: BLE001 — never kill hook thread
                    pass

        self._hook = keyboard.hook(_handler, suppress=False)

    def stop(self) -> None:
        if keyboard is None or self._hook is None:
            return
        try:
            keyboard.unhook(self._hook)
        except Exception:  # noqa: BLE001
            pass
        self._hook = None
