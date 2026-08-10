"""Tests for interferer detection + bug-mark plumbing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import bug_report, peers


class TestPeers:
    def test_summary_none(self):
        assert peers.summary([]) == "none"

    def test_summary_lists(self):
        items = [
            peers.Peer(label="ShareX", exe="ShareX.exe", pid=11),
            peers.Peer(label="Caramba Switcher", exe="CarambaSwitcher.exe", pid=22),
        ]
        s = peers.summary(items)
        assert "ShareX" in s and "Caramba" in s

    def test_known_fuzzy_sharex(self):
        with patch("app.peers._iter_processes", return_value=[("ShareX.exe", 42)]):
            got = peers.list_peers()
        assert len(got) == 1
        assert got[0].label == "ShareX"
        assert got[0].pid == 42

    def test_known_fuzzy_caramba(self):
        with patch(
            "app.peers._iter_processes",
            return_value=[("CarambaSwitcher64.exe", 7)],
        ):
            got = peers.list_peers()
        assert len(got) == 1
        assert got[0].label == "Caramba Switcher"


class TestBugReport:
    def test_report_writes_mark_and_json(self, tmp_path: Path, monkeypatch):
        log_lines: list[str] = []

        class FakeLog:
            def warning(self, msg, *args):
                log_lines.append(msg % args if args else msg)

            def info(self, msg, *args):
                log_lines.append(msg % args if args else msg)

        monkeypatch.setattr(bug_report, "_bugs_dir", lambda: tmp_path)
        monkeypatch.setattr(bug_report, "_log_tail", lambda _n: ["tail"])
        with (
            patch("app.bug_report.logutil.get", return_value=FakeLog()),
            patch("app.bug_report.peers.list_peers", return_value=[]),
            patch("app.bug_report.peers.summary", return_value="none"),
            patch("app.bug_report.diag.snapshot_lines", return_value=["SNAP uptime_s=1"]),
            patch("app.bug_report.diag.uptime_s", return_value=1.0),
            patch("app.bug_report.diag.recent_wakes", return_value=[]),
            patch("app.bug_report._toast"),
        ):
            path = bug_report.report(bug_report.KIND_EXTRA_S, note="в конце текста")

        assert path is not None and path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["kind"] == "extra_s"
        assert "с" in data["note"] or data["note"]
        joined = "\n".join(log_lines)
        assert "BUGMARK" in joined
        assert "extra_s" in joined
        assert "BUGMARK_END" in joined

    def test_kinds_cover_field_bugs(self):
        ids = {k for k, _ in bug_report.kinds()}
        assert bug_report.KIND_EXTRA_S in ids
        assert bug_report.KIND_NO_CHIP in ids
        assert bug_report.KIND_OTHER in ids
