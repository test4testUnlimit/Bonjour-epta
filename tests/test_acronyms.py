"""Acronym engine: detection, inline expansion, ranking, and the shipped packs.

Everything here runs without Tk and without the local packs — tests that touch
the index point LOCAL_DIR at an empty temp dir so results are the same on a
machine that has ~/.bonjour-epta/packs/local.json and one that does not.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.acronyms import detect, inline, resolve, store  # noqa: E402
from app.chip_offer import should_offer_chip  # noqa: E402


def keys(text: str) -> set[str]:
    """Candidates the engine would report as unknown — noise excluded."""
    return {c.key for c in detect.candidates(text) if not c.noise}


def all_keys(text: str) -> set[str]:
    """Every candidate, including the ones only a dictionary hit rescues."""
    return {c.key for c in detect.candidates(text)}


def make_index(rows: list[dict]) -> store.Index:
    return store.Index([store.Entry.from_dict(r, pack=r.pop("_pack", "test"),
                                              priority=r.pop("_prio", 12)) for r in rows])


@pytest.fixture(scope="module")
def repo_packs():
    """Only the packs that ship in git — never the user's local ones."""
    return [store._read_pack(f, "repo") for f in sorted(store.BUILTIN_DIR.glob("*.json"))]


@pytest.fixture(scope="module")
def repo_index(repo_packs):
    return store.Index([e for p in repo_packs for e in p.entries])


@pytest.fixture(scope="module")
def imp():
    from app.acronyms import importer

    return importer


class TestDetect:
    def test_plain_acronyms(self):
        assert keys("Send the PPAP by EOW") == {"PPAP", "EOW"}

    def test_compound_shapes(self):
        assert "GD&T" in keys("Check the GD&T callout")
        assert "GC-MS" in keys("Run GC-MS on the residue")
        assert "I/O" in keys("The I/O card is dead")
        assert "TL;DR" in keys("TL;DR it works")

    def test_digit_led(self):
        assert "8D" in keys("Open an 8D for this")
        assert "5S" in keys("The 5S audit failed")

    def test_dotted(self):
        assert "FAI" in keys("Waiting on the F.A.I. report")

    def test_cell_format_is_noise_until_the_dictionary_claims_it(self):
        cand = {c.key: c for c in detect.candidates("Line B uses 18650 cells")}
        assert "18650" in cand and cand["18650"].noise
        assert "B" not in cand  # single letter is not an acronym

    def test_stop_words(self):
        for w in ("THE", "USA", "PDF", "OK", "URL"):
            assert w not in all_keys(f"look at {w} please")

    def test_units_after_a_number_are_dropped(self):
        assert "MM" not in all_keys("tolerance is 5 MM")
        assert "KW" not in all_keys("draws 400 KW")
        assert "DC" not in all_keys("charges at 250 DC")
        assert "DC" in all_keys("the DC bus is live")  # no number in front

    def test_two_letter_romans_stay_reportable(self):
        # DC / MM / MI read as roman numerals but are acronyms far more often
        assert "DC" in keys("the DC bus is live")
        assert "IX" not in keys("see section IX below")

    def test_shouting_is_flagged_not_reported(self):
        loud = "PLEASE STOP THE LINE RIGHT NOW THE FIXTURE IS BROKEN AND PARTS ARE FALLING OFF"
        assert keys(loud) == set()

    def test_roman_numerals_are_noise(self):
        cand = {c.key: c for c in detect.candidates("see section XIV and XVII")}
        assert all(cand[k].noise for k in ("XIV", "XVII") if k in cand)

    def test_paths_and_code_produce_nothing_useful(self):
        assert quick_scan_is_zero("C:\\Projects\\app.py")

    def test_dates_and_times_are_not_compounds(self):
        assert keys("meeting 2024-11-05 at 10:30") == set()


def quick_scan_is_zero(text: str) -> bool:
    return resolve.quick_scan(text) == 0


class TestInline:
    def test_initials_match_skips_fillers(self):
        assert inline.initials_match("BOM", "Bill of Materials")
        assert inline.initials_match("CMM", "Coordinate Measuring Machine")
        assert not inline.initials_match("CMM", "Corrective Maintenance")

    def test_one_word_can_supply_several_letters(self):
        assert inline.initials_match("HiPot", "High Potential")

    def test_expansion_after_the_acronym(self):
        got = inline.inline_map("The FAI (First Article Inspection) is due")
        assert got["FAI"] == "First Article Inspection"

    def test_expansion_before_the_acronym(self):
        got = inline.inline_map("Coordinate Measuring Machine (CMM) results look fine")
        assert got["CMM"] == "Coordinate Measuring Machine"

    def test_unrelated_parenthesis_is_ignored(self):
        assert inline.inline_map("the part (see drawing) is fine") == {}

    def test_inline_works_with_an_empty_dictionary(self):
        rep = resolve.explain("Widget Alignment Gauge (WAG) failed", idx=store.EMPTY_INDEX)
        hit = next(h for h in rep.hits if h.key == "WAG")
        assert hit.inline == "Widget Alignment Gauge"
        assert not hit.entries


