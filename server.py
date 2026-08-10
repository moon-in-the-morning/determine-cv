#!/usr/bin/env python3
"""cv_db — experience library, saved documents, and a Typst generator.

A tiny JSON API over db/cv.db plus the static files in web/. Standard library
only: no venv, no npm, nothing to install. Run it, open the page, type.

    python3 server.py            # http://127.0.0.1:8000
    python3 server.py --port 9000 --db db/cv.db

Binds to loopback only. There is no auth, so do not put it on a network.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv_typst          # named so it can't collide with the `typst` PyPI package

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
GENERATED = ROOT / "cv.generated.typ"

KINDS = ("position", "education", "project", "publication")
STYLES = ("entries", "itemized", "skills", "skill-lines", "references", "profile")

ENTRY_FIELDS = ("kind", "org", "title", "note", "location",
                "date_display", "start_ym", "end_ym", "is_current", "url", "summary")

REFERENCE_FIELDS = ("name", "title", "org", "department", "address",
                    "email", "phone", "relation")

SEND_FIELDS = ("recipient", "org", "sent_on", "channel", "notes")

# Which columns a PATCH may touch, and which of those are numbers.
PATCHABLE = {
    "entry":     set(ENTRY_FIELDS),
    "bullet":    {"text", "sort_order"},
    "skill":     {"name", "category", "detail", "sort_order"},
    "reference": {*REFERENCE_FIELDS, "sort_order"},
    "section":   {"heading", "style", "category", "sort_order", "include"},
    "profile":   {"full_name", "legal_name", "pronouns", "summary"},
    "document":  {"slug", "title", "density", "paper", "notes"},
    "version":   {"notes"},
    "send":      set(SEND_FIELDS),
}
NUMERIC = {"sort_order", "include", "is_current", "density", "section_id"}

TABLE_OF = {"entries": "entry", "bullets": "bullet", "skills": "skill",
            "sections": "section", "documents": "document",
            "references": "reference", "versions": "version", "sends": "send"}

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


class Bad(Exception):
    """A client error. The message is shown in the form."""


# ----------------------------------------------------------------- database --

def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def rows(con, sql, args=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args)]


def clean(value) -> str | None:
    """Trim to a stored value: whitespace-only becomes NULL, not ''."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_number(field: str, value):
    if value in (None, ""):
        return None
    return float(value) if field == "density" else int(value)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "document"


# ---------------------------------------------------------------- API: read --

def get_meta(con) -> dict:
    return {
        "kinds": list(KINDS),
        "styles": list(STYLES),
        "categories": [r["category"] for r in
                       rows(con, "SELECT DISTINCT category FROM skill ORDER BY category")],
        "orgs": [r["org"] for r in
                 rows(con, "SELECT DISTINCT org FROM entry WHERE org IS NOT NULL ORDER BY org")],
        "profile": get_profile(con),
        "documents": get_documents(con),
    }


def get_profile(con) -> dict:
    row = con.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    return dict(row) if row else {}


def get_documents(con) -> list[dict]:
    return rows(con, """
        SELECT d.*,
               (SELECT COUNT(*) FROM section   s  WHERE s.document_id  = d.id) AS sections,
               (SELECT COUNT(*) FROM doc_entry de WHERE de.document_id = d.id) AS entries
        FROM document d ORDER BY d.id
    """)


