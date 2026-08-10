"""See what the parser made of a file, before any of it touches the database.

    python3 -m ingest reference-cvs/posner-miriam-ucla-dh.txt
    python3 -m ingest cv.generated.typ --gaps
    python3 -m ingest applications.zip --json

The number that matters is coverage: what fraction of the file's non-whitespace
characters some block claimed. `--gaps` prints the rest — the text the parser
read and could not place. That list is the point of the whole design, so it is
one flag away rather than buried.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import MissingDependency, parse

BAR = "─" * 72


def show(source, gaps: bool, limit: int) -> None:
    print(f"\n{source.name}  ·  {source.kind}  ·  {source.sha256[:12]}")
    if source.doc.notes:
        for note in source.doc.notes:
            print(f"  ! {note}")
        if not source.doc.text:
            return

    counts: dict[str, int] = {}
    for proposal in source.proposals:
        counts[proposal.target] = counts.get(proposal.target, 0) + 1
    tally = "  ".join(f"{n}× {t}" for t, n in sorted(counts.items())) or "nothing"

    unplaced = sum(len(g.text.strip()) for g in source.gaps)
    print(f"  coverage {source.coverage:6.1%}   {tally}"
          f"   {len(source.gaps)} unplaced span(s), {unplaced} chars")
    print(BAR)

    heading = None
    for proposal in source.proposals[:limit]:
        block_heading = source.doc.text[proposal.start:proposal.end]
        if proposal.target == "bullet":
            print(f"      • {proposal.payload['text'][:90]}")
            continue

        flag = " ?" if proposal.confidence < 0.7 else "  "
        if proposal.target == "entry":
            p = proposal.payload
            head = " — ".join(x for x in (p.get("org"), p.get("title")) if x)
            meta = "  ·  ".join(x for x in (p.get("date_display"),
                                            p.get("location")) if x)
            print(f"{flag}[{p.get('kind', '?'):11}] {head[:78]}")
            if meta:
                print(f"              {meta}")
            if p.get("note"):
                print(f"              {p['note'][:70]}")
        elif proposal.target == "skill":
            p = proposal.payload
            detail = f" ({p['detail']})" if p.get("detail") else ""
            print(f"{flag}[skill      ] {p['category']}: {p['name']}{detail}")
        elif proposal.target == "reference":
            print(f"{flag}[reference  ] {proposal.payload.get('name', '')}")
        elif proposal.target == "profile":
            print(f"{flag}[profile    ] {proposal.payload.get('full_name', '')}")
        elif proposal.target == "contact":
            p = proposal.payload
            print(f"{flag}[contact    ] {p['kind']}: {p['value'][:60]}")

    if len(source.proposals) > limit:
        print(f"      … {len(source.proposals) - limit} more")

    if gaps and source.gaps:
        print(f"\n  UNPLACED — {len(source.gaps)} span(s) the parser could not place")
        print(BAR)
        for gap in source.gaps[:limit]:
            snippet = " ".join(gap.text.split())[:100]
            print(f"  {gap.start:>7}  {snippet}")
        if len(source.gaps) > limit:
            print(f"      … {len(source.gaps) - limit} more")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m ingest", description=__doc__)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--gaps", action="store_true",
                    help="print the text no block claimed")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--limit", type=int, default=40, help="rows to show (default 40)")
    args = ap.parse_args(argv)

    failures = 0
    payload = []

    for path in args.paths:
        try:
            sources = parse(path.name, path.read_bytes())
        except MissingDependency as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            failures += 1
            continue
        except (OSError, ValueError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            failures += 1
            continue

        for source in sources:
            if args.json:
                payload.append({
                    "name": source.name, "kind": source.kind,
                    "sha256": source.sha256, "coverage": round(source.coverage, 4),
                    "notes": source.doc.notes,
                    "proposals": [
                        {"target": p.target, "payload": p.payload,
                         "start": p.start, "end": p.end, "rule": p.rule,
                         "parent": p.parent, "confidence": p.confidence,
                         "page": p.page, "quote": p.quote[:200]}
                        for p in source.proposals],
                    "gaps": [{"start": g.start, "end": g.end,
                              "text": g.text[:200]} for g in source.gaps],
                })
            else:
                show(source, args.gaps, args.limit)

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