class TestIndex:
    def test_aliases_resolve_to_the_same_entry(self):
        idx = make_index([{"term": "GR&R", "expansion": "Gauge R&R", "aliases": ["GRR"]}])
        assert idx.get("GRR")[0].expansion == "Gauge R&R"

    def test_plural_and_possessive_fall_back(self):
        idx = make_index([{"term": "PPAP", "expansion": "Production Part Approval Process"}])
        assert idx.get("PPAPS") and idx.get("PPAP'S")

    def test_same_term_and_expansion_is_deduped_across_packs(self):
        idx = make_index([
            {"term": "FA", "expansion": "Final Assembly", "_pack": "local", "_prio": 30},
            {"term": "FA", "expansion": "Final  assembly", "_pack": "repo", "_prio": 11},
        ])
        assert len(idx.get("FA")) == 1
        assert idx.get("FA")[0].pack == "local"

    def test_multi_word_terms_become_phrases(self):
        idx = make_index([{"term": "Takt time", "expansion": "Takt"}])
        assert "TAKT TIME" in idx.phrases
        hits = detect.dict_hits("what is the takt time here", idx.phrase_re, idx.literal_re)
        assert [c.key for c in hits] == ["TAKT TIME"]

    def test_odd_spellings_become_literals(self):
        idx = make_index([
            {"term": "Cpk", "expansion": "Process capability index"},
            {"term": "Kanban", "expansion": "Pull replenishment"},
            {"term": "PPAP", "expansion": "Production Part Approval Process"},
        ])
        assert set(idx.literals) == {"Cpk", "Kanban"}  # PPAP needs no help
        found = {c.key for c in detect.dict_hits("Cpk is 1.4 on the kanban loop",
                                                 idx.phrase_re, idx.literal_re)}
        assert found == {"CPK", "KANBAN"}  # long words match any case

    def test_short_literals_keep_their_case(self):
        idx = make_index([{"term": "Ra", "expansion": "Roughness average"}])
        assert [c.key for c in detect.dict_hits("Ra 1.6", idx.phrase_re, idx.literal_re)] == ["RA"]
        assert detect.dict_hits("ra ra ra", idx.phrase_re, idx.literal_re) == []


class TestResolve:
    @pytest.fixture
    def poly(self):
        return make_index([
            {"term": "FA", "expansion": "Final Assembly", "domain": ["manufacturing"]},
            {"term": "FA", "expansion": "Failure Analysis", "domain": ["lab", "metrology"]},
            {"term": "UPH", "expansion": "Units Per Hour", "domain": ["manufacturing"]},
            {"term": "SEM", "expansion": "Scanning Electron Microscope", "domain": ["lab"]},
        ])

    def test_domain_context_picks_the_meaning(self, poly):
        line = resolve.explain("FA line UPH is low", idx=poly)
        assert line.hits[0].best.expansion == "Final Assembly"
        lab = resolve.explain("FA of the failed cell with SEM", idx=poly)
        assert lab.hits[0].best.expansion == "Failure Analysis"

    def test_no_context_leaves_it_ambiguous(self, poly):
        rep = resolve.explain("FA is pending", idx=poly)
        assert rep.hits[0].ambiguous
        assert len(rep.hits[0].entries) == 2

    def test_pack_priority_breaks_the_tie(self):
        idx = make_index([
            {"term": "FY", "expansion": "Fiscal Year", "_pack": "corp", "_prio": 11},
            {"term": "FY", "expansion": "Final Yield", "_pack": "local", "_prio": 30},
        ])
        assert resolve.explain("FY is 96%", idx=idx).hits[0].best.expansion == "Final Yield"

    def test_unknown_is_reported_without_guessing(self, poly):
        rep = resolve.explain("check with XGV about it", idx=poly)
        assert rep.unknown == ["XGV"]
        assert not rep.hits

    def test_noise_candidates_never_reach_unknown(self, poly):
        assert resolve.explain("Line B uses 18650 cells", idx=poly).unknown == []

    def test_empty_text(self, poly):
        rep = resolve.explain("   ", idx=poly)
        assert not rep and rep.count == 0

    def test_quick_scan_counts_known_only(self, poly):
        assert resolve.quick_scan("FA line UPH is low", idx=poly) == 2
        assert resolve.quick_scan("The weather is nice today", idx=poly) == 0

    def test_quick_scan_gates_on_junk(self, poly):
        assert resolve.quick_scan("C:\\Projects\\Bonjur-epta\\app\\ui.py", idx=poly) == 0

    def test_explain_does_not_gate_on_junk(self, poly):
        # the main window is an explicit user action — always answer
        assert resolve.explain("FA UPH", idx=poly).count == 2

    def test_stays_under_the_latency_budget(self, poly):
        para = "Need FPY data from MOS before the PPAP submission. " * 12
        assert resolve.explain(para, idx=poly).ms < 25.0


