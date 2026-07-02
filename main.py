#!/usr/bin/env python3
"""Bonjur-epta entrypoint — dual-pane translator + hotkey + «чивобля?»."""

from __future__ import annotations

import sys
import threading
import traceback


def main() -> int:
    from app.hotkey import DoubleTapHotkey
    from app.popup import ChivoblyaPopup
    from app.selection import get_selected_text
    from app.selection_watch import SelectionWatcher
    from app.ui import run_app

    app = run_app()
    hotkey_holder: list[DoubleTapHotkey] = []
    watcher_holder: list[SelectionWatcher] = []

    popup = ChivoblyaPopup(app, on_click=lambda text: app.bring_with_selection(text))

    def point_over_own_ui(x: int, y: int) -> bool:
        if popup.contains_screen_point(x, y):
            return True
        try:
            # winfo_containing only sees Tk widgets of this process
            w = app.winfo_containing(x, y)
            if w is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def on_selection_detected(text: str, x: int, y: int) -> None:
        # marshal to UI thread
        app.after(0, lambda: popup.show(text, x, y))

    def on_double_tap() -> None:
        try:
            popup.hide()
            selected = get_selected_text()
            if not selected:
                app.after(
                    0,
                    lambda: (
                        app.deiconify(),
                        app.lift(),
                        app._status.set("Нет выделения"),
                    ),
                )
                return
            app.bring_with_selection(selected)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def start_hooks() -> None:
        status_bits: list[str] = []
        try:
            hk = DoubleTapHotkey(on_double=on_double_tap)
            hk.start()
            hotkey_holder.append(hk)
            status_bits.append("hotkey ` / ё")
        except Exception as exc:  # noqa: BLE001
            print(f"Hotkey off: {exc}", file=sys.stderr)
            status_bits.append("hotkey off")

        try:
            sw = SelectionWatcher(
                on_selection=on_selection_detected,
                should_ignore=point_over_own_ui,
            )
            sw.start()
            watcher_holder.append(sw)
            status_bits.append("чивобля")
        except Exception as exc:  # noqa: BLE001
            print(f"Selection watch off: {exc}", file=sys.stderr)
            status_bits.append("чивобля off")

        msg = "Готов · " + " · ".join(status_bits)
        app.after(0, lambda: app._status.set(msg))

    threading.Thread(target=start_hooks, daemon=True).start()

    def on_destroy(event=None) -> None:
        # only react to root destroy
        if event is not None and event.widget is not app:
            return
        popup.destroy()
        for hk in hotkey_holder:
            try:
                hk.stop()
            except Exception:  # noqa: BLE001
                pass
        for sw in watcher_holder:
            try:
                sw.stop()
            except Exception:  # noqa: BLE001
                pass

    app.bind("<Destroy>", on_destroy)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