def get_library(con) -> dict:
    """Every entry and skill you have, with no reference to any document."""
    entries = rows(con, """
        SELECT * FROM entry
        ORDER BY COALESCE(start_ym, '') DESC, id DESC
    """)
    by_id = {e["id"]: e for e in entries}
    for e in entries:
        e["bullets"], e["skills"], e["used_in"] = [], [], []

    for b in rows(con, "SELECT id, entry_id, text, sort_order FROM bullet "
                       "ORDER BY entry_id, sort_order, id"):
        by_id[b["entry_id"]]["bullets"].append(b)

    for s in rows(con, """SELECT es.entry_id, s.id, s.name, s.category
                          FROM entry_skill es JOIN skill s ON s.id = es.skill_id
                          ORDER BY es.entry_id, s.category, s.name"""):
        by_id[s["entry_id"]]["skills"].append(s)

    for u in rows(con, """SELECT de.entry_id, d.id, d.title
                          FROM doc_entry de JOIN document d ON d.id = de.document_id
                          ORDER BY de.entry_id, d.id"""):
        by_id[u["entry_id"]]["used_in"].append(u)

    skills = rows(con, """
        SELECT s.*, (SELECT COUNT(*) FROM entry_skill es WHERE es.skill_id = s.id) AS uses
        FROM skill s ORDER BY s.category, s.sort_order, s.id
    """)
    references = rows(con, """
        SELECT r.*,
               (SELECT COUNT(*) FROM doc_reference dr WHERE dr.reference_id = r.id) AS used_in
        FROM reference r ORDER BY r.sort_order, r.id
    """)
    return {"entries": entries, "skills": skills, "references": references}


def get_document(con, document_id: int) -> dict:
    """One document's arrangement: its headings, what sits under them, and
    which bullets it has cut. The experience itself comes from the library."""
    doc = con.execute("SELECT * FROM document WHERE id = ?", (document_id,)).fetchone()
    if doc is None:
        raise Bad(f"no document with id {document_id}")

    return {
        "document": dict(doc),
        "sections": rows(con, "SELECT * FROM section WHERE document_id = ? "
                              "ORDER BY sort_order, id", (document_id,)),
        "placements": rows(con, "SELECT entry_id, section_id, sort_order, include "
                                "FROM doc_entry WHERE document_id = ? "
                                "ORDER BY section_id, sort_order, entry_id", (document_id,)),
        # Only bullets this document has cut; everything else prints.
        "hidden_bullets": [r["bullet_id"] for r in
                           rows(con, "SELECT bullet_id FROM doc_bullet "
                                     "WHERE document_id = ? AND include = 0", (document_id,))],
        "skill_ids": [r["skill_id"] for r in
                      rows(con, "SELECT skill_id FROM doc_skill WHERE document_id = ? "
                                "ORDER BY skill_id", (document_id,))],
        "reference_ids": [r["reference_id"] for r in
                          rows(con, "SELECT reference_id FROM doc_reference "
                                    "WHERE document_id = ? ORDER BY reference_id",
                               (document_id,))],
    }


def get_versions(con, document_id: int) -> list[dict]:
    """Newest first, each with the sends recorded against it.

    `source` is deliberately left out — it is a few kilobytes per version and
    the page only needs it when you ask to download one.
    """
    versions = rows(con, """
        SELECT id, document_id, number, created_at, digest, notes,
               LENGTH(source) AS bytes
        FROM version WHERE document_id = ? ORDER BY number DESC
    """, (document_id,))
    by_id = {v["id"]: v for v in versions}
    for v in versions:
        v["sends"] = []
    for s in rows(con, """
        SELECT s.* FROM send s JOIN version v ON v.id = s.version_id
        WHERE v.document_id = ?
        ORDER BY s.version_id, COALESCE(s.sent_on, ''), s.id
    """, (document_id,)):
        by_id[s["version_id"]]["sends"].append(s)
    return versions


# --------------------------------------------------------------- API: write --

def create_document(con, body: dict) -> dict:
    """A new document starts blank: no headings, nothing selected."""
    title = clean(body.get("title"))
    if not title:
        raise Bad("a document needs a title")
    slug = slugify(clean(body.get("slug")) or title)
    if con.execute("SELECT 1 FROM document WHERE slug = ?", (slug,)).fetchone():
        raise Bad(f"a document with the slug {slug!r} already exists")

    with con:
        cur = con.execute(
            "INSERT INTO document (slug, title, density, paper, notes) VALUES (?,?,?,?,?)",
            (slug, title, as_number("density", body.get("density")) or 1.0,
             clean(body.get("paper")) or "us-letter", clean(body.get("notes"))))
        document_id = cur.lastrowid

        # Copying an existing arrangement beats retyping a dozen headings.
        source = as_number("section_id", body.get("copy_from"))
        if source:
            copy_document(con, source, document_id)
    return {"id": document_id, "slug": slug}


def copy_document(con, source_id: int, target_id: int) -> None:
    section_map = {}
    for s in con.execute("SELECT * FROM section WHERE document_id = ? ORDER BY sort_order, id",
                         (source_id,)):
        section_map[s["id"]] = con.execute(
            "INSERT INTO section (document_id, heading, style, sort_order, include) "
            "VALUES (?,?,?,?,?)",
            (target_id, s["heading"], s["style"], s["sort_order"], s["include"])).lastrowid

    for p in con.execute("SELECT * FROM doc_entry WHERE document_id = ?", (source_id,)):
        con.execute("INSERT INTO doc_entry (document_id, entry_id, section_id, sort_order, "
                    "include) VALUES (?,?,?,?,?)",
                    (target_id, p["entry_id"], section_map[p["section_id"]],
                     p["sort_order"], p["include"]))

    con.execute("INSERT INTO doc_bullet (document_id, bullet_id, include) "
                "SELECT ?, bullet_id, include FROM doc_bullet WHERE document_id = ?",
                (target_id, source_id))
    con.execute("INSERT INTO doc_skill (document_id, skill_id) "
                "SELECT ?, skill_id FROM doc_skill WHERE document_id = ?",
                (target_id, source_id))


def create_section(con, document_id: int, body: dict) -> dict:
    heading = clean(body.get("heading"))
    style = clean(body.get("style")) or "entries"
    if not heading:
        raise Bad("a section needs a heading")
    if style not in STYLES:
        raise Bad(f"style must be one of {', '.join(STYLES)}")
    order = con.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM section "
                        "WHERE document_id = ?", (document_id,)).fetchone()[0]
    try:
        with con:
            cur = con.execute("INSERT INTO section (document_id, heading, style, sort_order) "
                              "VALUES (?,?,?,?)", (document_id, heading, style, order))
    except sqlite3.IntegrityError:
        raise Bad(f"this document already has a section headed {heading!r}")
    return {"id": cur.lastrowid}


def place_entry(con, document_id: int, body: dict) -> dict:
    """Put a library entry under a heading in this document, or move it."""
    entry_id = as_number("section_id", body.get("entry_id"))
    section_id = as_number("section_id", body.get("section_id"))
    if not entry_id or not section_id:
        raise Bad("placing an entry needs both entry_id and section_id")

    owner = con.execute("SELECT document_id, style FROM section WHERE id = ?",
                        (section_id,)).fetchone()
    if owner is None or owner["document_id"] != document_id:
        raise Bad("that heading belongs to a different document")
    if owner["style"] not in ("entries", "itemized"):
        raise Bad("only an 'entries' or 'itemized' section can hold experience")

    order = con.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM doc_entry "
                        "WHERE section_id = ?", (section_id,)).fetchone()[0]
    with con:
        con.execute(
            "INSERT INTO doc_entry (document_id, entry_id, section_id, sort_order) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT (document_id, entry_id) DO UPDATE SET section_id = excluded.section_id",
            (document_id, entry_id, section_id, order))
    return {"entry_id": entry_id, "section_id": section_id}


def patch_placement(con, document_id: int, entry_id: int, body: dict) -> dict:
    fields = {k: as_number(k, v) for k, v in body.items()
              if k in ("section_id", "sort_order", "include")}
    if not fields:
        raise Bad("nothing to update")
    assignments = ", ".join(f"{f} = ?" for f in fields)
    with con:
        cur = con.execute(
            f"UPDATE doc_entry SET {assignments} WHERE document_id = ? AND entry_id = ?",
            [*fields.values(), document_id, entry_id])
    if not cur.rowcount:
        raise Bad("that entry is not in this document")
    return {"updated": list(fields)}


def set_bullet(con, document_id: int, bullet_id: int, body: dict) -> dict:
    """Cut a bullet from this document, or put it back. Absent row = prints."""
    if body.get("include"):
        with con:
            con.execute("DELETE FROM doc_bullet WHERE document_id = ? AND bullet_id = ?",
                        (document_id, bullet_id))
    else:
        with con:
            con.execute("INSERT INTO doc_bullet (document_id, bullet_id, include) "
                        "VALUES (?,?,0) ON CONFLICT (document_id, bullet_id) "
                        "DO UPDATE SET include = 0", (document_id, bullet_id))
    return {"bullet_id": bullet_id, "include": bool(body.get("include"))}


def set_skill(con, document_id: int, skill_id: int, body: dict) -> dict:
    with con:
        if body.get("include"):
            con.execute("INSERT OR IGNORE INTO doc_skill (document_id, skill_id) VALUES (?,?)",
                        (document_id, skill_id))
        else:
            con.execute("DELETE FROM doc_skill WHERE document_id = ? AND skill_id = ?",
                        (document_id, skill_id))
    return {"skill_id": skill_id, "include": bool(body.get("include"))}


def create_entry(con, body: dict) -> dict:
    """Add experience to the library, optionally filing it straight into a
    document so you don't have to go and find it again."""
    kind = clean(body.get("kind"))
    if kind not in KINDS:
        raise Bad(f"kind must be one of {', '.join(KINDS)}")
    if not clean(body.get("title")) and not clean(body.get("org")):
        raise Bad("an entry needs at least a title or an organisation")

    values = {f: clean(body.get(f)) for f in ENTRY_FIELDS}
    values["kind"] = kind
    values["is_current"] = 1 if body.get("is_current") else 0

    columns = ", ".join(ENTRY_FIELDS)
    holes = ", ".join("?" for _ in ENTRY_FIELDS)
    with con:
        cur = con.execute(f"INSERT INTO entry ({columns}) VALUES ({holes})",
                          [values[f] for f in ENTRY_FIELDS])
        entry_id = cur.lastrowid

        for i, text in enumerate(split_bullets(body.get("bullets")), start=1):
            con.execute("INSERT INTO bullet (entry_id, text, sort_order) VALUES (?,?,?)",
                        (entry_id, text, i))

        for skill_id in body.get("skill_ids") or []:
            con.execute("INSERT OR IGNORE INTO entry_skill (entry_id, skill_id) VALUES (?,?)",
                        (entry_id, int(skill_id)))

    document_id = as_number("section_id", body.get("document_id"))
    section_id = as_number("section_id", body.get("section_id"))
    if document_id and section_id:
        place_entry(con, document_id, {"entry_id": entry_id, "section_id": section_id})
    return {"id": entry_id}


def split_bullets(raw) -> list[str]:
    """One bullet per line. A leading '-' or '•' is decoration, not text."""
    if not raw:
        return []
    lines = raw if isinstance(raw, list) else str(raw).splitlines()
    return [t for t in (str(l).strip().lstrip("-•*").strip() for l in lines) if t]


def create_skill(con, body: dict) -> dict:
    name, category = clean(body.get("name")), clean(body.get("category"))
    if not name:
        raise Bad("a skill needs a name")
    if not category:
        raise Bad("a skill needs a category — it is the bold label in the Skills section")

    order = body.get("sort_order")
    if not str(order or "").strip():
        order = con.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM skill "
                            "WHERE category = ?", (category,)).fetchone()[0]
    try:
        with con:
            cur = con.execute("INSERT INTO skill (name, category, detail, sort_order) "
                              "VALUES (?,?,?,?)",
                              (name, category, clean(body.get("detail")), int(order)))
    except sqlite3.IntegrityError:
        raise Bad(f"a skill named {name!r} already exists")
    return {"id": cur.lastrowid}