class TestShippedPacks:
    """The JSON that travels in git."""

    def test_all_packs_parse(self, repo_packs):
        assert repo_packs, "no packs found in app/acronyms/data"
        assert [p.id for p in repo_packs if p.error] == []

    def test_every_entry_has_a_russian_line(self, repo_packs):
        missing = [f"{p.id}:{e.term}" for p in repo_packs for e in p.entries if not e.ru]
        assert missing == []

    def test_no_duplicate_term_and_expansion(self, repo_packs):
        seen: dict[tuple[str, str], str] = {}
        dupes = []
        for p in repo_packs:
            for e in p.entries:
                if e.ident in seen:
                    dupes.append(f"{e.term} in {p.id} and {seen[e.ident]}")
                seen[e.ident] = p.id
        assert dupes == []

    def test_every_term_is_findable(self, repo_index):
        """A term nothing can spot is dead weight in the file."""
        missing = []
        for entries in repo_index.by_key.values():
            for e in entries:
                if not resolve.explain(f"look at {e.term} here", idx=repo_index).hits:
                    missing.append(f"{e.pack}:{e.term}")
        assert sorted(set(missing)) == []

    def test_real_sentences_resolve(self, repo_index):
        rep = resolve.explain("Run GR&R per MSA before SOP", idx=repo_index)
        assert {h.key for h in rep.hits} == {"GR&R", "MSA", "SOP"}

    def test_polysemy_in_the_shipped_data(self, repo_index):
        line = resolve.explain("FA line UPH is low, DT up", idx=repo_index)
        assert next(h for h in line.hits if h.key == "FA").best.expansion == "Final Assembly"
        lab = resolve.explain("FA of the failed cell with SEM and FTIR", idx=repo_index)
        assert next(h for h in lab.hits if h.key == "FA").best.expansion == "Failure Analysis"

    def test_plain_english_finds_nothing(self, repo_index):
        assert resolve.explain("The weather is nice today", idx=repo_index).count == 0


