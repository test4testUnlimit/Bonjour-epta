"""System tray icon with menu: open / settings / exit.

pystray runs the icon in its own thread; menu callbacks are marshalled back
to the Tk main thread via app.after(0, ...).
"""

from __future__ import annotations

import threading
from typing import Any

from . import app_icon
from . import theme as T


def _load_image():
    """Return a PIL.Image for the tray icon, or None to use pystray fallback."""
    try:
        from PIL import Image

        path = app_icon.find_icon()
        if path is None:
            return None
        img = Image.open(path).convert("RGBA")
        # tray icons render best at 32x32 (or 64 for HiDPI)
        size = 64
        return img.resize((size, size), Image.Resampling.LANCZOS)
    except Exception:  # noqa: BLE001
        return None


class TrayIcon:
    def __init__(self, app: Any) -> None:
        self._app = app
        self._icon = None
        self._lock = threading.Lock()

    def _menu(self):
        import pystray

        def on_open(_icon, _item):
            self._marshal(self._open_window)

        def on_settings(_icon, _item):
            self._marshal(lambda: self._app.open_settings())

        def on_exit(_icon, _item):
            self._marshal(self._quit)

        return pystray.Menu(
            pystray.MenuItem("открыть", on_open, default=True),
            pystray.MenuItem("настройки", on_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("выход", on_exit),
        )

    def _marshal(self, fn) -> None:
        try:
            self._app.after(0, fn)
        except Exception:  # noqa: BLE001
            pass

    def _open_window(self) -> None:
        try:
            show = getattr(self._app, "show_from_tray", None)
            if callable(show):
                show()
            else:
                self._app.deiconify()
                self._app.lift()
                self._app.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def _quit(self) -> None:
        try:
            self.stop()
        finally:
            try:
                self._app._on_close()
            except Exception:  # noqa: BLE001
                try:
                    self._app.destroy()
                except Exception:  # noqa: BLE001
                    pass

    def start(self) -> None:
        with self._lock:
            if self._icon is not None:
                return
            try:
                import pystray

                image = _load_image()
                if image is None:
                    from PIL import Image

                    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                self._icon = pystray.Icon(
                    T.APP_NAME, image, T.APP_NAME, self._menu()
                )
                threading.Thread(
                    target=self._icon.run, daemon=True, name="bonjur-tray"
                ).start()
            except Exception:  # noqa: BLE001
                self._icon = None

    def stop(self) -> None:
        with self._lock:
            icon = self._icon
            self._icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass
