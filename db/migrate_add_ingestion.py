#!/usr/bin/env python3
"""One-off migration: add the ingestion staging area.

    python3 db/migrate_add_ingestion.py

Nothing you have is touched, and nothing is rebuilt. This adds three empty
tables — `source`, `extraction`, `unparsed` — plus their indexes and the
`v_pending` review queue. Every existing table keeps its rows, its schema, and
its rowids.

Unlike the earlier migrations this one does not copy the database through
`schema.sql`, because it does not need to: these are pure additions with no
CHECK constraint to widen, and SQLite can add a table in place. The reason the
others rebuilt was the constraint, not the tables.

The DDL is not written out here. It is lifted from `schema.sql` itself by
building it in memory and reading back what SQLite stored, so this file cannot
drift out of step with the schema it is supposed to be applying.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "cv.db"
SCHEMA = HERE / "schema.sql"
BACKUP = HERE / "cv.db.pre-ingestion"

ADDED = ["source", "extraction", "unparsed",
         "extraction_source", "extraction_status", "unparsed_source",
         "v_pending"]


def ddl_from_schema(names: list[str]) -> list[tuple[str, str, str]]:
    """(type, name, sql) for each object, as SQLite itself records it."""
    memory = sqlite3.connect(":memory:")
    memory.executescript(SCHEMA.read_text())
    holes = ", ".join("?" for _ in names)
    rows = memory.execute(
        f"SELECT type, name, sql FROM sqlite_master WHERE name IN ({holes})",
        names).fetchall()
    memory.close()

    found = {r[1] for r in rows}
    missing = [n for n in names if n not in found]
    if missing:
        sys.exit(f"{SCHEMA.name} has no {', '.join(missing)} — "
                 "is this the right schema file?")
    # Tables before the indexes and views that depend on them.
    order = {"table": 0, "index": 1, "view": 2, "trigger": 3}
    return sorted(rows, key=lambda r: (order.get(r[0], 9), names.index(r[1])))


def main() -> None:
    if not DB.exists():
        sys.exit(f"no database at {DB}")

    con = sqlite3.connect(DB)
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                   "AND name='extraction'").fetchone():
        sys.exit("already migrated — this database already has an `extraction` table")

    statements = ddl_from_schema(ADDED)

    shutil.copy2(DB, BACKUP)
    print(f"backup       {BACKUP.name}")

    with con:
        for kind, name, sql in statements:
            con.execute(sql)
            print(f"  {kind:<6} {name}")

    broken = con.execute("PRAGMA foreign_key_check").fetchall()
    if broken:                                               # pragma: no cover
        con.close()
        shutil.copy2(BACKUP, DB)
        sys.exit(f"foreign keys would break: {broken} — restored from backup")

    con.close()
    print(f"\nmigrated     {DB.name}")
    print("             source · extraction · unparsed  (empty)")
    print("             v_pending — the review queue, least-confident first")
    print(f"\nrevert with  mv {BACKUP} {DB}")


if __name__ == "__main__":
    main()
