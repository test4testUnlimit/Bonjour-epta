#!/usr/bin/env python3
"""Bonjur-epta — Crow-style: hotkey → grab selection → open window with text.

Crow default: Ctrl+Alt+E translates selection (no floating chip required).
We keep optional «чивобля?» chip; click uses cached text (no second Ctrl+C).
"""

from __future__ import annotations

import sys
import threading
import traceback

# Kept alive for process lifetime (Win32 single-instance mutex handle).
_INSTANCE_MUTEX = None


def _try_single_instance(startup: bool) -> bool:
    """True = we own the instance. False = another copy already running."""
    global _INSTANCE_MUTEX
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    # ERROR_ALREADY_EXISTS = 183
    _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "Local\\BonjurEpta_SingleInstance_v1")
    if kernel32.GetLastError() == 183:
        return False
    return True


def main() -> int:
    from app import dpi
    from app import logutil
    from app import settings as cfg
    from app.autostart import sync as sync_autostart
    from app.chip_offer import should_offer_chip
    from app.hotkey import TranslateHotkey
    from app.popup import ChivoblyaPopup
    from app.selection import get_selected_text
    from app.selection_watch import SelectionWatcher
    from app.tray import TrayIcon
    from app.ui import run_app
    from app.win_hotkeys import HotkeySpec

    startup = "--startup" in sys.argv
    if not _try_single_instance(startup):
        # Second copy at login → quiet exit. Manual second launch → also exit
        # (tray already owns the session).
        return 0

    dpi_mode = dpi.enable()
    from app.app_icon import set_app_user_model_id

    set_app_user_model_id()  # before any HWND — taskbar uses our icon, not pythonw
    log = logutil.setup()
    log.info("main() start dpi=%s startup=%s", dpi_mode, startup)

    # Prefer Crow default hotkey if still on bare double-OEM3 and user never customized
    # (sanitize already fixed Ctrl+Z). Offer Ctrl+Alt+E as product default for new installs.
    s0 = cfg.load()
    safe = s0.hotkey_spec()
    # migrate only the broken/default double-ё if settings file never set combo
    # keep user's `/ё ×2 if they want — but force-write Crow default for reliability first run
    # Only auto-migrate when hotkey was illegal (already sanitized) or empty dict edge
    if safe.to_dict() != (s0.hotkey or {}):
        log.warning("hotkey sanitized → %s", safe.label())
        cfg.update(hotkey=safe.to_dict())

    ok, err = sync_autostart(s0.autostart)
    if not ok:
        log.warning("autostart sync failed: %s", err)
    elif s0.autostart:
        from app.autostart import registered_command

        log.info("autostart refreshed: %s", registered_command())

    app = run_app()
    if startup:
        # Hide before paint / tray race — after(250) was flaky on slow login.
        try:
            app.withdraw()
        except Exception:  # noqa: BLE001
            pass

    tray = TrayIcon(app)
    app._tray = tray
    tray.start()
    if startup:
        app.after(0, app._minimize)
        app.after(400, app._minimize)
    hotkey_holder: list[TranslateHotkey] = []
    watcher_holder: list[SelectionWatcher] = []
    last_selection: list[str] = [""]

    def on_open_main(text: str) -> None:
        # mini card «в окно» → full dual-pane (Crow-style fill)
        payload = (text or last_selection[0] or "").strip()
        log.info("mini → main len=%s", len(payload))
        if payload:
            app.bring_with_selection(payload)
        else:
            app._status.set("нет текста")

    # track popup visibility; do NOT pause watcher — outside-click dismiss +
    # should_ignore(over chip) keep UX clean, and new selection can replace chip/card
    popup_open = {"on": False}

    def on_popup_vis(on: bool) -> None:
        popup_open["on"] = on

    # Google-style pill; style chosen in «стиль чипа» window (numbered gallery)
    popup = ChivoblyaPopup(
        app,
        on_open_main=on_open_main,
        on_visibility=on_popup_vis,
    )
    app.on_chip_style_changed = lambda _sid: popup.apply_style_now()

    def point_over_own_ui(x: int, y: int) -> bool:
        if popup.contains_screen_point(x, y):
            return True
        try:
            if app.winfo_containing(x, y) is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def on_selection_detected(text: str, x: int, y: int) -> None:
        log.info("selection cache len=%s at=%s,%s head=%r", len(text), x, y, text[:80])
        last_selection[0] = text or ""
        if not cfg.get().chivoblya_enabled:
            return
        s = cfg.get()
        # use UI target if app has it, else settings
        target = getattr(app, "_target_lang", None)
        target_code = target.get() if target is not None else (s.target_lang or "ru")
        if not should_offer_chip(text, target_lang=target_code):
            log.debug(
                "skip chip — not useful for target=%s head=%r",
                target_code,
                (text or "")[:40],
            )
            return

        def show() -> None:
            try:
                popup.show(text, x, y)
            except Exception:  # noqa: BLE001
                logutil.exc("popup.show")

        app.after(0, show)

    def on_hotkey_fire() -> None:
        """Crow path: hotkey → requestSelection → fill window."""
        log.info("HOTKEY FIRE (Crow path) spec=%s", cfg.get().hotkey_spec().label())
        for sw in watcher_holder:
            try:
                sw.pause()
            except Exception:  # noqa: BLE001
                pass
        try:
            try:
                popup.hide()
            except Exception:  # noqa: BLE001
                pass

            # Crow: grab NOW via Ctrl+C (mods must be released — handled inside)
            from app.selection import sanitize_selection

            selected = get_selected_text(
                restore_clipboard=True,
                settle_s=1.5,  # soft; hard cap ~5s while large copy still on marker
                clipboard_fallback=True,
            )
            selected = sanitize_selection(selected)
            log.info(
                "hotkey grab len=%s cache_len=%s head=%r",
                len(selected or ""),
                len(last_selection[0] or ""),
                (selected or "")[:100],
            )
            if not selected and last_selection[0]:
                selected = sanitize_selection(last_selection[0])
                if selected:
                    log.info("hotkey fallback cache len=%s", len(selected))

            if not selected:
                log.warning("hotkey: nothing to translate")
                app.after(
                    0,
                    lambda: (
                        app.deiconify(),
                        app.lift(),
                        app._status.set("нет выделения — выдели текст и нажми хоткей"),
                    ),
                )
                return

            last_selection[0] = selected
            app.bring_with_selection(selected)
        except Exception:  # noqa: BLE001
            logutil.exc("on_hotkey_fire")
            traceback.print_exc()
        finally:
            # delay resume so chip click isn't stolen by watcher
            def resume() -> None:
                for sw in watcher_holder:
                    try:
                        sw.resume()
                    except Exception:  # noqa: BLE001
                        pass

            try:
                app.after(400, resume)
            except Exception:  # noqa: BLE001
                resume()

    def start_hooks() -> None:
        status_bits: list[str] = []
        try:
            hk = TranslateHotkey(on_fire=on_hotkey_fire, spec=cfg.get().hotkey_spec())
            hk.start()
            hotkey_holder.append(hk)
            status_bits.append(cfg.get().hotkey_spec().label())
            log.info("hotkey started: %s", cfg.get().hotkey_spec().label())
        except Exception as exc:  # noqa: BLE001
            logutil.exc("hotkey start failed")
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
            log.info("selection watcher started")
        except Exception as exc:  # noqa: BLE001
            logutil.exc("watcher start failed")
            print(f"Selection watch off: {exc}", file=sys.stderr)
            status_bits.append("чивобля off")

        from pathlib import Path

        log_path = Path.home() / ".bonjur-epta" / "bonjur.log"
        log.info("hooks ready %s log=%s", " · ".join(status_bits), log_path)
        log.info(
            "Crow usage: select text → press hotkey (now %s) → window fills. "
            "Chip click uses cache only.",
            cfg.get().hotkey_spec().label(),
        )

    def on_settings_live(s: cfg.AppSettings) -> None:
        log.info("settings live hotkey=%s", s.hotkey_spec().label())
        for hk in list(hotkey_holder):
            try:
                hk.reconfigure(s.hotkey_spec())
            except Exception:  # noqa: BLE001
                logutil.exc("hotkey reconfig")

    cfg.on_change(on_settings_live)
    threading.Thread(target=start_hooks, daemon=True).start()

    def on_destroy(event=None) -> None:
        if event is not None and event.widget is not app:
            return
        log.info("app destroy")
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
    log.info("entering mainloop")
    app.mainloop()
    log.info("mainloop exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
