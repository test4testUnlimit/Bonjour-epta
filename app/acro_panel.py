"""Acronym breakdown strip under both panes.

Read-only, offline, sized to its content and hidden when there is nothing to
say — a text without acronyms leaves the window looking exactly as before.
Full width on purpose: «PPAP · Production Part Approval Process» does not fit
a ~470px pane column, but reads fine across ~940px.
"""

from __future__ import annotations

import webbrowser

import customtkinter as ctk

from . import theme as T
from .theme import ui_font

MAX_FRACTION = 0.35  # never eat more than this share of the window
MIN_H = 52
INDENT = 18  # continuation lines hang under the term
ARROW = " ↗"


class AcronymPanel(ctk.CTkFrame):
    """`render(report)` fills it and decides whether it is visible at all."""

    def __init__(self, parent, *, on_open_dict=None) -> None:
        super().__init__(
            parent,
            fg_color=T.SURFACE,
            corner_radius=T.CORNER,
            border_width=1,
            border_color=T.LINE,
        )
        self._on_open_dict = on_open_dict
        self._pack_kw = dict(fill="x", pady=(T.GAP, 0))
        self._shown = False
        self._rows: list[int] = []  # font size of every logical line written
        self._blocks = 0  # blocks get extra air above
        self._links = 0  # per-url tags, recreated on every render

        self._f_term = ui_font(13, "bold")
        self._f_body = ui_font(12)
        self._f_small = ui_font(11)

        bar = ctk.CTkFrame(self, fg_color="transparent", height=T.BAR_H)
        bar.pack(fill="x", padx=T.INSET, pady=(T.INSET, T.BAR_GAP))
        bar.pack_propagate(False)

        self._title = ctk.CTkLabel(
            bar, text="акронимы", font=ui_font(11), text_color=T.INK_FAINT, anchor="w"
        )
        self._title.pack(side="left")

        self._dict_btn = ctk.CTkButton(
            bar,
            text="словарь",
            width=76,
            height=T.CTRL_H,
            corner_radius=T.CORNER_SM,
            fg_color=T.CHIP_BG,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT,
            font=ui_font(11),
            command=lambda: self._open_dict(""),
        )
        if on_open_dict is not None:
            self._dict_btn.pack(side="right")

        self._box = ctk.CTkTextbox(
            self,
            fg_color=T.FIELD,
            text_color=T.INK,
            border_width=1,
            border_color=T.LINE,
            border_spacing=T.TEXT_BORDER_SPACING,
            font=self._f_body,
            wrap="word",
            height=MIN_H,
            corner_radius=T.CORNER_SM,
            scrollbar_button_color=T.LINE,
            scrollbar_button_hover_color=T.LINE_STRONG,
        )
        self._box.pack(fill="x", padx=T.INSET, pady=(0, T.INSET))
        self._inner = getattr(self._box, "_textbox", self._box)
        self._make_tags()
        self._box.configure(state="disabled")
        self._last_w = 0
        self._fit_job: str | None = None
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event) -> None:
        """Width drives wrapping, so a resize changes the height we need."""
        if not self._shown or abs(event.width - self._last_w) < 24:
            return
        self._last_w = event.width
        if self._fit_job is not None:
            try:
                self.after_cancel(self._fit_job)
            except Exception:  # noqa: BLE001
                pass
        self._fit_job = self.after(150, lambda: self._fit(retry=False))

    # ── visibility ───────────────────────────────────────────

    def show(self) -> None:
        if not self._shown:
            self.pack(**self._pack_kw)
            self._shown = True

    def hide(self) -> None:
        if self._shown:
            self.pack_forget()
            self._shown = False

    # ── styling ──────────────────────────────────────────────

    def _font(self, f):
        """CTkFont → the scaled tuple the inner tk.Text needs on a HiDPI screen."""
        try:
            return self._box._apply_font_scaling(f)
        except Exception:  # noqa: BLE001
            return (T.FONT_UI, f.cget("size"))

    def _make_tags(self) -> None:
        t = self._inner
        sub = dict(lmargin1=INDENT, lmargin2=INDENT)
        t.tag_config("term", font=self._font(self._f_term), foreground=T.INK, spacing1=6)
        t.tag_config("exp", font=self._font(self._f_body), foreground=T.INK_SOFT)
        t.tag_config("ru", font=self._font(self._f_body), foreground=T.INK, **sub)
        t.tag_config("where", font=self._font(self._f_small), foreground=T.INK_FAINT, **sub)
        t.tag_config("alt", font=self._font(self._f_small), foreground=T.INK_SOFT, **sub)
        t.tag_config("unk", font=self._font(self._f_small), foreground=T.INK_FAINT, spacing1=8)

    def _link_tag(self, url: str, term: str = "") -> str:
        """A fresh clickable tag — one per link, dropped on the next render."""
        name = f"link{self._links}"
        self._links += 1
        t = self._inner
        t.tag_config(
            name,
            font=self._font(self._f_small),
            foreground=T.LINK,
            underline=1,
            lmargin1=INDENT,
            lmargin2=INDENT,
        )
        if url:
            t.tag_bind(name, "<Button-1>", lambda _e, u=url: self._open_url(u))
        else:
            t.tag_bind(name, "<Button-1>", lambda _e, w=term: self._open_dict(w))
        t.tag_bind(name, "<Enter>", lambda _e: t.configure(cursor="hand2"))
        t.tag_bind(name, "<Leave>", lambda _e: t.configure(cursor=""))
        return name

    @staticmethod
    def _open_url(url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    def _open_dict(self, term: str) -> None:
        if self._on_open_dict is None:
            return
        try:
            self._on_open_dict(term)
        except Exception:  # noqa: BLE001
            pass

    # ── writing ──────────────────────────────────────────────

    def _write(self, segs, size: int) -> None:
        """One logical line from (text, tag) pieces; remembers its height."""
        for text, tag in segs:
            self._inner.insert("end", text, tag)
        self._inner.insert("end", "\n")
        self._rows.append(size)

    def _hit(self, h) -> None:
        best = h.best
        self._blocks += 1
        if best is None:  # only the text itself explained it
            self._write([(h.raw, "term"), (f" · {h.inline}", "exp")], 13)
            self._write([("из текста", "where")], 11)
            return

        self._write([(best.term, "term"), (f" · {best.expansion}", "exp")], 13)
        if best.ru:
            self._write([(best.ru, "ru")], 12)
        if best.where:
            self._write([(f"где: {best.where}", "where")], 11)
        if h.ambiguous:
            for alt in h.entries[1:3]:
                tail = f" — {alt.ru}" if alt.ru else ""
                self._write([(f"или: {alt.expansion}{tail}", "alt")], 11)
        if best.source_title:
            url = best.source_url
            self._write([(best.source_title + (ARROW if url else ""), self._link_tag(url))], 11)

    def _unknown(self, words: list[str]) -> None:
        self._blocks += 1
        self._inner.insert("end", "не знаю: ", "unk")
        for i, w in enumerate(words):
            if i:
                self._inner.insert("end", ", ", "unk")
            self._inner.insert("end", w, self._link_tag("", w) if self._on_open_dict else "unk")
        self._inner.insert("end", "\n")
        self._rows.append(11)

    # ── public ───────────────────────────────────────────────

    def render(self, rep) -> None:
        """Fill from an `acronyms.Report`; hide when it has nothing."""
        hits = list(getattr(rep, "hits", None) or [])
        unknown = list(getattr(rep, "unknown", None) or [])
        if not hits and not unknown:
            self.hide()
            return

        self._rows = []
        self._blocks = 0
        t = self._inner
        for name in t.tag_names():
            if str(name).startswith("link"):
                t.tag_delete(name)
        self._links = 0

        self._box.configure(state="normal")
        t.delete("1.0", "end")
        for h in hits:
            self._hit(h)
        if unknown:
            self._unknown(unknown)
        t.delete("end-1c", "end")  # drop the trailing newline
        self._box.configure(state="disabled")

        self._title.configure(text=f"акронимы · {len(hits)}" if hits else "акронимы")
        self.show()
        self._fit()

    def _fit(self, retry: bool = True) -> None:
        """Height by content, capped — then the box scrolls instead of growing."""
        if not self._shown:
            return
        try:
            self.update_idletasks()
        except Exception:  # noqa: BLE001
            pass

        px = {}
        for size, f in ((13, self._f_term), (12, self._f_body), (11, self._f_small)):
            try:
                px[size] = int(f.metrics("linespace"))
            except Exception:  # noqa: BLE001
                px[size] = size + 5
        need = sum(px.get(s, 17) for s in self._rows) + self._blocks * 6

        # An unmapped Text is one char wide and reports every char as a line —
        # measure only once geometry is real, otherwise come back on idle.
        if self._inner.winfo_width() > 50:
            try:
                shown = int(self._inner.count("1.0", "end-1c", "displaylines")[0]) + 1
                need += max(0, shown - len(self._rows)) * px[12]
            except Exception:  # noqa: BLE001
                pass
        elif retry:
            self.after_idle(lambda: self._fit(retry=False))

        need += 2 * T.TEXT_BORDER_SPACING + 4
        self._box.configure(height=max(MIN_H, min(need, self._cap())))

    def _cap(self) -> int:
        """A third of the window, in the logical units CTk sizes widgets with."""
        try:
            phys = int(self.winfo_toplevel().winfo_height())
            scale = float(ctk.ScalingTracker.get_widget_scaling(self)) or 1.0
            logical = phys / scale
        except Exception:  # noqa: BLE001
            logical = 0
        if logical < 200:  # window not laid out yet
            logical = 560
        return max(MIN_H, int(logical * MAX_FRACTION))
