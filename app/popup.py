"""Floating «чивобля?» chip near the cursor after text selection."""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

CHIP_BG = "#1a2332"
CHIP_BORDER = "#3d9cf0"
CHIP_TEXT = "#e7ecf3"
CHIP_HOVER = "#2a6aa8"


class ChivoblyaPopup:
    """Tiny always-on-top chip; click runs callback with stored selection."""

    def __init__(self, master: ctk.CTk, on_click: Callable[[str], None]) -> None:
        self._master = master
        self._on_click = on_click
        self._text = ""
        self._win: ctk.CTkToplevel | None = None
        self._hide_after_id: str | None = None
        self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible

    def show(self, text: str, x: int, y: int, auto_hide_ms: int = 4500) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._text = text
        self._ensure_win()
        assert self._win is not None

        # Place slightly below-right of cursor so it doesn't cover the selection end
        px = max(0, x + 14)
        py = max(0, y + 18)
        self._win.geometry(f"+{px}+{py}")
        self._win.deiconify()
        self._win.lift()
        self._win.attributes("-topmost", True)
        self._visible = True

        if self._hide_after_id is not None:
            try:
                self._master.after_cancel(self._hide_after_id)
            except Exception:  # noqa: BLE001
                pass
        self._hide_after_id = self._master.after(auto_hide_ms, self.hide)

    def hide(self) -> None:
        self._visible = False
        if self._hide_after_id is not None:
            try:
                self._master.after_cancel(self._hide_after_id)
            except Exception:  # noqa: BLE001
                pass
            self._hide_after_id = None
        if self._win is not None:
            try:
                self._win.withdraw()
            except Exception:  # noqa: BLE001
                pass

    def destroy(self) -> None:
        self.hide()
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._win = None

    def contains_screen_point(self, x: int, y: int) -> bool:
        if not self._visible or self._win is None:
            return False
        try:
            wx = self._win.winfo_rootx()
            wy = self._win.winfo_rooty()
            ww = self._win.winfo_width()
            wh = self._win.winfo_height()
            return wx <= x <= wx + ww and wy <= y <= wy + wh
        except Exception:  # noqa: BLE001
            return False

    def _ensure_win(self) -> None:
        if self._win is not None:
            return
        win = ctk.CTkToplevel(self._master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(fg_color=CHIP_BG)
        win.withdraw()

        # Border frame
        outer = ctk.CTkFrame(
            win,
            fg_color=CHIP_BG,
            border_width=2,
            border_color=CHIP_BORDER,
            corner_radius=12,
        )
        outer.pack(fill="both", expand=True)

        btn = ctk.CTkButton(
            outer,
            text="чивобля?",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=CHIP_TEXT,
            fg_color=CHIP_BG,
            hover_color=CHIP_HOVER,
            corner_radius=10,
            height=34,
            width=110,
            command=self._clicked,
        )
        btn.pack(padx=4, pady=4)

        # Don't let the chip steal keyboard focus from the source app
        win.bind("<Button-1>", lambda _e: self._clicked())
        self._win = win

    def _clicked(self) -> None:
        text = self._text
        self.hide()
        if text:
            self._on_click(text)
