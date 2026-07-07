"""Separate window: pick chivoblya chip style by number (Google-like gallery)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from . import settings as cfg
from . import theme as T
from .chip_styles import STYLES, get_style


class StylePickerWindow(tk.Toplevel):
    """User chooses chip look — numbered cards, live preview, save without restart."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_saved: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title(T.APP_NAME)
        self.configure(bg=T.BG)
        self.geometry("520x560")
        self.minsize(480, 480)
        self.resizable(False, False)
        self.transient(master)
        self._on_saved = on_saved
        self._selected = get_style(cfg.get().chip_style_id).id
        self._row_frames: dict[int, tk.Frame] = {}

        head = tk.Frame(self, bg=T.BG)
        head.pack(fill="x", padx=20, pady=(18, 6))
        tk.Label(
            head,
            text="стиль кнопки «чивобля?»",
            font=(T.FONT_UI, 16),
            fg=T.INK,
            bg=T.BG,
        ).pack(anchor="w")
        tk.Label(
            head,
            text="выбери номер — как у Google, варианты с превью. сохранится сразу.",
            font=(T.FONT_UI, 10),
            fg=T.INK_FAINT,
            bg=T.BG,
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        canvas = tk.Canvas(self, bg=T.BG, highlightthickness=0)
        scroll = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=8)

        inner = tk.Frame(canvas, bg=T.BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _cfg(_e=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win_id, width=canvas.winfo_width())

        inner.bind("<Configure>", _cfg)
        canvas.bind("<Configure>", _cfg)

        for st in STYLES:
            self._add_row(inner, st)

        foot = tk.Frame(self, bg=T.BG)
        foot.pack(fill="x", padx=20, pady=(4, 16), side="bottom")
        self._status = tk.Label(foot, text="", font=(T.FONT_UI, 9), fg=T.INK_FAINT, bg=T.BG)
        self._status.pack(side="left")
        tk.Button(
            foot,
            text="закрыть",
            font=(T.FONT_UI, 10),
            fg="#fff",
            bg=T.ACCENT,
            activebackground=T.ACCENT_HOVER,
            activeforeground="#fff",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            command=self.destroy,
        ).pack(side="right")

        self._paint_selection()

    def _add_row(self, parent: tk.Frame, st) -> None:
        row = tk.Frame(parent, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.LINE)
        row.pack(fill="x", pady=6, padx=(0, 12))
        self._row_frames[st.id] = row

        left = tk.Frame(row, bg=T.SURFACE, width=48)
        left.pack(side="left", padx=10, pady=12)
        num = tk.Label(
            left,
            text=str(st.id),
            font=(T.FONT_UI, 18, "bold"),
            fg=T.INK,
            bg=T.SURFACE,
            width=2,
        )
        num.pack()

        mid = tk.Frame(row, bg=T.SURFACE)
        mid.pack(side="left", fill="both", expand=True, pady=10)
        tk.Label(
            mid, text=st.name, font=(T.FONT_UI, 11, "bold"), fg=T.INK, bg=T.SURFACE, anchor="w"
        ).pack(anchor="w")
        tk.Label(
            mid,
            text=st.note,
            font=(T.FONT_UI, 9),
            fg=T.INK_FAINT,
            bg=T.SURFACE,
            anchor="w",
            wraplength=280,
            justify="left",
        ).pack(anchor="w", pady=(2, 8))

        # live preview of the chip
        prev = self._preview_chip(mid, st)
        prev.pack(anchor="w")

        # click whole row to select
        def pick(_e=None, sid=st.id) -> None:
            self._selected = sid
            self._paint_selection()
            cfg.update(chip_style_id=sid)
            self._status.configure(text=f"сохранено · стиль {sid}")
            if self._on_saved:
                try:
                    self._on_saved(sid)
                except Exception:
                    pass

        for w in (row, left, num, mid, prev):
            w.bind("<ButtonRelease-1>", pick)
            # bind children of preview
        self._bind_tree(prev, pick)

    def _bind_tree(self, w: tk.Misc, fn) -> None:
        w.bind("<ButtonRelease-1>", fn)
        for ch in w.winfo_children():
            self._bind_tree(ch, fn)

    def _preview_chip(self, parent: tk.Frame, st) -> tk.Frame:
        outer = tk.Frame(parent, bg=st.border, cursor="hand2")
        if st.dual_action:
            # 1/3 eye | 2/3 chivoblya
            left = tk.Frame(outer, bg=st.bg, width=40, cursor="hand2")
            left.pack(side="left", padx=(1, 0), pady=1)
            left.pack_propagate(False)
            tk.Label(
                left,
                text=st.icon or "👁",
                font=("Segoe UI Emoji", 11),
                fg=st.ink,
                bg=st.bg,
                cursor="hand2",
            ).place(relx=0.5, rely=0.5, anchor="center")
            tk.Frame(outer, bg=st.border, width=1).pack(side="left", fill="y", pady=1)
            right = tk.Frame(outer, bg=st.bg, cursor="hand2")
            right.pack(side="left", padx=(0, 1), pady=1)
            tk.Label(
                right,
                text="чивобля?",
                font=(T.FONT_UI, 10),
                fg=st.ink,
                bg=st.bg,
                padx=14,
                pady=6,
                cursor="hand2",
            ).pack()
        else:
            inner = tk.Frame(outer, bg=st.bg, cursor="hand2")
            inner.pack(padx=1, pady=1)
            tk.Label(
                inner,
                text="чивобля?",
                font=(T.FONT_UI, 10),
                fg=st.ink,
                bg=st.bg,
                padx=14,
                pady=6,
                cursor="hand2",
            ).pack()
        return outer

    def _paint_selection(self) -> None:
        for sid, fr in self._row_frames.items():
            if sid == self._selected:
                fr.configure(highlightbackground=T.ACCENT, highlightthickness=2, bg="#f0f0ec")
            else:
                fr.configure(highlightbackground=T.LINE, highlightthickness=1, bg=T.SURFACE)