def create_reference(con, body: dict) -> dict:
    name = clean(body.get("name"))
    if not name:
        raise Bad("a reference needs a name")
    order = body.get("sort_order")
    if not str(order or "").strip():
        order = con.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM reference").fetchone()[0]

    values = [clean(body.get(f)) for f in REFERENCE_FIELDS]
    columns = ", ".join(REFERENCE_FIELDS)
    holes = ", ".join("?" for _ in REFERENCE_FIELDS)
    with con:
        cur = con.execute(
            f"INSERT INTO reference ({columns}, sort_order) VALUES ({holes}, ?)",
            [*values, int(order)])
    return {"id": cur.lastrowid}


def set_reference(con, document_id: int, reference_id: int, body: dict) -> dict:
    """Name this referee in this document, or stop naming them. Opt-in, so a
    new document lists nobody until you say so."""
    with con:
        if body.get("include"):
            con.execute("INSERT OR IGNORE INTO doc_reference (document_id, reference_id) "
                        "VALUES (?,?)", (document_id, reference_id))
        else:
            con.execute("DELETE FROM doc_reference WHERE document_id = ? AND reference_id = ?",
                        (document_id, reference_id))
    return {"reference_id": reference_id, "include": bool(body.get("include"))}


def record_send(con, version_id: int, body: dict) -> dict:
    recipient = clean(body.get("recipient"))
    if not recipient:
        raise Bad("who did it go to?")
    if not con.execute("SELECT 1 FROM version WHERE id = ?", (version_id,)).fetchone():
        raise Bad(f"no version with id {version_id}")

    values = {f: clean(body.get(f)) for f in SEND_FIELDS}
    values["recipient"] = recipient
    values["sent_on"] = values["sent_on"] or today()
    columns = ", ".join(SEND_FIELDS)
    holes = ", ".join("?" for _ in SEND_FIELDS)
    with con:
        cur = con.execute(f"INSERT INTO send (version_id, {columns}) VALUES (?, {holes})",
                          [version_id, *(values[f] for f in SEND_FIELDS)])
    return {"id": cur.lastrowid}


def add_bullet(con, entry_id: int, body: dict) -> dict:
    text = clean(body.get("text"))
    if not text:
        raise Bad("a bullet needs text")
    order = con.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM bullet "
                        "WHERE entry_id = ?", (entry_id,)).fetchone()[0]
    with con:
        cur = con.execute("INSERT INTO bullet (entry_id, text, sort_order) VALUES (?,?,?)",
                          (entry_id, text, order))
    return {"id": cur.lastrowid}


def patch(con, table: str, row_id: int, body: dict) -> dict:
    """Update whichever whitelisted columns the client sent. Absent keys are
    left alone, so a checkbox toggle sends one field and touches one column."""
    fields = {k: v for k, v in body.items() if k in PATCHABLE[table]}
    if not fields:
        raise Bad("nothing to update")

    values = {f: (as_number(f, v) if f in NUMERIC else clean(v)) for f, v in fields.items()}

    if table == "entry" and "kind" in values and values["kind"] not in KINDS:
        raise Bad(f"kind must be one of {', '.join(KINDS)}")
    if table == "section" and "style" in values and values["style"] not in STYLES:
        raise Bad(f"style must be one of {', '.join(STYLES)}")
    if "text" in values and not values["text"]:
        raise Bad("a bullet cannot be emptied — delete it instead")
    for required in ("name", "heading", "title", "full_name"):
        if required in values and not values[required]:
            raise Bad(f"{required.replace('_', ' ')} cannot be empty")

    assignments = ", ".join(f"{f} = ?" for f in values)
    try:
        with con:
            cur = con.execute(f"UPDATE {table} SET {assignments} WHERE id = ?",
                              [*values.values(), row_id])
    except sqlite3.IntegrityError as e:
        raise Bad(str(e))
    if not cur.rowcount:
        raise Bad(f"no {table} with id {row_id}")
    return {"updated": list(values)}


