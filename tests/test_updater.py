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


def test_feed_is_anonymous_and_public():
    src = Path(up.__file__).read_text(encoding="utf-8")
    assert "Authorization" not in src
    assert "api.github.com" not in src
    assert "gho_" not in src and "ghp_" not in src
    assert up.FEED_URL.startswith("https://github.com/test4testUnlimit/Bonjur-epta/")
    # the private repo holds the poisoned history — never point a client at it
    assert "Bonjur-epta-private" not in src
