"""Dictionary window: search the packs, paste a new table, see what is loaded.

Three tabs, one job each — look a term up, feed the base, know where every
entry came from. Everything is local: no request leaves the machine, and
imported rows are split public / internal so the site-specific half never
drifts into git.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

import customtkinter as ctk

from . import ai_client, ai_config, assistant, logutil
from . import settings as cfg
from . import theme as T
from .acronyms import importer, store
from .app_icon import apply as apply_app_icon
from .theme import ui_font

_W, _H = 660, 620
MAX_ROWS = 80  # a search that matches everything is a scroll, not an answer

# imported rows land in live local packs, so a paste works immediately;
# the public half is a separate file you can copy into the repo as-is.
LOCAL_PACK = "user"
PUBLIC_PACK = "user_public"

CONF_RU = {"high": "уверенно", "medium": "возможно", "low": "догадка"}


class AcroWindow(ctk.CTkToplevel):
    """`AcroWindow(master, term="PPAP")` opens straight on that search."""

    def __init__(self, master, *, term: str = "", on_changed: Callable[[], None] | None = None) -> None:
        super().__init__(master)
        self.title(T.APP_NAME)
        self.geometry(f"{_W}x{_H}")
        self.minsize(520, 420)
        self.configure(fg_color=T.SETTINGS_BG)
        self.transient(master)
        self.after(0, lambda: apply_app_icon(self))
        self._on_changed = on_changed
        self._rows: list[importer.Row] = []
        self._tabs: dict[str, ctk.CTkFrame] = {}
        self._tab_btns: dict[str, ctk.CTkButton] = {}

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=T.GAP, pady=(T.GAP, 0))
        for key, label in (("search", "поиск"), ("import", "импорт"), ("packs", "паки")):
            b = ctk.CTkButton(
                bar,
                text=label,
                width=92,
                height=T.CTRL_H,
                corner_radius=T.CORNER_SM,
                fg_color=T.SURFACE,
                border_width=1,
                border_color=T.LINE,
                hover_color=T.CHIP_HOVER,
                text_color=T.INK_SOFT,
                font=ui_font(12),
                command=lambda k=key: self._select(k),
            )
            b.pack(side="left", padx=(0, 6))
            self._tab_btns[key] = b

        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="both", expand=True, padx=T.GAP, pady=T.GAP)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=T.GAP, pady=(0, T.GAP))
        self._status = ctk.CTkLabel(foot, text="", font=ui_font(11), text_color=T.INK_FAINT)
        self._status.pack(side="left")
        ctk.CTkButton(
            foot,
            text="закрыть",
            width=96,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color=T.ON_ACCENT,
            font=ui_font(12),
            command=self.destroy,
        ).pack(side="right")

        self._build_search()
        self._build_import()
        self._build_packs()
        self._select("search")
        if term:
            self._query.insert(0, term)
        self.after(60, self._run_search)
        self.after(80, self._query.focus_set)

    # ── tabs ─────────────────────────────────────────────────

    def _select(self, key: str) -> None:
        for k, frame in self._tabs.items():
            frame.pack_forget()
            btn = self._tab_btns[k]
            on = k == key
            btn.configure(
                fg_color=T.ACCENT if on else T.SURFACE,
                text_color=T.ON_ACCENT if on else T.INK_SOFT,
                border_color=T.ACCENT if on else T.LINE,
            )
        self._tabs[key].pack(fill="both", expand=True)
        if key == "packs":
            self._fill_packs()

    def _panel(self, key: str) -> ctk.CTkFrame:
        f = ctk.CTkFrame(
            self._body,
            fg_color=T.SURFACE,
            corner_radius=T.CORNER,
            border_width=1,
            border_color=T.LINE,
        )
        self._tabs[key] = f
        return f

    def _readonly_box(self, parent) -> ctk.CTkTextbox:
        box = ctk.CTkTextbox(
            parent,
            fg_color=T.FIELD,
            text_color=T.INK,
            border_width=1,
            border_color=T.LINE,
            border_spacing=T.TEXT_BORDER_SPACING,
            font=ui_font(12),
            wrap="word",
            corner_radius=T.CORNER_SM,
            scrollbar_button_color=T.LINE,
            scrollbar_button_hover_color=T.LINE_STRONG,
        )
        inner = getattr(box, "_textbox", box)
        try:
            scaled = box._apply_font_scaling
        except AttributeError:  # pragma: no cover - CTk internals
            def scaled(f):
                return (T.FONT_UI, f.cget("size"))
        inner.tag_config("term", font=scaled(ui_font(13, "bold")), foreground=T.INK, spacing1=6)
        inner.tag_config("exp", font=scaled(ui_font(12)), foreground=T.INK_SOFT)
        inner.tag_config("ru", font=scaled(ui_font(12)), foreground=T.INK, lmargin1=18, lmargin2=18)
        inner.tag_config(
            "note", font=scaled(ui_font(11)), foreground=T.INK_FAINT, lmargin1=18, lmargin2=18
        )
        inner.tag_config("bad", font=scaled(ui_font(11)), foreground=T.ERR, lmargin1=18, lmargin2=18)
        box.configure(state="disabled")
        return box

    @staticmethod
    def _fill(box: ctk.CTkTextbox, chunks) -> None:
        inner = getattr(box, "_textbox", box)
        box.configure(state="normal")
        inner.delete("1.0", "end")
        for text, tag in chunks:
            inner.insert("end", text, tag)
        box.configure(state="disabled")

    def _small_btn(self, parent, text: str, cmd, width: int = 104) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            height=T.CTRL_H,
            corner_radius=T.CORNER_SM,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT,
            font=ui_font(11),
            command=cmd,
        )

    # ── search ───────────────────────────────────────────────

    def _build_search(self) -> None:
        f = self._panel("search")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=T.INSET, pady=(T.INSET, T.BAR_GAP))
        self._query = ctk.CTkEntry(
            row,
            placeholder_text="термин, расшифровка или русское слово",
            height=T.CTRL_H,
            corner_radius=T.CORNER_SM,
            fg_color=T.FIELD,
            border_color=T.LINE,
            text_color=T.INK,
            font=ui_font(12),
        )
        self._query.pack(side="left", fill="x", expand=True)
        self._query.bind("<KeyRelease>", lambda _e: self._debounce())
        self._query.bind("<Return>", lambda _e: self._run_search())
        self._small_btn(row, "очистить", self._clear_search, 88).pack(side="left", padx=(6, 0))
        self._ask_btn = self._small_btn(row, "спросить ИИ", self._ask_ai, 108)
        self._ask_btn.pack(side="left", padx=(6, 0))

        self._hits = self._readonly_box(f)
        self._hits.pack(fill="both", expand=True, padx=T.INSET, pady=(0, T.INSET))
        self._search_job: str | None = None

        # what the model offered, one card each — packed under the hits only
        # while there is something to pick from
        self._cards = ctk.CTkScrollableFrame(
            f, fg_color=T.FIELD, corner_radius=T.CORNER_SM, height=190
        )
        self._cards_shown = False
        self._cards_term = ""
        self._ai_busy = False

    def search_for(self, term: str) -> None:
        """Re-point an already-open window at another word."""
        self._select("search")
        self._query.delete(0, "end")
        if term:
            self._query.insert(0, term)
        self._run_search()
        self._query.focus_set()

    def _clear_search(self) -> None:
        self._query.delete(0, "end")
        self._run_search()

    def _debounce(self) -> None:
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except Exception:  # noqa: BLE001
                pass
        self._search_job = self.after(140, self._run_search)

    def _run_search(self) -> None:
        needle = self._query.get().strip().lower()
        entries = self._all_entries()
        if needle:
            found = [e for e in entries if self._matches(e, needle)]
            found.sort(key=lambda e: (not e.term.lower().startswith(needle), e.term.lower()))
        else:
            found = sorted(entries, key=lambda e: e.term.lower())

        chunks: list[tuple[str, str]] = []
        for e in found[:MAX_ROWS]:
            chunks.append((e.term, "term"))
            chunks.append((f" · {e.expansion}\n", "exp"))
            if e.ru:
                chunks.append((f"{e.ru}\n", "ru"))
            if e.where:
                chunks.append((f"{e.where}\n", "note"))
            chunks.append((f"пак: {e.pack}\n", "note"))
        if not found:
            ok, _ = self._ai_ready()
            hint = " — можно спросить ИИ" if ok and needle else ""
            chunks.append((f"ничего не нашлось{hint}\n", "note"))
        self._fill(self._hits, chunks)

        # cards belong to the word they were fetched for, not to whatever is
        # in the box now
        if needle != self._cards_term.lower():
            self._show_cards([], "")
        self._sync_ask()

        shown = min(len(found), MAX_ROWS)
        tail = f" · показано {shown}" if len(found) > MAX_ROWS else ""
        self._status.configure(text=f"найдено {len(found)} из {len(entries)}{tail}")

    @staticmethod
    def _matches(e, needle: str) -> bool:
        blob = " ".join((e.term, e.expansion, e.ru, e.where, " ".join(e.aliases))).lower()
        return needle in blob

    @staticmethod
    def _all_entries() -> list:
        """Every enabled pack — the same base the main window reads."""
        try:
            return list(store.index().entries)
        except Exception:  # noqa: BLE001
            return []

    # ── ask the model ────────────────────────────────────────
    # The packs stay the source of truth; this only fills the gap when a word
    # is not in them yet. Nothing is saved without a click.

    @staticmethod
    def _ai_ready() -> tuple[bool, str]:
        try:
            if not cfg.get().ai_enabled or not ai_config.configured():
                return False, "ИИ выключен"
            return ai_client.available()
        except Exception:  # noqa: BLE001
            return False, "ИИ недоступен"

    def _sync_ask(self) -> None:
        ok, _ = self._ai_ready()
        live = ok and bool(self._query.get().strip()) and not self._ai_busy
        try:
            self._ask_btn.configure(state="normal" if live else "disabled")
        except Exception:  # noqa: BLE001
            pass

    def _ask_ai(self) -> None:
        term = self._query.get().strip()
        if not term or self._ai_busy:
            return
        ok, why = self._ai_ready()
        if not ok:
            self._status.configure(text=why)
            return

        self._ai_busy = True
        self._ask_btn.configure(state="disabled", text="спрашиваю…")
        self._status.configure(text=f"спрашиваю про {term}…")
        context = " ".join(e.expansion for e in self._all_entries() if e.term.lower() == term.lower())

        def land(cands, err) -> None:
            try:
                self.after(0, lambda: self._ai_answer(cands, term, err))
            except Exception:  # noqa: BLE001
                pass  # window closed while we were waiting

        def work() -> None:
            try:
                land(assistant.explain_acronym(term, context), "")
            except ai_client.AiError as exc:
                land([], str(exc))
            except Exception:  # noqa: BLE001
                logutil.exc("acro ask ai")
                land([], "не получилось")

        threading.Thread(target=work, daemon=True).start()

    def _ai_answer(self, cands: list, term: str, err: str) -> None:
        self._ai_busy = False
        self._ask_btn.configure(text="спросить ИИ")
        self._sync_ask()
        self._show_cards(cands, term)
        if err:
            self._status.configure(text=err)
        elif not cands:
            self._status.configure(text=f"ИИ тоже не знает «{term}»")
        else:
            self._status.configure(
                text=f"ИИ предложил {len(cands)} — выбери, что сохранить"
            )

    def _show_cards(self, cands: list, term: str) -> None:
        for w in self._cards.winfo_children():
            w.destroy()
        self._cards_term = term
        if not cands:
            if self._cards_shown:
                self._cards.pack_forget()
                self._cards_shown = False
            return
        for c in cands:
            self._card(c)
        if not self._cards_shown:
            self._cards.pack(fill="x", padx=T.INSET, pady=(0, T.INSET))
            self._cards_shown = True

    def _card(self, c) -> None:
        card = ctk.CTkFrame(
            self._cards,
            fg_color=T.SURFACE,
            corner_radius=T.CORNER_SM,
            border_width=1,
            border_color=T.LINE,
        )
        card.pack(fill="x", padx=4, pady=(6, 0))

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=8, pady=(6, 0))
        self._small_btn(head, "сохранить", lambda: self._save_candidate(c, card), 96).pack(
            side="right"
        )
        ctk.CTkLabel(
            head,
            text=f"{c.term} · {c.expansion}",
            font=ui_font(12, "bold"),
            text_color=T.INK,
            anchor="w",
            justify="left",
            wraplength=_W - 230,
        ).pack(side="left")

        for text, colour in ((c.ru, T.INK), (c.where, T.INK_FAINT)):
            if text:
                ctk.CTkLabel(
                    card,
                    text=text,
                    font=ui_font(11),
                    text_color=colour,
                    anchor="w",
                    justify="left",
                    wraplength=_W - 90,
                ).pack(anchor="w", padx=8)

        tail = " · ".join(
            x for x in (", ".join(c.domain), CONF_RU.get(c.confidence, c.confidence)) if x
        )
        ctk.CTkLabel(
            card, text=tail or "—", font=ui_font(10), text_color=T.INK_FAINT, anchor="w"
        ).pack(anchor="w", padx=8, pady=(0, 6))

    def _save_candidate(self, c, card) -> None:
        """Straight into the local pack — same pipeline a pasted table goes through."""
        try:
            path = store.local_dir() / f"{LOCAL_PACK}.json"
            keep = importer.load_keep(path, overwrite=False)
            merged = {(e.get("term", ""), e.get("expansion", "")): e for e in keep.values()}
            entry = importer.to_entry(assistant.to_row(c), keep, default_domain=("ai",))
            # stamped, so later it is obvious a model wrote this and no human checked it
            entry["source"] = {"title": f"ИИ · {ai_client.model()}"}
            merged[(entry["term"], entry["expansion"])] = entry
            importer.write_pack(
                path,
                LOCAL_PACK,
                "Мои термины",
                40,
                sorted(merged.values(), key=lambda e: e["term"].lower()),
            )
        except Exception as exc:  # noqa: BLE001
            self._status.configure(text=f"не сохранилось: {exc}")
            return

        store.reload()
        self._notify()
        try:
            card.destroy()
        except Exception:  # noqa: BLE001
            pass
        saved = f"{c.term} · {c.expansion}"
        self._run_search()
        self._status.configure(text=f"сохранено — {saved}")

    # ── import ───────────────────────────────────────────────

    def _build_import(self) -> None:
        f = self._panel("import")
        ctk.CTkLabel(
            f,
            text="вставь таблицу: TERM ⇥ расшифровка ⇥ примечание, или как скопировалось из браузера",
            font=ui_font(11),
            text_color=T.INK_FAINT,
            anchor="w",
            justify="left",
            wraplength=_W - 80,
        ).pack(anchor="w", padx=T.INSET, pady=(T.INSET, 6))

        self._paste = ctk.CTkTextbox(
            f,
            height=150,
            fg_color=T.FIELD,
            text_color=T.INK,
            border_width=1,
            border_color=T.LINE,
            border_spacing=T.TEXT_BORDER_SPACING,
            font=ui_font(12),
            wrap="none",
            corner_radius=T.CORNER_SM,
            scrollbar_button_color=T.LINE,
            scrollbar_button_hover_color=T.LINE_STRONG,
        )
        self._paste.pack(fill="x", padx=T.INSET, pady=(0, 6))

        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=T.INSET, pady=(0, 6))
        self._small_btn(row, "разобрать", self._parse_paste, 96).pack(side="left")
        self._save_btn = self._small_btn(row, "сохранить", self._save_import, 104)
        self._save_btn.pack(side="left", padx=(6, 0))
        self._save_btn.configure(state="disabled")
        self._small_btn(row, "очистить", self._clear_import, 88).pack(side="left", padx=(6, 0))

        self._preview = self._readonly_box(f)
        self._preview.pack(fill="both", expand=True, padx=T.INSET, pady=(0, T.INSET))

    def _clear_import(self) -> None:
        self._paste.delete("1.0", "end")
        self._rows = []
        self._save_btn.configure(state="disabled")
        self._fill(self._preview, [])
        self._status.configure(text="")

    def _parse_paste(self) -> None:
        text = self._paste.get("1.0", "end")
        try:
            rows = importer.parse(text)
            known = importer.repo_pairs()
            for r in rows:
                importer.classify(r, known)
                r.domain = importer.guess_domains(r)
        except Exception as exc:  # noqa: BLE001
            self._rows = []
            self._save_btn.configure(state="disabled")
            self._fill(self._preview, [(f"не разобралось: {exc}\n", "bad")])
            return

        self._rows = [r for r in rows if r.verdict != "known"]
        counts = {"public": 0, "internal": 0, "known": 0}
        chunks: list[tuple[str, str]] = []
        for r in rows:
            counts[r.verdict] = counts.get(r.verdict, 0) + 1
            if r.verdict == "known":
                continue
            where = "в git можно" if r.verdict == "public" else "только локально"
            chunks.append((r.term, "term"))
            chunks.append((f" · {r.expansion}\n", "exp"))
            if r.notes:
                chunks.append((f"{r.notes[:200]}\n", "note"))
            chunks.append((f"{where} — {', '.join(r.reasons) or '—'}\n", "note"))
        if not rows:
            chunks.append(("ни одной строки не разобрал — это точно таблица?\n", "bad"))
        self._fill(self._preview, chunks)

        self._save_btn.configure(state="normal" if self._rows else "disabled")
        self._status.configure(
            text=f"разобрано {len(rows)} · локально {counts['internal']}"
            f" · публичных {counts['public']} · уже есть {counts['known']}"
        )

    def _save_import(self) -> None:
        if not self._rows:
            return
        try:
            wrote = self._write_rows()
        except Exception as exc:  # noqa: BLE001
            self._fill(self._preview, [(f"не сохранилось: {exc}\n", "bad")])
            return
        store.reload()
        self._notify()
        parts = " · ".join(f"{pid}: {n}" for pid, n in wrote.items())
        self._status.configure(text=f"сохранено — {parts}")
        self._save_btn.configure(state="disabled")
        self._rows = []

    def _write_rows(self) -> dict[str, int]:
        """Local pack for site-specific rows, a second one for the git-safe half."""
        out: dict[str, int] = {}
        split = {
            LOCAL_PACK: [r for r in self._rows if r.verdict != "public"],
            PUBLIC_PACK: [r for r in self._rows if r.verdict == "public"],
        }
        titles = {LOCAL_PACK: "Мои термины", PUBLIC_PACK: "Мои — публичные кандидаты"}
        prio = {LOCAL_PACK: 40, PUBLIC_PACK: 35}
        for pid, rows in split.items():
            if not rows:
                continue
            path = store.local_dir() / f"{pid}.json"
            keep = importer.load_keep(path, overwrite=False)
            merged = {(e.get("term", ""), e.get("expansion", "")): e for e in keep.values()}
            for r in rows:
                entry = importer.to_entry(r, keep, default_domain=())
                merged[(entry["term"], entry["expansion"])] = entry
            entries = sorted(merged.values(), key=lambda e: e["term"].lower())
            importer.write_pack(path, pid, titles[pid], prio[pid], entries)
            out[pid] = len(rows)
        return out

    # ── packs ────────────────────────────────────────────────

    def _build_packs(self) -> None:
        f = self._panel("packs")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=T.INSET, pady=(T.INSET, 6))
        ctk.CTkLabel(
            row, text="подключённые словари", font=ui_font(12, "bold"), text_color=T.INK
        ).pack(side="left")
        self._small_btn(row, "папка", self._open_dir, 84).pack(side="right")
        self._small_btn(row, "перечитать", self._reload_packs, 104).pack(side="right", padx=(0, 6))

        self._pack_list = ctk.CTkScrollableFrame(f, fg_color=T.FIELD, corner_radius=T.CORNER_SM)
        self._pack_list.pack(fill="both", expand=True, padx=T.INSET, pady=(0, T.INSET))

    def _fill_packs(self) -> None:
        for w in self._pack_list.winfo_children():
            w.destroy()
        found = store.packs()
        if not found:
            ctk.CTkLabel(
                self._pack_list, text="словарей нет", font=ui_font(11), text_color=T.INK_FAINT
            ).pack(anchor="w", padx=8, pady=8)
            return
        for p in found:
            card = ctk.CTkFrame(self._pack_list, fg_color="transparent")
            card.pack(fill="x", padx=4, pady=(6, 0))
            where = "локально" if p.origin == "local" else "в репо"
            head = f"{p.title or p.id} · {p.count} · {where}"
            if p.error:
                ctk.CTkLabel(
                    card, text=f"{p.id} · не читается", font=ui_font(12), text_color=T.ERR
                ).pack(anchor="w")
            else:
                colour = T.INK if store.is_enabled(p.id) else T.INK_FAINT
                ctk.CTkLabel(card, text=head, font=ui_font(12), text_color=colour).pack(anchor="w")
            ctk.CTkLabel(
                card,
                text=str(p.path),
                font=ui_font(10),
                text_color=T.INK_FAINT,
                anchor="w",
                justify="left",
                wraplength=_W - 120,
            ).pack(anchor="w")
        self._status.configure(
            text=f"{len(found)} словарей · {sum(p.count for p in found)} терминов"
        )

    def _reload_packs(self) -> None:
        store.reload()
        self._fill_packs()
        self._run_search()
        self._notify()

    def _open_dir(self) -> None:
        try:
            os.startfile(str(store.local_dir()))  # noqa: S606
        except Exception:  # noqa: BLE001
            self._status.configure(text="не удалось открыть папку")

    def _notify(self) -> None:
        if self._on_changed is None:
            return
        try:
            self._on_changed()
        except Exception:  # noqa: BLE001
            pass
