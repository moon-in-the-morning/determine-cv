#!/usr/bin/env python3
"""One-off migration: single document with include flags → library + documents.

    python3 db/migrate_to_documents.py

The library (entry, bullet, skill) loses its document-facing columns —
`section_id`, `include`, and the per-row `sort_order` that only meant anything
inside one arrangement. Those move into `doc_entry`, `doc_bullet`, `doc_skill`.

Your current arrangement is preserved as a document called "Full CV", so
nothing you have filed is lost. New documents you create start blank.

Unfiled entries stay in the library and belong to no document — which is now
just what "not selected" means, rather than a special state.

The old file is copied aside first, so this is reversible by moving it back.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "cv.db"
SCHEMA = HERE / "schema.sql"
BACKUP = HERE / "cv.db.pre-documents"

DOC_SLUG = "full-cv"
DOC_TITLE = "Full CV"


def main() -> None:
    if not DB.exists():
        sys.exit(f"no database at {DB}")

    old = sqlite3.connect(DB)
    old.row_factory = sqlite3.Row

    if old.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='document'").fetchone():
        sys.exit("already migrated — this database already has a `document` table")

    shutil.copy2(DB, BACKUP)
    print(f"backup       {BACKUP.name}")

    tmp = HERE / "cv.db.migrating"
    tmp.unlink(missing_ok=True)
    new = sqlite3.connect(tmp)
    new.executescript(SCHEMA.read_text())

    with new:
        copy_library(old, new)
        stats = build_document(old, new)

    new.close()
    old.close()
    tmp.replace(DB)

    print(f"library      {stats['entries']} entries, {stats['bullets']} bullets, "
          f"{stats['skills']} skills")
    print(f"document     {DOC_TITLE!r}: {stats['sections']} headings, "
          f"{stats['placed']} entries, {stats['doc_skills']} skills")
    print(f"             {stats['hidden']} bullets suppressed, "
          f"{stats['loose']} entries left in the library only")
    print(f"\nwrote        {DB}")


def copy_library(old, new) -> None:
    """Experience moves across untouched, minus the columns that were really
    about one particular arrangement."""
    p = old.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    new.execute("INSERT INTO profile (id, full_name, legal_name, pronouns, summary) "
                "VALUES (1, ?, ?, ?, ?)",
                (p["full_name"], p["legal_name"], p["pronouns"], p["summary"]))

    for c in old.execute("SELECT * FROM contact ORDER BY sort_order, id"):
        new.execute("INSERT INTO contact (id, profile_id, kind, value, display, sort_order) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (c["id"], c["profile_id"], c["kind"], c["value"], c["display"],
                     c["sort_order"]))

    for e in old.execute("SELECT * FROM entry ORDER BY id"):
        new.execute(
            "INSERT INTO entry (id, kind, org, title, note, location, date_display, "
            "start_ym, end_ym, is_current, url, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (e["id"], e["kind"], e["org"], e["title"], e["note"], e["location"],
             e["date_display"], e["start_ym"], e["end_ym"], e["is_current"], e["url"],
             e["summary"]))

    for b in old.execute("SELECT * FROM bullet ORDER BY entry_id, sort_order, id"):
        new.execute("INSERT INTO bullet (id, entry_id, text, sort_order) VALUES (?,?,?,?)",
                    (b["id"], b["entry_id"], b["text"], b["sort_order"]))

    for s in old.execute("SELECT * FROM skill ORDER BY category, sort_order, id"):
        new.execute("INSERT INTO skill (id, name, category, detail, sort_order) "
                    "VALUES (?,?,?,?,?)",
                    (s["id"], s["name"], s["category"], s["detail"], s["sort_order"]))

    for r in old.execute("SELECT * FROM entry_skill ORDER BY entry_id, skill_id"):
        new.execute("INSERT INTO entry_skill (entry_id, skill_id) VALUES (?, ?)",
                    (r["entry_id"], r["skill_id"]))


def build_document(old, new) -> dict:
    """Rebuild the current arrangement as one saved document."""
    density = 1.0
    paper = "us-letter"
    profile_columns = {r[1] for r in old.execute("PRAGMA table_info(profile)")}
    if {"density", "paper"} <= profile_columns:
        row = old.execute("SELECT density, paper FROM profile WHERE id = 1").fetchone()
        density, paper = row["density"], row["paper"]

    doc = new.execute(
        "INSERT INTO document (slug, title, density, paper, notes) VALUES (?, ?, ?, ?, ?)",
        (DOC_SLUG, DOC_TITLE, density, paper,
         "Everything, in the arrangement this database was migrated from.")).lastrowid

    section_map = {}
    for s in old.execute("SELECT * FROM section ORDER BY sort_order, id"):
        section_map[s["id"]] = new.execute(
            "INSERT INTO section (document_id, heading, style, sort_order, include) "
            "VALUES (?, ?, ?, ?, ?)",
            (doc, s["heading"], s["style"], s["sort_order"], s["include"])).lastrowid

    placed = loose = 0
    for e in old.execute("SELECT * FROM entry ORDER BY id"):
        target = section_map.get(e["section_id"]) if e["section_id"] else None
        if target is None:
            loose += 1
            continue
        new.execute(
            "INSERT INTO doc_entry (document_id, entry_id, section_id, sort_order, include) "
            "VALUES (?, ?, ?, ?, ?)",
            (doc, e["id"], target, e["sort_order"], e["include"]))
        placed += 1

    hidden = 0
    for b in old.execute("SELECT id FROM bullet WHERE include = 0"):
        new.execute("INSERT INTO doc_bullet (document_id, bullet_id, include) VALUES (?, ?, 0)",
                    (doc, b["id"]))
        hidden += 1

    doc_skills = 0
    for s in old.execute("SELECT id FROM skill WHERE include = 1 ORDER BY id"):
        new.execute("INSERT INTO doc_skill (document_id, skill_id) VALUES (?, ?)", (doc, s["id"]))
        doc_skills += 1

    count = lambda table: new.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return {"sections": len(section_map), "placed": placed, "loose": loose,
            "hidden": hidden, "doc_skills": doc_skills,
            "entries": count("entry"), "bullets": count("bullet"), "skills": count("skill")}


if __name__ == "__main__":
    main()
