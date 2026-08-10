#!/usr/bin/env python3
"""One-off migration: multi-variant schema → single document with include flags.

Reads the old cv.db, writes a new one against the current schema.sql. Nothing
is dropped in place — the old file is copied aside first, so this is reversible
by moving the backup back.

    python3 db/migrate_to_single_document.py

What it does:
  · variant / variant_entry / variant_bullet / variant_skill disappear. What
    the full CV selected becomes include = 1; what only the resume selected
    becomes include = 0 or is dropped.
  · section loses variant_id and gains style + include. Profile and Skills
    become real sections so they can be reordered and switched off like any
    other.
  · entry gains section_id (its heading, directly) and sort_order.
  · The four resume-worded bullets are DELETED, per instruction. The CV
    wording for those two entries is untouched.
  · Entries the CV never showed are imported UNFILED (section_id IS NULL):
    on record, printed nowhere, one dropdown from being filed.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "cv.db"
SCHEMA = HERE / "schema.sql"
BACKUP = HERE / "cv.db.pre-single-document"

# Sections in print order. The six existing headings keep their content; the
# two new ones make Profile and Skills switchable like everything else.
SECTIONS = [
    # (new sort_order, heading,                             style,     old_id)
    (1, "Profile",                            "profile", None),
    (2, "Research Experience",                "entries", 1),
    (3, "Teaching",                           "entries", 2),
    (4, "Non-Profit Leadership and Organizing", "entries", 3),
    (5, "Education",                          "entries", 4),
    (6, "Skills",                             "skills",  None),
    (7, "Writing and Presentations",          "entries", 5),
    (8, "Additional Experience",              "entries", 6),
]


def main() -> None:
    if not DB.exists():
        sys.exit(f"no database at {DB}")

    old = sqlite3.connect(DB)
    old.row_factory = sqlite3.Row

    if not old.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='variant'"
    ).fetchone():
        sys.exit("already migrated — no `variant` table in this database")

    shutil.copy2(DB, BACKUP)
    print(f"backup      {BACKUP.name}")

    tmp = HERE / "cv.db.migrating"
    tmp.unlink(missing_ok=True)
    new = sqlite3.connect(tmp)
    new.executescript(SCHEMA.read_text())

    with new:
        section_map = copy_sections(new)
        copy_profile(old, new)
        copy_contacts(old, new)
        placement = copy_entries(old, new, section_map)
        dropped = copy_bullets(old, new)
        off = copy_skills(old, new)
        copy_entry_skills(old, new)

    new.close()
    old.close()
    tmp.replace(DB)

    print(f"sections    {len(SECTIONS)}")
    print(f"entries     {placement['filed']} filed, {placement['unfiled']} unfiled")
    print(f"bullets     {dropped} resume-worded bullets deleted")
    print(f"skills      {off} imported unticked (resume-only)")
    print(f"\nwrote       {DB}")


def copy_sections(new) -> dict[int, int]:
    """Insert the section list; return {old_section_id: new_section_id}."""
    mapping = {}
    for order, heading, style, old_id in SECTIONS:
        cur = new.execute(
            "INSERT INTO section (heading, style, sort_order, include) VALUES (?, ?, ?, 1)",
            (heading, style, order),
        )
        if old_id is not None:
            mapping[old_id] = cur.lastrowid
    return mapping


def copy_profile(old, new) -> None:
    p = old.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    v = old.execute("SELECT density, paper FROM variant WHERE slug = 'full-cv'").fetchone()
    new.execute(
        "INSERT INTO profile (id, full_name, legal_name, pronouns, summary, density, paper) "
        "VALUES (1, ?, ?, ?, ?, ?, ?)",
        (p["full_name"], p["legal_name"], p["pronouns"], p["summary"],
         v["density"] if v else 1.0, v["paper"] if v else "us-letter"),
    )


def copy_contacts(old, new) -> None:
    for c in old.execute("SELECT * FROM contact ORDER BY sort_order, id"):
        new.execute(
            "INSERT INTO contact (id, profile_id, kind, value, display, sort_order, include) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (c["id"], c["profile_id"], c["kind"], c["value"], c["display"], c["sort_order"]),
        )


def copy_entries(old, new, section_map) -> dict[str, int]:
    """Every entry comes across. The CV's placement becomes section_id +
    sort_order; anything the CV never showed arrives unfiled."""
    placed = {
        r["entry_id"]: (r["section_id"], r["sort_order"])
        for r in old.execute("SELECT entry_id, section_id, sort_order "
                             "FROM variant_entry WHERE variant_id = 1")
    }

    filed = unfiled = 0
    for e in old.execute("SELECT * FROM entry ORDER BY id"):
        old_section, order = placed.get(e["id"], (None, 0))
        section_id = section_map.get(old_section) if old_section else None
        filed, unfiled = (filed + 1, unfiled) if section_id else (filed, unfiled + 1)
        new.execute(
            "INSERT INTO entry (id, section_id, kind, org, title, note, location, "
            "date_display, start_ym, end_ym, is_current, url, summary, sort_order, include) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (e["id"], section_id, e["kind"], e["org"], e["title"], e["note"], e["location"],
             e["date_display"], e["start_ym"], e["end_ym"], e["is_current"], e["url"],
             e["summary"], order),
        )
    return {"filed": filed, "unfiled": unfiled}


def copy_bullets(old, new) -> int:
    """Drop the bullets written for the resume; keep everything else."""
    resume_only = {
        r["id"] for r in old.execute("""
            SELECT b.id FROM bullet b
            WHERE EXISTS (SELECT 1 FROM variant_bullet WHERE bullet_id = b.id AND variant_id = 2)
              AND NOT EXISTS (SELECT 1 FROM variant_bullet WHERE bullet_id = b.id AND variant_id = 1)
        """)
    }
    for b in old.execute("SELECT * FROM bullet ORDER BY entry_id, sort_order, id"):
        if b["id"] in resume_only:
            continue
        new.execute(
            "INSERT INTO bullet (id, entry_id, text, sort_order, include) VALUES (?,?,?,?,1)",
            (b["id"], b["entry_id"], b["text"], b["sort_order"]),
        )
    return len(resume_only)


def copy_skills(old, new) -> int:
    """All skills come across. Ones the CV never showed start unticked, so the
    generated document reads exactly as your CV does today."""
    on_cv = {r["skill_id"] for r in
             old.execute("SELECT skill_id FROM variant_skill WHERE variant_id = 1")}
    off = 0
    for s in old.execute("SELECT * FROM skill ORDER BY category, sort_order, id"):
        include = 1 if (not on_cv or s["id"] in on_cv) else 0
        off += 1 - include
        new.execute(
            "INSERT INTO skill (id, name, category, detail, sort_order, include) "
            "VALUES (?,?,?,?,?,?)",
            (s["id"], s["name"], s["category"], s["detail"], s["sort_order"], include),
        )
    return off


def copy_entry_skills(old, new) -> None:
    for r in old.execute("SELECT entry_id, skill_id FROM entry_skill ORDER BY entry_id, skill_id"):
        new.execute("INSERT INTO entry_skill (entry_id, skill_id) VALUES (?, ?)",
                    (r["entry_id"], r["skill_id"]))


if __name__ == "__main__":
    main()