def link_skills(con, entry_id: int, body: dict) -> dict:
    ids = [int(i) for i in (body.get("skill_ids") or [])]
    with con:
        for skill_id in ids:
            con.execute("INSERT OR IGNORE INTO entry_skill (entry_id, skill_id) VALUES (?,?)",
                        (entry_id, skill_id))
    return {"linked": len(ids)}


def delete_row(con, table: str, row_id: int) -> dict:
    with con:
        cur = con.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    return {"deleted": cur.rowcount}


def reorder(con, table: str, body: dict) -> dict:
    """Renumber sort_order from an explicit list of ids, 1..n."""
    ids = [int(i) for i in (body.get("ids") or [])]
    with con:
        for position, row_id in enumerate(ids, start=1):
            con.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (position, row_id))
    return {"reordered": len(ids)}


# ------------------------------------------------------------------ generate --

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def record_version(con, document_id: int, source: str) -> dict:
    """Return the version this render belongs to, creating one if it is new.

    The digest is of the UNSTAMPED source, so it answers "did the document
    change?" and not "did I press the button again?". Regenerating an unchanged
    document therefore hands back the version it already is — which is what
    makes the list a list of states rather than a list of clicks, and what lets
    four sends hang off the one version they actually shared.
    """
    digest = cv_typst.digest_of(source)
    latest = con.execute("SELECT * FROM version WHERE document_id = ? "
                         "ORDER BY number DESC LIMIT 1", (document_id,)).fetchone()
    if latest and latest["digest"] == digest:
        return {"id": latest["id"], "number": latest["number"],
                "created_at": latest["created_at"], "digest": digest, "new": False}

    number = (latest["number"] + 1) if latest else 1
    created_at = now_utc()
    with con:
        cur = con.execute(
            "INSERT INTO version (document_id, number, created_at, digest, source) "
            "VALUES (?,?,?,?,?)", (document_id, number, created_at, digest, source))
    return {"id": cur.lastrowid, "number": number, "created_at": created_at,
            "digest": digest, "new": True}


