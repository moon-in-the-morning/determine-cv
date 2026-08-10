#!/usr/bin/env python3
"""One-off migration: add references, versions, and the itemized section styles.

    python3 db/migrate_add_references_and_versions.py

Nothing you have is touched. This adds four empty tables — `reference`,
`doc_reference`, `version`, `send` — and widens the set of section styles from
three to six, so a heading can render as an itemized list, a per-line skills
block, or a block of professional references.

The style change is a CHECK constraint, which SQLite cannot alter in place. So
this rebuilds the file from `schema.sql` and copies every row across, which is
also how `migrate_to_documents.py` did it. Column-for-column, in foreign-key
order; a column the old file doesn't have arrives at its schema default.

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
BACKUP = HERE / "cv.db.pre-versions"

# Parents before the rows that reference them.
CARRIED = ["profile", "contact", "entry", "bullet", "skill", "entry_skill",
           "document", "section", "doc_entry", "doc_bullet", "doc_skill"]


def columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def main() -> None:
    if not DB.exists():
        sys.exit(f"no database at {DB}")

    old = sqlite3.connect(DB)
    if old.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                   "AND name='version'").fetchone():
        sys.exit("already migrated — this database already has a `version` table")

    shutil.copy2(DB, BACKUP)
    print(f"backup       {BACKUP.name}")

    tmp = HERE / "cv.db.migrating"
    tmp.unlink(missing_ok=True)
    new = sqlite3.connect(tmp)
    new.executescript(SCHEMA.read_text())

    with new:
        for table in CARRIED:
            shared = [c for c in columns(new, table) if c in columns(old, table)]
            rows = old.execute(f"SELECT {', '.join(shared)} FROM {table}").fetchall()
            if not rows:
                continue
            holes = ", ".join("?" for _ in shared)
            new.executemany(
                f"INSERT INTO {table} ({', '.join(shared)}) VALUES ({holes})", rows)
            print(f"  {table:<12} {len(rows):>4} rows")

    broken = new.execute("PRAGMA foreign_key_check").fetchall()
    if broken:
        new.close()
        tmp.unlink(missing_ok=True)
        sys.exit(f"foreign keys would break: {broken} — nothing was changed")

    new.close()
    old.close()
    tmp.replace(DB)
    print(f"\nmigrated     {DB.name}")
    print("             reference · doc_reference · version · send  (empty)")
    print("             section.style now allows itemized, skill-lines, references")
    print(f"\nrevert with  mv {BACKUP} {DB}")


if __name__ == "__main__":
    main()
