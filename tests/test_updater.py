"""Update decision logic — the part that must never act on a bad feed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import updater as up


def _manifest(**over) -> str:
    data = {
        "version": "3.2.0",
        "url": "https://github.com/o/r/releases/download/v3.2.0/BonjurLauncher_3.2.0.exe",
        "sha256": "ab" * 32,
        "notes": "- one\n- two",
        "date": "2026-08-26",
    }
    data.update(over)
    return json.dumps(data)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.1.2", (3, 1, 2)),
        ("v3.1.2", (3, 1, 2)),
        ("  3.1  ", (3, 1)),
        ("3.1.2.4", (3, 1, 2, 4)),
        ("", None),
        (None, None),
        ("3.1.2-beta", None),
        ("latest", None),
    ],
)
def test_parse_version(text, expected):
    assert up.parse_version(text) == expected


def test_compare_pads_missing_components():
    assert up.compare((3, 1), (3, 1, 0)) == 0
    assert up.compare((3, 2), (3, 1, 9)) == 1
    assert up.compare((3, 1, 9), (3, 2)) == -1
    # 3.10 beats 3.9 — string compare would get this wrong
    assert up.compare((3, 10, 0), (3, 9, 9)) == 1


def test_decide_update_available():
    info = up.parse_manifest(_manifest())
    assert up.decide("3.1.2", info) == up.UPDATE_AVAILABLE


def test_decide_up_to_date_and_newer_local():
    info = up.parse_manifest(_manifest())
    assert up.decide("3.2.0", info) == up.UP_TO_DATE
    assert up.decide("4.0.0", info) == up.UP_TO_DATE


def test_decide_dismissed_only_for_that_exact_version():
    info = up.parse_manifest(_manifest())
    assert up.decide("3.1.2", info, skipped="3.2.0") == up.DISMISSED
    assert up.decide("3.1.2", info, skipped="3.1.9") == up.UPDATE_AVAILABLE


def test_decide_unreadable_local_version_still_updates():
    info = up.parse_manifest(_manifest())
    assert up.decide("", info) == up.UPDATE_AVAILABLE


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "not json",
        "[]",
        json.dumps({"url": "https://x/y.exe"}),  # no version
        _manifest(version="latest"),
        _manifest(url="http://insecure/y.exe"),  # plain http
        _manifest(url=""),
    ],
)
def test_bad_manifest_is_never_up_to_date(text):
    info = up.parse_manifest(text)
    assert info is None
    assert up.decide("3.1.2", info) == up.BAD_MANIFEST


def test_manifest_tolerates_a_missing_hash():
    info = up.parse_manifest(_manifest(sha256=""))
    assert info is not None
    assert info["sha256"] == ""


DAY = 24 * 3600


@pytest.mark.parametrize(
    ("last", "now", "expected"),
    [
        (0.0, 1_000_000.0, True),          # never checked
        (None, 1_000_000.0, True),         # missing / null in settings.json
        ("junk", 1_000_000.0, True),       # hand-edited settings
        (1_000_000.0, 1_000_000.0 + 60, False),
        (1_000_000.0, 1_000_000.0 + DAY - 1, False),
        (1_000_000.0, 1_000_000.0 + DAY, True),
        (1_000_000.0, 999_000.0, True),    # stamp in the future — clock moved
    ],
)
def test_due(last, now, expected):
    assert up.due(last, now) is expected


def test_format_notes_bullets_every_line():
    out = up.format_notes("- fixed a\nadded b\n\n* c")
    assert out.splitlines() == ["• fixed a", "• added b", "• c"]


def test_format_notes_empty():
    assert up.format_notes("") == ""
    assert up.format_notes(None) == ""


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x/y/BonjurLauncher_3.2.0.exe", "BonjurLauncher_3.2.0.exe"),
        ("https://x/y/BonjurLauncher.exe?token=1", "BonjurLauncher.exe"),
        ("https://x/y/readme.txt", ""),
        ("https://x/y/", ""),
    ],
)
def test_asset_name(url, expected):
    assert up.asset_name(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://x/y/..%5Cevil.exe",
        "https://x/y/.hidden.exe",
        "https://x/y/sub%2Fdir.exe",
    ],
)
def test_asset_name_rejects_anything_path_like(url):
    # A hostile feed must not be able to choose where we write.
    assert up.asset_name(url) == ""


def test_launcher_path_prefers_the_unversioned_exe(tmp_path, monkeypatch):
    (tmp_path / "BonjurLauncher_3.1.4.exe").write_bytes(b"old")
    (tmp_path / "BonjurLauncher.exe").write_bytes(b"new")
    monkeypatch.setattr(up, "install_dir", lambda: tmp_path)
    assert up.launcher_path().name == "BonjurLauncher.exe"


def test_launcher_path_falls_back_to_a_versioned_exe(tmp_path, monkeypatch):
    (tmp_path / "BonjurLauncher_3.1.4.exe").write_bytes(b"old")
    monkeypatch.setattr(up, "install_dir", lambda: tmp_path)
    assert up.launcher_path().name == "BonjurLauncher_3.1.4.exe"


def test_launcher_path_is_none_in_a_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "install_dir", lambda: tmp_path)
    assert up.launcher_path() is None


def test_apply_sweeps_leftover_versioned_launchers(tmp_path, monkeypatch):
    """A stale per-version exe would reinstall its own payload — a silent downgrade."""
    from app import restart

    (tmp_path / "BonjurLauncher_3.1.4.exe").write_bytes(b"old")
    armed = []

    def fake_download(url, dest, sha256="", timeout=120.0):
        dest.write_bytes(b"x" * 60_000)
        return True

    monkeypatch.setattr(up, "install_dir", lambda: tmp_path)
    monkeypatch.setattr(up, "download", fake_download)
    monkeypatch.setattr(restart, "schedule_run", lambda argv, cwd: armed.append(argv) or True)

    info = up.parse_manifest(_manifest(url="https://x/y/BonjurLauncher.exe"))
    assert up.apply(info) is True
    assert sorted(p.name for p in tmp_path.glob("*.exe")) == ["BonjurLauncher.exe"]
    assert armed and armed[0][0].endswith("BonjurLauncher.exe")


def test_apply_leaves_nothing_behind_when_the_download_fails(tmp_path, monkeypatch):
    (tmp_path / "BonjurLauncher_3.1.4.exe").write_bytes(b"old")
    monkeypatch.setattr(up, "install_dir", lambda: tmp_path)
    monkeypatch.setattr(up, "download", lambda *a, **k: False)

    info = up.parse_manifest(_manifest(url="https://x/y/BonjurLauncher.exe"))
    assert up.apply(info) is False
    # the old launcher must survive a failed update
    assert (tmp_path / "BonjurLauncher_3.1.4.exe").is_file()
    assert not list(tmp_path.glob("*.part"))


def test_feed_is_anonymous_and_public():
    src = Path(up.__file__).read_text(encoding="utf-8")
    assert "Authorization" not in src
    assert "api.github.com" not in src
    assert "gho_" not in src and "ghp_" not in src
    assert up.FEED_URL.startswith("https://github.com/test4testUnlimit/Bonjur-epta/")
    # the private repo holds the poisoned history — never point a client at it
    assert "Bonjur-epta-private" not in src
