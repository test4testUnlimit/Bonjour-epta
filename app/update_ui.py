"""The update dialog — release notes, not a bare MsgBox.

Kept apart from updater.py so the update logic stays importable (and testable)
without a display.
"""

from __future__ import annotations

import tkinter as tk

from . import theme as T
from .screen import center_on_screen
from .updater import format_notes


class UpdateDialog(tk.Toplevel):
    """Returns ('update' | 'later', skip_this_version) via .result after wait_window."""

    def __init__(self, master: tk.Misc, info: dict, local_version: str) -> None:
        super().__init__(master)
        self.title(T.APP_NAME)
        self.configure(bg=T.BG)
        self.geometry("560x480")
        self.resizable(False, False)
        self.transient(master)
        self.result: tuple[str, bool] = ("later", False)
        self._skip = tk.BooleanVar(value=False)

        tk.Label(
            self,
            text=f"Доступна версия {info.get('version', '')}",
            font=(T.FONT_UI, 15),
            fg=T.INK,
            bg=T.BG,
        ).pack(anchor="w", padx=20, pady=(18, 2))

        date = str(info.get("date") or "")
        if date:
            tk.Label(
                self, text=date, font=(T.FONT_UI, 9), fg=T.INK_FAINT, bg=T.BG
            ).pack(anchor="w", padx=20)

        body = format_notes(info.get("notes", "")) or "Описание к этой версии не опубликовано."
        # The buttons must be packed BEFORE the greedy notes box: pack hands out
        # space in call order, so an expand=True widget packed first leaves the
        # footer zero height and the «обновить» button simply disappears.
        self._foot = tk.Frame(self, bg=T.BG)
        self._foot.pack(side="bottom", fill="x", padx=20, pady=(6, 16))
        self._skiprow = tk.Frame(self, bg=T.BG)
        self._skiprow.pack(side="bottom", fill="x", padx=18, pady=(0, 2))

        wrap = tk.Frame(self, bg=T.BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=(10, 6))
        scroll = tk.Scrollbar(wrap, orient="vertical")
        scroll.pack(side="right", fill="y")
        text = tk.Text(
            wrap,
            wrap="word",
            font=(T.FONT_UI, 10),
            fg=T.INK,
            bg=T.READ_BG,
            relief="flat",
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=T.LINE,
            yscrollcommand=scroll.set,
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.config(command=text.yview)
        text.insert("1.0", body)
        text.configure(state="disabled")

        tk.Checkbutton(
            self._skiprow,
            text="пропустить эту версию",
            variable=self._skip,
            font=(T.FONT_UI, 9),
            fg=T.INK_SOFT,
            bg=T.BG,
            activebackground=T.BG,
            activeforeground=T.INK,
            selectcolor=T.BG,
            highlightthickness=0,
            bd=0,
        ).pack(anchor="w")

        foot = self._foot
        tk.Label(
            foot,
            text=f"у вас {local_version}",
            font=(T.FONT_UI, 9),
            fg=T.INK_FAINT,
            bg=T.BG,
        ).pack(side="left")
        tk.Button(
            foot,
            text="обновить",
            font=(T.FONT_UI, 10, "bold"),
            fg=T.ON_ACCENT,
            bg=T.ACCENT,
            activebackground=T.ACCENT_HOVER,
            activeforeground=T.ON_ACCENT,
            relief="flat",
            bd=0,
            padx=18,
            pady=6,
            command=lambda: self._done("update"),
        ).pack(side="right")
        tk.Button(
            foot,
            text="позже",
            font=(T.FONT_UI, 10),
            fg=T.INK,
            bg=T.BG,
            activebackground=T.BG,
            relief="flat",
            bd=0,
            padx=14,
            pady=6,
            command=lambda: self._done("later"),
        ).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", lambda: self._done("later"))
        self.bind("<Escape>", lambda _e: self._done("later"))
        self.after(10, self._focus)

    def _focus(self) -> None:
        try:
            # A Toplevel can be left withdrawn by the window manager / CTk
            # titlebar re-apply — assert visibility before grabbing focus.
            self.deiconify()
            center_on_screen(self)
            self.grab_set()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _done(self, choice: str) -> None:
        self.result = (choice, bool(self._skip.get()))
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class MessageDialog(tk.Toplevel):
    """A plain OK dialog in the same style — used for "no updates" / errors."""

    def __init__(self, master: tk.Misc, title: str, body: str) -> None:
        super().__init__(master)
        self.title(T.APP_NAME)
        self.configure(bg=T.BG)
        self.geometry("420x210")
        self.resizable(False, False)
        self.transient(master)

        tk.Label(
            self, text=title, font=(T.FONT_UI, 14), fg=T.INK, bg=T.BG,
        ).pack(anchor="w", padx=20, pady=(20, 6))

        tk.Label(
            self, text=body, font=(T.FONT_UI, 10), fg=T.INK_SOFT, bg=T.BG,
            justify="left", wraplength=380, anchor="w",
        ).pack(anchor="w", padx=20, pady=(0, 10), fill="both", expand=True)

        foot = tk.Frame(self, bg=T.BG)
        foot.pack(fill="x", padx=20, pady=(0, 18))
        tk.Button(
            foot, text="ок", font=(T.FONT_UI, 10, "bold"),
            fg=T.ON_ACCENT, bg=T.ACCENT,
            activebackground=T.ACCENT_HOVER, activeforeground=T.ON_ACCENT,
            relief="flat", bd=0, padx=22, pady=6, command=self._close,
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _e: self._close())
        self.bind("<Return>", lambda _e: self._close())
        self.after(10, self._focus)

    def _focus(self) -> None:
        try:
            self.deiconify()
            center_on_screen(self)
            self.grab_set()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def show_message(master: tk.Misc, title: str, body: str) -> None:
    """Modal OK box — a button press always gets a window, never just a flash."""
    dlg = MessageDialog(master, title, body)
    try:
        master.wait_window(dlg)
    except Exception:  # noqa: BLE001
        pass


def ask(master: tk.Misc, info: dict, local_version: str) -> tuple[str, bool]:
    dlg = UpdateDialog(master, info, local_version)
    master.wait_window(dlg)
    return dlg.result
