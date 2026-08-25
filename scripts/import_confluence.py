#!/usr/bin/env python3
"""Confluence acronym table -> acronym pack.

Reads a table copied out of Confluence (TSV, or the loose multi-line mess that
a browser copy produces) and writes a JSON pack.

Every row is classified public / internal. **Internal is the default** — a row
has to actively prove it is generic industry vocabulary to be called public.
Internal rows go to the local pack (outside the repo, never committed); public
candidates go to a separate review file that a human reads before anything is
copied into app/acronyms/data/.

    python scripts/import_confluence.py c:/tmp/raw-table.txt --pack local
    python scripts/import_confluence.py table.tsv --pack local --dry-run --explain

Re-running is safe: hand-written "ru" / "where" text in an existing output pack
is preserved unless --overwrite is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.acronyms.importer import (  # noqa: E402
    classify,
    guess_domains,
    load_keep,
    parse,
    repo_pairs,
    to_entry,
    write_pack,
)
from app.acronyms.store import LOCAL_DIR  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="TSV / text dump of the Confluence table")
    ap.add_argument("--pack", default="local", help="pack id for internal rows (default: local)")
    ap.add_argument("--title", default="", help="human title of the pack")
    ap.add_argument("--priority", type=int, default=30)
    ap.add_argument("--out", type=Path, default=None, help="default: ~/.bonjur-epta/packs/<pack>.json")
    ap.add_argument("--public-out", type=Path, default=None,
                    help="review file for public candidates (default: next to --out, _<pack>_public.json)")
    ap.add_argument("--overwrite", action="store_true", help="drop existing ru/where instead of keeping them")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--explain", action="store_true", help="print the verdict for every row")
    args = ap.parse_args()

    text = args.input.read_text(encoding="utf-8", errors="replace")
    rows = parse(text)
    if not rows:
        print("no rows parsed — is the input a copied table?", file=sys.stderr)
        return 1

    known = repo_pairs()
    for r in rows:
        classify(r, known)
        r.domain = guess_domains(r)

    internal = [r for r in rows if r.verdict == "internal"]
    public = [r for r in rows if r.verdict == "public"]
    already = [r for r in rows if r.verdict == "known"]

    out = args.out or (LOCAL_DIR / f"{args.pack}.json")
    pub_out = args.public_out or (out.parent / f"_{args.pack}_public.json")

    if args.explain:
        mark = {"public": "PUB ", "internal": "loc ", "known": "  = "}
        for r in rows:
            print(f"{mark[r.verdict]}{r.term:<12} {r.expansion[:52]:<52} {','.join(r.reasons)}")

    print(f"parsed {len(rows)} rows: {len(internal)} local, {len(public)} public candidates, "
          f"{len(already)} already in repo packs (skipped)")
    print(f"  local pack  -> {out}")
    print(f"  review file -> {pub_out}   (read it before copying anything into app/acronyms/data/)")

    if args.dry_run:
        return 0

    keep = load_keep(out, args.overwrite)
    write_pack(out, args.pack, args.title or args.pack.upper(), args.priority,
               [to_entry(r, keep) for r in internal])
    write_pack(pub_out, f"{args.pack}_public", f"{args.pack} — public candidates, needs review", 10,
               [to_entry(r, {}) for r in public])
    kept = sum(1 for r in internal if keep.get((norm_key(r.term), norm_key(r.expansion)), {}).get("ru"))
    if kept:
        print(f"  kept {kept} hand-written ru translations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
