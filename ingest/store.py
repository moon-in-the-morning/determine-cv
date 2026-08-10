"""Proposals into the staging tables, and accepted proposals into the library.

Two functions and a hard line between them. `save()` writes what the parser
thought; `accept()` writes what a person decided. Nothing in this module lets
the first become the second without someone saying so.

`save()` is idempotent on `(sha256, parser)`: re-importing a file you already
imported returns the row you already have. Import it under a NEWER parser
version and you get a second row instead — deliberately, because that is what
makes an improved rule measurable. Two `source` rows over the same sha256 are
the same document read two ways, and the difference between their extractions
is exactly what the rule change bought.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import PARSER_VERSION, Source

# Which library table each proposal target lands in, and which columns it may
# fill. Kept here rather than inferred, so a reader cannot reach a column the
# promoter never meant to expose.
COLUMNS = {
    "entry": ("kind", "org", "title", "note", "location", "date_display",
              "start_ym", "end_ym", "is_current", "url", "summary"),
    "bullet": ("entry_id", "text", "sort_order"),
    "skill": ("name", "category", "detail", "sort_order"),
    "reference": ("name", "title", "org", "department", "address", "email",
                  "phone", "relation", "sort_order"),
    "contact": ("kind", "value", "display", "sort_order"),
    # `profile` is a singleton: accepting one UPDATES row 1 rather than
    # inserting, so re-importing a second CV cannot give you two names.
    "profile": ("full_name", "legal_name", "pronouns", "summary"),
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save(con: sqlite3.Connection, source: Source,
         parser: str = PARSER_VERSION) -> int:
    """Store a parsed document and everything it proposed. Returns `source.id`."""
    existing = con.execute(
        "SELECT id FROM source WHERE sha256 = ? AND parser = ?",
        (source.sha256, parser)).fetchone()
    if existing:
        return existing[0]

    with con:
        cursor = con.execute(
            "INSERT INTO source (filename, kind, sha256, text, coverage, "
            "parser, imported_at) VALUES (?,?,?,?,?,?,?)",
            (source.name, source.kind, source.sha256, source.doc.text,
             round(source.coverage, 6), parser, now()))
        source_id = cursor.lastrowid

        # Parents before children: a bullet's `parent_id` is the row id of the
        # entry above it, which does not exist until that entry is inserted.
        ids: dict[int, int] = {}
        for index, p in enumerate(source.proposals):
            parent = ids.get(p.parent) if p.parent is not None else None
            row = con.execute(
                "INSERT INTO extraction (source_id, target, payload, parent_id,"
                " char_start, char_end, page, quote, rule, confidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (source_id, p.target, json.dumps(p.payload, ensure_ascii=False),
                 parent, p.start, p.end, p.page, p.quote, p.rule, p.confidence))
            ids[index] = row.lastrowid

        con.executemany(
            "INSERT INTO unparsed (source_id, char_start, char_end, text) "
            "VALUES (?,?,?,?)",
            [(source_id, g.start, g.end, g.text) for g in source.gaps])

    return source_id


def accept(con: sqlite3.Connection, extraction_id: int,
           edits: dict | None = None, merge_into: int | None = None) -> int | None:
    """Promote one proposal into the library. Returns the `entry.id` it became.

    `edits` are the reviewer's corrections, applied over the payload — this is
    where a split organisation-and-title arrives, and it is the only path by
    which a human's judgement reaches the library.

    `merge_into` folds the proposal into an entry that already exists instead
    of creating a second one. That is the answer to the second CV someone
    uploads: the bullet pool takes the new wording, and the entry stays one
    entry. The row is marked `merged`, not `accepted`, so the difference stays
    visible a year later.
    """
    row = con.execute(
        "SELECT target, payload, parent_id, status FROM extraction WHERE id = ?",
        (extraction_id,)).fetchone()
    if row is None:
        raise LookupError(f"no extraction {extraction_id}")
    target, payload_json, parent_id, status = row
    if status != "pending":
        raise ValueError(f"extraction {extraction_id} is already {status}")

    payload = {**json.loads(payload_json), **(edits or {})}
    allowed = COLUMNS.get(target)
    if allowed is None:
        raise ValueError(f"cannot promote {target!r} rows here")
    fields = {k: v for k, v in payload.items() if k in allowed and v not in (None, "")}

    with con:
        if target == "bullet":
            entry_id = merge_into or _entry_of(con, parent_id)
            if entry_id is None:
                raise ValueError("bullet has no accepted entry to hang under")
            order = con.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM bullet "
                "WHERE entry_id = ?", (entry_id,)).fetchone()[0]
            con.execute("INSERT INTO bullet (entry_id, text, sort_order) "
                        "VALUES (?,?,?)",
                        (entry_id, fields.get("text", ""), order))
            new_id = entry_id
        elif target == "profile":
            # One person, one row. Only the fields this proposal carries are
            # written, so accepting a name does not blank an existing summary.
            con.execute("INSERT OR IGNORE INTO profile (id, full_name) VALUES (1, '')")
            if fields:
                assignments = ", ".join(f"{c} = ?" for c in fields)
                con.execute(f"UPDATE profile SET {assignments} WHERE id = 1",
                            list(fields.values()))
            new_id = 1
        elif target == "contact":
            order = con.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM contact").fetchone()[0]
            fields.setdefault("sort_order", order)
            columns = ", ".join(["profile_id", *fields])
            holes = ", ".join("?" for _ in range(len(fields) + 1))
            con.execute("INSERT OR IGNORE INTO profile (id, full_name) VALUES (1, '')")
            new_id = con.execute(
                f"INSERT INTO contact ({columns}) VALUES ({holes})",
                [1, *fields.values()]).lastrowid
        elif merge_into is not None:
            new_id = merge_into
        else:
            columns = ", ".join(fields)
            holes = ", ".join("?" for _ in fields)
            new_id = con.execute(
                f"INSERT INTO {target} ({columns}) VALUES ({holes})",
                list(fields.values())).lastrowid

        con.execute("UPDATE extraction SET status = ?, entry_id = ? WHERE id = ?",
                    ("merged" if merge_into is not None else "accepted",
                     new_id if target in ("entry", "bullet") else None,
                     extraction_id))
    return new_id


def reject(con: sqlite3.Connection, extraction_id: int) -> None:
    with con:
        con.execute("UPDATE extraction SET status = 'rejected' WHERE id = ?",
                    (extraction_id,))


def _entry_of(con: sqlite3.Connection, extraction_id: int | None) -> int | None:
    if extraction_id is None:
        return None
    row = con.execute("SELECT entry_id FROM extraction WHERE id = ?",
                      (extraction_id,)).fetchone()
    return row[0] if row else None


def pending(con: sqlite3.Connection, source_id: int | None = None) -> list[dict]:
    """The review queue, least-confident first."""
    con.row_factory = sqlite3.Row
    sql = "SELECT * FROM v_pending"
    args: tuple = ()
    if source_id is not None:
        sql = ("SELECT v.* FROM v_pending v JOIN extraction x ON x.id = v.id "
               "WHERE x.source_id = ?")
        args = (source_id,)
    return [{**dict(r), "payload": json.loads(r["payload"])}
            for r in con.execute(sql, args)]