class TestImportClassifier:
    """scripts/import_confluence.py — internal is the default verdict."""

    def verdict(self, imp, term, expansion, notes=""):
        row = imp.Row(term=term, expansion=expansion, notes=notes)
        imp.classify(row, imp.repo_pairs())
        return row.verdict

    def test_internal_url_stays_local(self, imp):
        assert self.verdict(imp, "MOS", "Manufacturing Operating System",
                            "https://wiki.example.com/confluence/x") == "internal"

    def test_site_and_product_stay_local(self, imp):
        assert self.verdict(imp, "NP1", "North Plant line one") == "internal"
        assert self.verdict(imp, "XZ", "XZ-40 crossover") == "internal"

    def test_personal_commentary_stays_local(self, imp):
        assert self.verdict(imp, "ACME", "Equipment integrator",
                            "really screwed up the cell line 1.0") == "internal"

    def test_local_markers_file_is_read_and_bad_rows_skipped(self, imp, tmp_path):
        f = tmp_path / "internal_markers.json"
        f.write_text(json.dumps([
            ["site", r"\bnorth ?plant\b"],
            ["broken", "(unclosed"],
            "not a pair",
        ]), encoding="utf-8")
        with patch.object(imp, "LOCAL_MARKERS_FILE", f):
            assert imp.local_markers() == [("site", r"\bnorth ?plant\b")]

    def test_missing_local_markers_file_is_not_an_error(self, imp, tmp_path):
        with patch.object(imp, "LOCAL_MARKERS_FILE", tmp_path / "nope.json"):
            assert imp.local_markers() == []

    def test_a_local_marker_beats_a_generic_hint(self, imp):
        """Without the marker, "process control" would talk this row into public."""
        row = "process control rack at North Plant"
        assert self.verdict(imp, "PCR", "Process Control Rack", row) == "public"
        marked = [*imp._INTERNAL_RE, ("site", re.compile(r"\bnorth ?plant\b", re.I))]
        with patch.object(imp, "_INTERNAL_RE", marked):
            assert self.verdict(imp, "PCR", "Process Control Rack", row) == "internal"

    def test_unknown_defaults_to_local(self, imp):
        assert self.verdict(imp, "ZZZ", "Some Internal Thing") == "internal"

    def test_generic_industry_term_is_a_public_candidate(self, imp):
        assert self.verdict(imp, "TCU", "Torque Control Unit",
                            "holds the calibration for the torque tool") == "public"

    def test_already_shipped_rows_are_skipped(self, imp):
        assert self.verdict(imp, "SPC", "Statistical Process Control") == "known"

    def test_spelling_variants_still_count_as_shipped(self, imp):
        assert self.verdict(imp, "FPY", "First-Pass Yield") == "known"

    def test_parser_handles_the_loose_browser_copy(self, imp):
        raw = "CLT\n\nComponent Level Test\t\nDU\n\nDrive Unit\tConverts battery energy to torque.\n"
        rows = {r.term: r for r in imp.parse(raw)}
        assert rows["CLT"].expansion == "Component Level Test"
        assert rows["DU"].expansion == "Drive Unit"
        assert "torque" in rows["DU"].notes

    def test_parser_handles_proper_tsv(self, imp):
        raw = "Acronym/Term\tExpansion\tNotes\nM3Y\tModel 3/Y\tCommon battery platform\n"
        rows = imp.parse(raw)
        assert len(rows) == 1 and rows[0].term == "M3Y"

    def test_commentary_without_a_definition_is_dropped(self, imp):
        assert imp.parse("PMI\n\nlol, that finally died\t\n") == []

    def test_a_definition_line_is_not_mistaken_for_a_term(self, imp):
        rows = imp.parse("26650\n\n26650 Battery Cells\t\naka 26-650 Battery Cells.\n")
        assert [r.term for r in rows] == ["26650"]


class TestPackDiscovery:
    def test_underscore_files_are_not_packs(self, tmp_path):
        (tmp_path / "real.json").write_text(
            json.dumps({"id": "real", "entries": [{"term": "AA", "expansion": "Alpha"}]}),
            encoding="utf-8",
        )
        (tmp_path / "_scratch.json").write_text(
            json.dumps({"id": "scratch", "entries": [{"term": "BB", "expansion": "Beta"}]}),
            encoding="utf-8",
        )
        with patch.object(store, "LOCAL_DIR", tmp_path), patch.object(store, "BUILTIN_DIR", tmp_path / "none"):
            assert [p.id for p in store.discover_packs()] == ["real"]

    def test_a_broken_pack_does_not_kill_the_others(self, tmp_path):
        (tmp_path / "good.json").write_text(
            json.dumps({"id": "good", "entries": [{"term": "AA", "expansion": "Alpha"}]}),
            encoding="utf-8",
        )
        (tmp_path / "bad.json").write_text("{ not json", encoding="utf-8")
        with patch.object(store, "LOCAL_DIR", tmp_path), patch.object(store, "BUILTIN_DIR", tmp_path / "none"):
            found = {p.id: p for p in store.discover_packs()}
        assert found["bad"].error and not found["good"].error


class TestChipGate:
    """Russian text full of English acronyms must still get a chip offered."""

    def _scan(self, text: str) -> bool:
        return resolve.quick_scan(text) > 0

    def test_russian_with_acronyms_offers_the_chip(self):
        assert should_offer_chip(
            "Отправь PPAP до EOW", target_lang="ru", acronym_scan=self._scan
        )

    def test_plain_russian_still_skipped(self):
        assert not should_offer_chip(
            "Погода сегодня хорошая", target_lang="ru", acronym_scan=self._scan
        )

    def test_scanner_is_not_asked_about_english(self):
        asked = []

        def scan(text: str) -> bool:
            asked.append(text)
            return True

        assert should_offer_chip("Send the PPAP by EOW", target_lang="ru", acronym_scan=scan)
        assert asked == []

    def test_no_scanner_keeps_the_old_answer(self):
        assert not should_offer_chip("Отправь PPAP до EOW", target_lang="ru")

    def test_a_throwing_scanner_does_not_break_the_chip(self):
        def boom(_text: str) -> bool:
            raise RuntimeError("index unavailable")

        assert not should_offer_chip("Отправь PPAP до EOW", target_lang="ru", acronym_scan=boom)

    def test_code_is_still_junk_even_with_acronyms(self):
        assert not should_offer_chip(
            r"C:\Projects\PPAP\app.py", target_lang="ru", acronym_scan=self._scan
        )
