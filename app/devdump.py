"""Dump the live widget tree with on-screen coordinates — "eyes" for an AI.

One call writes EVERY window of the app — the main window plus every Toplevel
(settings, acronym dictionary, chip-style picker, update dialog). Windows that
are not currently open are created OFF-SCREEN, dumped, then closed again, so the
map is complete without disturbing what the user sees. Every CTkTabview is
walked tab by tab so hidden tab contents are captured too.

Coordinates: x/y relative to the parent, w/h size, X/Y absolute on screen.
"""

from __future__ import annotations

import time
from pathlib import Path

DUMP_PATH = Path.home() / ".bonjour-epta" / f"ui-dump-{time.strftime('%Y%m%d-%H%M%S')}.txt"


def _text_of(w) -> str:
    for key in ("text", "placeholder_text"):
        try:
            v = w.cget(key)
            if v:
                return str(v).replace("\n", "\\n")[:60]
        except Exception:  # noqa: BLE001
            pass
    return ""


def _walk(w, depth: int, lines: list[str]) -> None:
    try:
        x = int(w.winfo_x())
        y = int(w.winfo_y())
        ww = int(w.winfo_width())
        wh = int(w.winfo_height())
    except Exception:  # noqa: BLE001
        x = y = ww = wh = 0
    try:
        rx = int(w.winfo_rootx())
        ry = int(w.winfo_rooty())
    except Exception:  # noqa: BLE001
        rx = ry = 0
    cls = type(w).__name__
    txt = _text_of(w)
    label = f' "{txt}"' if txt else ""
    lines.append(f"{'  ' * depth}{cls}{label}  x={x} y={y} w={ww} h={wh}  X={rx} Y={ry}")
    try:
        children = w.winfo_children()
    except Exception:  # noqa: BLE001
        children = []
    for ch in children:
        _walk(ch, depth + 1, lines)


def _dump_tabview(tv, depth: int, lines: list[str]) -> None:
    """Walk a CTkTabview tab by tab so hidden tab contents are captured."""
    try:
        names = list(getattr(tv, "_name_list", []) or [])
    except Exception:  # noqa: BLE001
        names = []
    if not names:
        _walk(tv, depth, lines)
        return
    try:
        current = tv.get()
    except Exception:  # noqa: BLE001
        current = ""
    lines.append(f"{'  ' * depth}CTkTabview  tabs={names}")
    for name in names:
        try:
            tv.set(name)
            tv.update_idletasks()
        except Exception:  # noqa: BLE001
            pass
        lines.append(f"{'  ' * (depth + 1)}--- TAB {name!r} ---")
        try:
            frame = tv.tab(name)
        except Exception:  # noqa: BLE001
            frame = None
        if frame is not None:
            for ch in frame.winfo_children():
                _walk(ch, depth + 2, lines)
    try:
        if current:
            tv.set(current)
    except Exception:  # noqa: BLE001
        pass


def _offscreen(win) -> None:
    try:
        win.geometry("+-9999+-9999")
    except Exception:  # noqa: BLE001
        pass


def _pump(app, ms: int = 120) -> None:
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            app.update()
        except Exception:  # noqa: BLE001
            break
        time.sleep(0.01)


