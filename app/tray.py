"""System tray icon with menu: open / settings / report-a-bug / exit.

pystray runs the icon in its own thread; menu callbacks are marshalled back
to the Tk main thread via app.after(0, ...).
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Any

from . import app_icon
from . import bug_report
from . import theme as T


def _repro_html_path() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "assets" / "repro-field-bugs.html",
        here.parent / "repro-field-bugs.html",
        here.parent / "notes" / "repro-field-bugs.html",
        here.parent / "release" / "repro-field-bugs.html",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _load_image():
    """Return a PIL.Image for the tray icon — same artwork as window/taskbar."""
    img = app_icon.load_tray_image()
    if img is not None:
        return img
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

        def on_repro(_icon, _item):
            self._marshal(self._open_repro)

        def on_bug_extra(_icon, _item):
            self._marshal(lambda: bug_report.report(bug_report.KIND_EXTRA_S, app=self._app))

        def on_bug_chip(_icon, _item):
            self._marshal(lambda: bug_report.report(bug_report.KIND_NO_CHIP, app=self._app))

        def on_bug_describe(_icon, _item):
            self._marshal(lambda: bug_report.open_describe(self._app))

        def on_restart(_icon, _item):
            self._marshal(lambda: self._app._restart_client())

        def on_exit(_icon, _item):
            self._marshal(self._quit)

        bug_menu = pystray.Menu(
            pystray.MenuItem("дополнительная «с»", on_bug_extra),
            pystray.MenuItem("нет чипа при выделении", on_bug_chip),
            pystray.MenuItem("описать…", on_bug_describe),
        )

        return pystray.Menu(
            pystray.MenuItem("открыть", on_open, default=True),
            pystray.MenuItem("настройки", on_settings),
            pystray.MenuItem("страница повтора багов", on_repro),
            pystray.MenuItem("был баг", bug_menu),
            pystray.Menu.SEPARATOR,
            # The title-bar ↻ now checks for updates, so restart moved here.
            pystray.MenuItem("перезапустить", on_restart),
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

    def _open_repro(self) -> None:
        path = _repro_html_path()
        if path is None:
            try:
                st = getattr(self._app, "_status", None)
                if st is not None:
                    st.set("нет repro-field-bugs.html")
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            webbrowser.open(path.resolve().as_uri())
        except Exception:  # noqa: BLE001
            from . import logutil

            logutil.exc("open repro html")

    def _quit(self) -> None:
        """Tray exit always fully quits (bypasses close-to-tray)."""
        try:
            self.stop()
        finally:
            try:
                self._app._on_close(force=True)
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
