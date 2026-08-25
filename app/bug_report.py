"""User-triggered bug marks — the tray's report-a-bug item.

Writes a greppable BUGMARK into bonjur.log and a JSON sidecar under
~/.bonjur-epta/bugs/ so the next session can pull context around that time.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import customtkinter as ctk

from . import diag, logutil, peers
from . import theme as T
from .app_icon import apply as apply_app_icon
from .theme import ui_font

# Stable ids for menus + JSON (never translate these)
KIND_EXTRA_S = "extra_s"
KIND_NO_CHIP = "no_chip"
KIND_OTHER = "other"

KIND_LABELS: dict[str, str] = {
    KIND_EXTRA_S: "дополнительная «с»",
    KIND_NO_CHIP: "нет чипа при выделении",
    KIND_OTHER: "другое / описание",
}

_LOOKBACK_LINES = 80  # keep AUTOMARK/BUGMARK light — full-file read froze UI in 2.2.0
_LOCK = threading.Lock()


def kinds() -> list[tuple[str, str]]:
    return [(k, KIND_LABELS[k]) for k in (KIND_EXTRA_S, KIND_NO_CHIP, KIND_OTHER)]


def report(
    kind: str,
    note: str = "",
    *,
    app: Any | None = None,
    auto: bool = False,
) -> Path | None:
    """Stamp the log + write JSON. Returns path to the report file (or None)."""
    if kind not in KIND_LABELS:
        kind = KIND_OTHER
    note = (note or "").strip()
    stamp = datetime.now(timezone.utc)
    local = datetime.now().astimezone()
    rid = stamp.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    ver = T.APP_VERSION
    peer_list = peers.list_peers()
    snap = diag.snapshot_lines("SNAP")
    log = logutil.get()
    tag = "AUTOMARK" if auto else "BUGMARK"

    with _LOCK:
        log.warning("=" * 72)
        log.warning(
            "%s id=%s kind=%s ver=%s utc=%s local=%s auto=%s",
            tag,
            rid,
            kind,
            ver,
            stamp.isoformat(),
            local.isoformat(),
            auto,
        )
        log.warning("%s label=%s", tag, KIND_LABELS.get(kind, kind))
        if note:
            log.warning("%s note=%r", tag, note[:2000])
        for line in snap:
            log.warning("%s %s", tag, line)
        log.warning("%s peers=%s", tag, peers.summary(peer_list))
        log.warning("%s_END id=%s", tag, rid)
        log.warning("=" * 72)

    payload = {
        "id": rid,
        "kind": kind,
        "label": KIND_LABELS.get(kind, kind),
        "note": note,
        "auto": auto,
        "version": ver,
        "utc": stamp.isoformat(),
        "local": local.isoformat(),
        "uptime_s": round(diag.uptime_s(), 1),
        "wakes_1h": [
            {"unix": ts, "gap_s": round(gap, 1)} for ts, gap in diag.recent_wakes()
        ],
        "peers": [
            {"label": p.label, "exe": p.exe, "pid": p.pid} for p in peer_list
        ],
        "snapshot": snap,
        "log_tail": _log_tail(_LOOKBACK_LINES),
    }
    path = _write_json(rid, payload)
    if path:
        log.info("bug report file: %s", path)
    if not auto:
        _toast(app, kind, path)
    return path


def open_describe(app: Any) -> None:
    """Modal-ish note dialog for KIND_OTHER (must run on Tk thread)."""
    BugNoteDialog(app)


class BugNoteDialog(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.title("был баг")
        self.geometry("420x320")
        self.minsize(380, 280)
        self.configure(fg_color=T.SETTINGS_BG)
        self.transient(master)
        self.after(0, lambda: apply_app_icon(self))
        self._kind = ctk.StringVar(value=KIND_OTHER)

        pad = T.PAD
        ctk.CTkLabel(
            self,
            text="что случилось?",
            font=ui_font(16, "bold"),
            text_color=T.INK,
        ).pack(anchor="w", padx=pad, pady=(10, 4))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=pad, pady=(0, 6))
        for kid, label in kinds():
            ctk.CTkRadioButton(
                row,
                text=label,
                variable=self._kind,
                value=kid,
                font=ui_font(12),
                text_color=T.INK,
                fg_color=T.SWITCH_ON,
                hover_color=T.SWITCH_ON,
            ).pack(anchor="w", pady=2)

        ctk.CTkLabel(
            self,
            text="описание (что делал, какая программа была в фокусе)",
            font=ui_font(11),
            text_color=T.INK,
        ).pack(anchor="w", padx=pad, pady=(4, 2))

        self._box = ctk.CTkTextbox(
            self,
            height=110,
            font=ui_font(12),
            fg_color=T.SETTINGS_CARD,
            text_color=T.INK,
            border_width=1,
            border_color=T.LINE,
        )
        self._box.pack(fill="both", expand=True, padx=pad, pady=(0, 8))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=pad, pady=(0, 10))
        ctk.CTkButton(
            btns,
            text="отмена",
            width=100,
            fg_color=T.SETTINGS_CARD,
            text_color=T.INK,
            hover_color=T.LINE,
            command=self.destroy,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            btns,
            text="записать",
            width=120,
            command=self._save,
        ).pack(side="right")

        try:
            self.lift()
            self.focus_force()
            self._box.focus_set()
        except Exception:  # noqa: BLE001
            pass

    def _save(self) -> None:
        note = ""
        try:
            note = self._box.get("1.0", "end").strip()
        except Exception:  # noqa: BLE001
            pass
        kind = self._kind.get() or KIND_OTHER
        report(kind, note, app=self.master)
        self.destroy()


def _bugs_dir() -> Path:
    d = Path.home() / ".bonjur-epta" / "bugs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_json(rid: str, payload: dict) -> Path | None:
    try:
        path = _bugs_dir() / f"bug-{rid}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except Exception:  # noqa: BLE001
        logutil.exc("bug_report write")
        return None


def _log_paths() -> list[Path]:
    paths = [Path.home() / ".bonjur-epta" / "bonjur.log"]
    try:
        paths.append(Path(__file__).resolve().parent.parent / "bonjur.log")
    except Exception:  # noqa: BLE001
        pass
    return paths


def _log_tail(n: int) -> list[str]:
    """Read only the end of the log — never the whole multi‑MB file on the UI thread."""
    for p in _log_paths():
        try:
            if not p.is_file():
                continue
            size = p.stat().st_size
            # ~200 bytes/line upper bound; cap read window
            window = min(size, max(16_384, n * 240))
            with open(p, "rb") as fh:
                if size > window:
                    fh.seek(size - window)
                    fh.readline()  # drop partial first line
                raw = fh.read().decode("utf-8", errors="replace")
            lines = raw.splitlines()
            return lines[-n:]
        except Exception:  # noqa: BLE001
            continue
    return []


def _toast(app: Any | None, kind: str, path: Path | None) -> None:
    if app is None:
        return
    label = KIND_LABELS.get(kind, kind)
    msg = f"баг записан: {label}"
    if path:
        msg += f" → {path.name}"

    def set_status() -> None:
        try:
            st = getattr(app, "_status", None)
            if st is not None and hasattr(st, "set"):
                st.set(msg)
        except Exception:  # noqa: BLE001
            pass

    try:
        app.after(0, set_status)
    except Exception:  # noqa: BLE001
        pass