def dump_all(app, path: Path | None = None) -> Path:
    """Open every window off-screen, dump all of them (and every tab), close them."""
    out = path or DUMP_PATH
    opened = []  # windows we created and must close afterwards

    # ── make sure every known window exists ─────────────────────────────
    try:
        if getattr(app, "_settings_win", None) is None or not app._settings_win.winfo_exists():
            from .settings_ui import SettingsWindow

            win = SettingsWindow(app)
            _offscreen(win)
            opened.append(win)
            app._settings_win = win
    except Exception:  # noqa: BLE001
        pass

    try:
        if getattr(app, "_acro_win", None) is None or not app._acro_win.winfo_exists():
            from .acro_window import AcroWindow

            win = AcroWindow(app, term="", on_changed=lambda: None)
            _offscreen(win)
            opened.append(win)
            app._acro_win = win
    except Exception:  # noqa: BLE001
        pass

    try:
        if getattr(app, "_style_win", None) is None or not app._style_win.winfo_exists():
            from .style_picker import StylePickerWindow

            win = StylePickerWindow(app, on_saved=lambda _sid: None)
            _offscreen(win)
            opened.append(win)
            app._style_win = win
    except Exception:  # noqa: BLE001
        pass

    # update dialog — modal, so build it but never grab; off-screen, then destroy
    upd = None
    try:
        from . import update_ui

        info = {
            "version": "X.Y.Z",
            "url": "https://example/BonjourLauncher.exe",
            "notes": "- пример строки заметок",
            "date": "2026-01-01",
        }
        upd = update_ui.UpdateDialog(app, info, "0.0.0")
        _offscreen(upd)
        opened.append(upd)
    except Exception:  # noqa: BLE001
        pass

    _pump(app, 150)

    # ── write the dump ──────────────────────────────────────────────────
    lines = [
        f"# UI dump {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "# coords: x/y = relative to parent, w/h = size, X/Y = absolute on screen",
        "",
    ]
    try:
        lines.append(f"# screen: {int(app.winfo_screenwidth())}x{int(app.winfo_screenheight())}")
        lines.append("")
    except Exception:  # noqa: BLE001
        pass

    windows = [app, *opened]
    for top in windows:
        try:
            top.update_idletasks()
        except Exception:  # noqa: BLE001
            continue
        try:
            title = top.title() if hasattr(top, "title") else ""
            state = top.state() if hasattr(top, "state") else ""
            geom = top.geometry() if hasattr(top, "geometry") else ""
        except Exception:  # noqa: BLE001
            title = state = geom = ""
        lines.append(f"=== WINDOW {type(top).__name__} title={title!r} state={state} geom={geom} ===")
        # dump children; expand any CTkTabview we find along the way
        for ch in top.winfo_children():
            _dump_widget(ch, 0, lines)
        lines.append("")

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    # ── close what we opened ────────────────────────────────────────────
    for win in opened:
        try:
            if win is upd:
                win._done("later")
            else:
                win.destroy()
        except Exception:  # noqa: BLE001
            pass
    try:
        app._settings_win = None
        app._acro_win = None
        app._style_win = None
    except Exception:  # noqa: BLE001
        pass
    return out


def _dump_widget(w, depth: int, lines: list[str]) -> None:
    """Walk a widget; if it is a CTkTabview, expand every tab."""
    try:
        import customtkinter as ctk

        is_tabview = isinstance(w, ctk.CTkTabview)
    except Exception:  # noqa: BLE001
        is_tabview = False
    if is_tabview:
        _dump_tabview(w, depth, lines)
        return
    _walk_one(w, depth, lines)


def _walk_one(w, depth: int, lines: list[str]) -> None:
    try:
        x = int(w.winfo_x())
        y = int(w.winfo_y())
        ww = int(w.winfo_width())
        wh = int(w.winfo_height())
    except Exception:  # noqa: BLE001
        x = y = ww = wh = 0
    try:
        rx = int(w.winfo_rootx())
        ry = int(w.winfo_rooty())
    except Exception:  # noqa: BLE001
        rx = ry = 0
    cls = type(w).__name__
    txt = _text_of(w)
    label = f' "{txt}"' if txt else ""
    lines.append(f"{'  ' * depth}{cls}{label}  x={x} y={y} w={ww} h={wh}  X={rx} Y={ry}")
    try:
        children = w.winfo_children()
    except Exception:  # noqa: BLE001
        children = []
    for ch in children:
        _dump_widget(ch, depth + 1, lines)


def dump_window(win, path: Path | None = None) -> Path:
    """Backwards-compatible entry: dump the whole app that owns `win`."""
    try:
        app = win.winfo_toplevel()
        while getattr(app, "master", None) is not None:
            app = app.master
    except Exception:  # noqa: BLE001
        app = win
    return dump_all(app, path)