def generate(con, body: dict) -> dict:
    document_id = as_number("section_id", body.get("document_id"))
    if not document_id:
        raise Bad("which document? none was given")
    try:
        source = cv_typst.render(con, document_id)
    except LookupError as e:
        raise Bad(str(e))

    # Version first, then re-render carrying its number — the file that lands
    # on disk is the one whose metadata names the version it is.
    version = record_version(con, document_id, source)
    stamped = cv_typst.render(con, document_id, {
        "version": version["number"],
        "created_at": version["created_at"],
        "digest": version["digest"],
    })

    # Keep the stamped text, so a version can be rebuilt as the file it was.
    # Its digest still comes from the unstamped render above, which is what
    # makes two identical documents compare equal.
    with con:
        con.execute("UPDATE version SET source = ? WHERE id = ?", (stamped, version["id"]))

    GENERATED.write_text(stamped)
    result = {"typst": stamped, "path": GENERATED.name, "compiled": False,
              "version": version,
              "download": "/download/typ", "filename": download_name(con, document_id, "typ")}

    if body.get("compile"):
        if not shutil.which("typst"):
            result["error"] = "typst is not on PATH — the .typ file was still written"
            return result
        run = subprocess.run(["typst", "compile", GENERATED.name],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
        result["compiled"] = run.returncode == 0
        if run.returncode:
            result["error"] = (run.stderr or run.stdout).strip()[:2000]
        else:
            result["pdf"] = GENERATED.with_suffix(".pdf").name
            result["download"] = "/download/pdf"
            result["filename"] = download_name(con, document_id, "pdf")
    return result


def reveal(body: dict) -> dict:
    """Show the generated file in Finder — the copy in the project folder."""
    target = GENERATED.with_suffix(".pdf") if body.get("kind") == "pdf" else GENERATED
    if not target.is_file():
        raise Bad("nothing generated yet — press Generate first")
    if sys.platform != "darwin":
        raise Bad("Reveal in Finder only works on macOS")
    subprocess.run(["open", "-R", str(target)], timeout=10)
    return {"revealed": target.name, "path": str(target)}


def download_name(con, document_id, suffix: str) -> str:
    """What the browser saves it as: "Moon Younes - Full CV.pdf".

    Kept to characters every filesystem accepts, since this becomes a real file
    in someone's Downloads folder.
    """
    person = (get_profile(con).get("full_name") or "").strip()
    row = con.execute("SELECT title FROM document WHERE id = ?", (document_id,)).fetchone()
    label = " - ".join(filter(None, [person, row["title"] if row else "CV"]))
    safe = "".join(c for c in label if c.isalnum() or c in " -_").strip() or "cv"
    return f"{safe}.{suffix}"


# ------------------------------------------------------------------ routing --

def route(con, method: str, path: str, body: dict):
    tail = [p for p in path.strip("/").split("/") if p][1:]   # after 'api'
    n = len(tail)

    if method == "GET":
        if tail == ["meta"]:
            return get_meta(con)
        if tail == ["library"]:
            return get_library(con)
        if tail == ["documents"]:
            return get_documents(con)
        if tail == ["profile"]:
            return get_profile(con)
        if n == 2 and tail[0] == "documents":
            return get_document(con, int(tail[1]))
        if n == 3 and tail[0] == "documents" and tail[2] == "versions":
            return get_versions(con, int(tail[1]))

    if method == "POST":
        if tail == ["entries"]:
            return create_entry(con, body)
        if tail == ["skills"]:
            return create_skill(con, body)
        if tail == ["references"]:
            return create_reference(con, body)
        if n == 3 and tail[0] == "versions" and tail[2] == "sends":
            return record_send(con, int(tail[1]), body)
        if tail == ["documents"]:
            return create_document(con, body)
        if tail == ["generate"]:
            return generate(con, body)
        if tail == ["reveal"]:
            return reveal(body)
        if n == 2 and tail[1] == "reorder" and tail[0] in ("sections", "entries"):
            return reorder(con, TABLE_OF[tail[0]], body)
        if n == 3 and tail[0] == "entries" and tail[2] == "bullets":
            return add_bullet(con, int(tail[1]), body)
        if n == 3 and tail[0] == "entries" and tail[2] == "skills":
            return link_skills(con, int(tail[1]), body)
        if n == 3 and tail[0] == "documents" and tail[2] == "sections":
            return create_section(con, int(tail[1]), body)
        if n == 3 and tail[0] == "documents" and tail[2] == "place":
            return place_entry(con, int(tail[1]), body)

    if method in ("PUT", "PATCH"):
        if tail == ["profile"] or (n == 2 and tail[0] == "profile"):
            return patch(con, "profile", 1, body)   # a singleton; the id is ignored
        if n == 4 and tail[0] == "documents" and tail[2] == "place":
            return patch_placement(con, int(tail[1]), int(tail[3]), body)
        if n == 4 and tail[0] == "documents" and tail[2] == "bullets":
            return set_bullet(con, int(tail[1]), int(tail[3]), body)
        if n == 4 and tail[0] == "documents" and tail[2] == "skills":
            return set_skill(con, int(tail[1]), int(tail[3]), body)
        if n == 4 and tail[0] == "documents" and tail[2] == "references":
            return set_reference(con, int(tail[1]), int(tail[3]), body)
        if n == 2 and tail[0] in TABLE_OF:
            return patch(con, TABLE_OF[tail[0]], int(tail[1]), body)

    if method == "DELETE":
        if n == 4 and tail[0] == "documents" and tail[2] == "place":
            with con:
                con.execute("DELETE FROM doc_entry WHERE document_id = ? AND entry_id = ?",
                            (int(tail[1]), int(tail[3])))
            return {"ok": True}
        if n == 4 and tail[0] == "entries" and tail[2] == "skills":
            with con:
                con.execute("DELETE FROM entry_skill WHERE entry_id = ? AND skill_id = ?",
                            (int(tail[1]), int(tail[3])))
            return {"ok": True}
        if n == 2 and tail[0] in TABLE_OF:
            return delete_row(con, TABLE_OF[tail[0]], int(tail[1]))

    raise Bad(f"no route for {method} {path}")


class Handler(BaseHTTPRequestHandler):
    con: sqlite3.Connection = None  # set in main()
    server_version = "cv_db"

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.api("GET", path, {})
        elif path == "/download/version":
            self.download_version()
        elif path.startswith("/download/"):
            self.download(path.rsplit("/", 1)[-1])
        else:
            self.static(path)

    def do_POST(self):
        self.api("POST", urlparse(self.path).path, self.read_json())

    def do_PATCH(self):
        self.api("PATCH", urlparse(self.path).path, self.read_json())

    def do_PUT(self):
        self.api("PUT", urlparse(self.path).path, self.read_json())

    def do_DELETE(self):
        self.api("DELETE", urlparse(self.path).path, self.read_json())

    # -- helpers --

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def api(self, method, path, body):
        try:
            self.send_json(200, route(self.con, method, path, body))
        except Bad as e:
            self.send_json(400, {"error": str(e)})
        except (ValueError, KeyError) as e:
            self.send_json(400, {"error": f"bad request: {e}"})
        except sqlite3.Error as e:
            self.send_json(500, {"error": f"database: {e}"})
        except subprocess.TimeoutExpired:
            self.send_json(500, {"error": "typst compile timed out"})

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def download(self, kind):
        """Hand the generated file to the browser as a save, not a page.

        Only the two generated files are reachable — `kind` indexes a fixed
        table rather than becoming part of a path.
        """
        targets = {"pdf": (GENERATED.with_suffix(".pdf"), "application/pdf"),
                   "typ": (GENERATED, "text/plain; charset=utf-8")}
        if kind not in targets:
            self.send_error(404)
            return
        target, mime = targets[kind]
        if not target.is_file():
            # ASCII only: this goes in the HTTP status line, which is latin-1.
            self.send_error(404, "nothing generated yet - press Generate first")
            return

        # The page passes ?name= because only it knows which document was just
        # generated. Sanitised here anyway: this lands in someone's Downloads.
        wanted = parse_qs(urlparse(self.path).query).get("name", [""])[0]
        filename = "".join(c for c in wanted if c.isalnum() or c in " -_.") or f"cv.{kind}"

        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def download_version(self):
        """Hand back the Typst of one stored version, exactly as it was written.

        It comes out of the database, not off disk: `cv.generated.typ` is
        whatever you generated last, while this is the file that went out.
        """
        wanted = parse_qs(urlparse(self.path).query).get("id", [""])[0]
        row = None
        if wanted.isdigit():
            row = self.con.execute(
                "SELECT v.number, v.source, d.slug FROM version v "
                "JOIN document d ON d.id = v.document_id WHERE v.id = ?",
                (int(wanted),)).fetchone()
        if row is None:
            self.send_error(404, "no such version")
            return

        data = row["source"].encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{row["slug"]}-v{row["number"]}.typ"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def static(self, path):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB / name).resolve()
        if not str(target).startswith(str(WEB)) or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"  {fmt % args}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=ROOT / "db" / "cv.db", type=Path)
    ap.add_argument("--port", default=8000, type=int)
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"no database at {args.db} — create it with db/schema.sql first")

    Handler.con = connect(args.db)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"cv_db  ·  {args.db}\n        ·  http://127.0.0.1:{args.port}   (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
