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
import base64
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

import ingest
from ingest import store as ingest_store

import cv_typst          # named so it can't collide with the `typst` PyPI package
import cv_docx           # the same rows, rendered to OOXML instead

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
# The build copy. It stays here because the source it holds opens with a
# relative `#import "cv-template.typ"`, so it only compiles beside the template.
GENERATED = ROOT / "cv.generated.typ"
# Where finished CVs land, named for the document rather than for the build.
SAVE_DIR = Path.home() / "Desktop"

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
    "contact":   {"kind", "value", "display", "sort_order"},
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
            "sections": "section", "documents": "document", "contacts": "contact",
            "references": "reference", "versions": "version", "sends": "send"}

CONTACT_KINDS = ("email", "phone", "city", "link")

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
        "contacts": get_contacts(con),
        "contact_kinds": list(CONTACT_KINDS),
        "documents": get_documents(con),
    }


def get_profile(con) -> dict:
    row = con.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    return dict(row) if row else {}


def get_contacts(con) -> list[dict]:
    return rows(con, "SELECT * FROM contact ORDER BY sort_order, id")


def patch_profile(con, body: dict) -> dict:
    """Update the profile, creating it if this database has none yet.

    A fresh database has no profile row, and a plain UPDATE against a row that
    is not there fails — which used to mean a new user could not type their own
    name on the first screen. So this upserts.
    """
    if not con.execute("SELECT 1 FROM profile WHERE id = 1").fetchone():
        with con:
            con.execute("INSERT INTO profile (id, full_name) VALUES (1, ?)",
                        (clean(body.get("full_name")) or "Your Name",))
    return patch(con, "profile", 1, body)


def create_contact(con, body: dict) -> dict:
    """Add a line to the header: an email, a phone, a city, or a link."""
    kind = clean(body.get("kind"))
    value = clean(body.get("value"))
    if kind not in CONTACT_KINDS:
        raise Bad(f"kind must be one of {', '.join(CONTACT_KINDS)}")
    if not value:
        raise Bad("a contact needs a value")
    if not con.execute("SELECT 1 FROM profile WHERE id = 1").fetchone():
        raise Bad("set your name first — a contact belongs to a profile")

    order = body.get("sort_order")
    if not str(order or "").strip():
        order = con.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM contact").fetchone()[0]
    with con:
        cur = con.execute("INSERT INTO contact (profile_id, kind, value, display, sort_order) "
                          "VALUES (1,?,?,?,?)",
                          (kind, value, clean(body.get("display")), int(order)))
    return {"id": cur.lastrowid}


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


FORMATS = ("typ", "pdf", "docx", "both", "all")


def generate(con, body: dict) -> dict:
    """Render, version, and hand back whichever files were asked for.

    `format` is one of typ · pdf · docx · both · all. The `.typ` is written to
    disk whichever is chosen — a PDF cannot be compiled without it, and the
    version is computed from it — so the choice is about what you are handed,
    not about what runs. `both` is pdf and source; `all` adds the Word file.

    The Word file is rendered from the same rows by cv_docx, not converted from
    the PDF, so nothing about it depends on `typst` being installed. That is
    deliberate: it is the one output that still works on a bare machine.

    The older `compile: true/false` is still accepted, because a bool maps onto
    two of the formats exactly.
    """
    document_id = as_number("section_id", body.get("document_id"))
    if not document_id:
        raise Bad("which document? none was given")

    fmt = str(body.get("format") or ("pdf" if body.get("compile") else "typ")).lower()
    if fmt not in FORMATS:
        raise Bad(f"format must be one of {', '.join(FORMATS)} — got {fmt!r}")

    try:
        source = cv_typst.render(con, document_id)
    except LookupError as e:
        raise Bad(str(e))

    # Version first, then re-render carrying its number — the file that lands
    # on disk is the one whose metadata names the version it is.
    version = record_version(con, document_id, source)
    # One stamp, shared by both renderers, so the Word file and the PDF can
    # never disagree about which version they are.
    stamp = {
        "version": version["number"],
        "created_at": version["created_at"],
        "digest": version["digest"],
    }
    stamped = cv_typst.render(con, document_id, stamp)

    # Keep the stamped text, so a version can be rebuilt as the file it was.
    # Its digest still comes from the unstamped render above, which is what
    # makes two identical documents compare equal.
    with con:
        con.execute("UPDATE version SET source = ? WHERE id = ?", (stamped, version["id"]))

    # Written twice on purpose. The copy in the project folder is what typst
    # compiles, because the source imports cv-template.typ by a relative path;
    # the copy in SAVE_DIR is the one meant to be kept, and carries the name of
    # the document. Its import still points back here, so it is an archive copy
    # rather than something that compiles where it sits.
    GENERATED.write_text(stamped)
    typ_path = SAVE_DIR / download_name(con, document_id, "typ")
    pdf_path = SAVE_DIR / download_name(con, document_id, "pdf")
    docx_path = SAVE_DIR / download_name(con, document_id, "docx")
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    typ_path.write_text(stamped)

    typ_file = {"kind": "typ", "name": typ_path.name, "download": "/download/typ",
                "filename": typ_path.name}
    # `download`/`filename` name the one file to offer first; `files` is the
    # whole set, which is the only part that differs between the formats.
    result = {"typst": stamped, "path": typ_path.name, "compiled": False,
              "directory": str(SAVE_DIR), "version": version, "format": fmt,
              "files": [typ_file], "download": typ_file["download"],
              "filename": typ_file["filename"]}

    # Written before the PDF on purpose. It needs nothing installed, so a
    # missing `typst` should not cost the Word file too.
    docx_file = None
    if fmt in ("docx", "all"):
        cv_docx.write(con, document_id, docx_path, stamp)
        docx_file = {"kind": "docx", "name": docx_path.name,
                     "download": "/download/docx", "filename": docx_path.name}
        result["docx"] = docx_file["name"]

    if fmt == "docx":
        result["files"] = [docx_file]
        result["download"] = docx_file["download"]
        result["filename"] = docx_file["filename"]
        if pdf_path.is_file():
            result["stale_pdf"] = pdf_path.name
        return result

    if fmt == "typ":
        # A PDF from an earlier run is now older than the .typ beside it. Not
        # deleted — it is a file someone may still want — but not passed off as
        # current either, which is the failure this project exists to avoid.
        if pdf_path.is_file():
            result["stale_pdf"] = pdf_path.name
        return result

    if not shutil.which("typst"):
        result["error"] = "typst is not on PATH — the .typ file was still written"
        if docx_file:
            # `all` asked for three and got two. Say which two rather than
            # reporting the whole run as a failure.
            result["files"] = [docx_file, typ_file]
        return result

    # Compiled from the project folder so the template import resolves, but
    # written straight out to SAVE_DIR — no PDF is left behind here to go stale.
    run = subprocess.run(["typst", "compile", GENERATED.name, str(pdf_path)],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    result["compiled"] = run.returncode == 0
    if run.returncode:
        result["error"] = (run.stderr or run.stdout).strip()[:2000]
        if docx_file:
            result["files"] = [docx_file, typ_file]
        return result

    pdf_file = {"kind": "pdf", "name": pdf_path.name, "download": "/download/pdf",
                "filename": download_name(con, document_id, "pdf")}
    result["pdf"] = pdf_file["name"]
    result["download"] = pdf_file["download"]
    result["filename"] = pdf_file["filename"]
    # The PDF is what gets sent, so it leads. `pdf` alone drops the source from
    # the set; `both` keeps it; `all` puts the Word file between the two.
    if fmt == "pdf":
        result["files"] = [pdf_file]
    elif fmt == "all":
        result["files"] = [pdf_file, docx_file, typ_file]
    else:
        result["files"] = [pdf_file, typ_file]
    return result


def reveal(con, body: dict) -> dict:
    """Show the saved file in Finder — the copy in SAVE_DIR.

    Takes the document rather than a path: the name is rebuilt from the
    database, so this still finds the file after a restart.
    """
    document_id = as_number("section_id", body.get("document_id"))
    if not document_id:
        raise Bad("which document? none was given")
    kind = body.get("kind") if body.get("kind") in ("pdf", "docx") else "typ"
    target = SAVE_DIR / download_name(con, document_id, kind)
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



# ----------------------------------------------------------------- ingestion --
#  Extraction proposes; a person promotes. Nothing here writes to the library
#  except through ingest_store.accept(), which is the only path a guess can
#  take to become a fact.

# The order the review walks, and what each step is called on screen. Skills
# and languages are the same table — a language is a skill whose category says
# so — but they are separate confirmations because they are read differently.
REVIEW_STEPS = [
    {"key": "contact",     "title": "Contact details",  "targets": ["profile", "contact"]},
    {"key": "appointments","title": "Appointments",     "targets": ["entry"],
     "kinds": ["position"]},
    {"key": "education",   "title": "Education",        "targets": ["entry"],
     "kinds": ["education"]},
    {"key": "publications","title": "Publications",     "targets": ["entry"],
     "kinds": ["publication", "project"]},
    {"key": "languages",   "title": "Languages",        "targets": ["skill"],
     "categories": ["Languages", "Language"]},
    {"key": "skills",      "title": "Skills",           "targets": ["skill"]},
    {"key": "references",  "title": "References",       "targets": ["reference"]},
]

UPLOAD_LIMIT = 12 * 1024 * 1024      # a CV that large is not a CV


def import_file(con, body: dict) -> dict:
    """Read an uploaded file, parse it, and stage what it proposed.

    The file arrives base64 in JSON rather than as multipart: `cgi` was removed
    in Python 3.13, and hand-rolling a multipart parser to save one encode is a
    poor trade in a stdlib-only project.
    """
    filename = clean(body.get("filename")) or "upload"
    raw = body.get("data") or ""
    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError):
        raise Bad("that upload did not arrive intact — try again")
    if not data:
        raise Bad("that file is empty")
    if len(data) > UPLOAD_LIMIT:
        raise Bad(f"that file is {len(data) // 1024 // 1024} MB; the limit is 12 MB")

    try:
        sources = ingest.parse(filename, data)
    except ingest.MissingDependency as e:
        raise Bad(str(e))
    except Exception as e:                      # a bad file is a user error here
        raise Bad(f"could not read {filename}: {e}")
    if not sources:
        raise Bad(f"nothing readable in {filename}")

    ids = [ingest_store.save(con, source) for source in sources]
    return {"sources": [source_summary(con, i) for i in ids]}


def source_summary(con, source_id: int) -> dict:
    row = con.execute("SELECT id, filename, kind, coverage, imported_at, parser "
                      "FROM source WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise Bad(f"no import with id {source_id}")
    summary = dict(row)
    summary["counts"] = {
        r["status"]: r["n"] for r in
        rows(con, "SELECT status, COUNT(*) AS n FROM extraction "
                  "WHERE source_id = ? GROUP BY status", (source_id,))
    }
    summary["unparsed"] = con.execute(
        "SELECT COUNT(*) FROM unparsed WHERE source_id = ?", (source_id,)).fetchone()[0]
    return summary


def get_imports(con) -> dict:
    ids = [r["id"] for r in rows(con, "SELECT id FROM source ORDER BY id DESC")]
    return {"sources": [source_summary(con, i) for i in ids],
            "steps": REVIEW_STEPS}


def get_review(con, source_id: int) -> dict:
    """Everything still awaiting a decision, grouped into the review steps."""
    proposals = [p for p in ingest_store.pending(con, source_id)]
    for p in proposals:
        p["payload"] = p["payload"] if isinstance(p["payload"], dict) else {}

    steps = []
    claimed: set[int] = set()
    for step in REVIEW_STEPS:
        picked = [p for p in proposals
                  if p["id"] not in claimed and matches_step(p, step)]
        claimed.update(p["id"] for p in picked)
        steps.append({**step, "proposals": picked})

    # Bullets ride with the entry they hang under rather than being their own
    # step — reviewing them detached from their job would be meaningless.
    bullets: dict[int, list] = {}
    for p in proposals:
        if p["target"] == "bullet" and p["parent_id"]:
            bullets.setdefault(p["parent_id"], []).append(p)

    return {"source": source_summary(con, source_id), "steps": steps,
            "bullets": bullets,
            "leftover": [p for p in proposals
                         if p["id"] not in claimed and p["target"] != "bullet"],
            "unparsed": rows(con, "SELECT id, text FROM unparsed WHERE source_id = ? "
                                  "ORDER BY char_start LIMIT 200", (source_id,))}


def matches_step(proposal: dict, step: dict) -> bool:
    if proposal["target"] not in step["targets"]:
        return False
    payload = proposal["payload"]
    if "kinds" in step and payload.get("kind") not in step["kinds"]:
        return False
    if "categories" in step and payload.get("category") not in step["categories"]:
        return False
    return True


def decide(con, extraction_id: int, body: dict) -> dict:
    """Accept (with the reviewer's edits) or reject one proposal."""
    action = clean(body.get("action")) or "accept"
    if action == "reject":
        ingest_store.reject(con, extraction_id)
        return {"status": "rejected"}
    edits = body.get("edits") or {}
    if not isinstance(edits, dict):
        raise Bad("edits must be an object")
    try:
        new_id = ingest_store.accept(con, extraction_id, edits=edits,
                                     merge_into=body.get("merge_into"))
    except (LookupError, ValueError) as e:
        raise Bad(str(e))
    return {"status": "accepted", "id": new_id}


def decide_many(con, source_id: int, body: dict) -> dict:
    """Confirm a whole review step at once, carrying any per-row edits.

    Entries go first so that a bullet's parent has become a real row by the
    time the bullet is promoted.
    """
    action = clean(body.get("action")) or "accept"
    edits = body.get("edits") or {}
    wanted = [int(i) for i in (body.get("ids") or [])]
    if not wanted:
        return {"accepted": 0, "rejected": 0, "failed": []}

    order = {"profile": 0, "contact": 1, "entry": 2, "skill": 3, "reference": 4,
             "bullet": 5}
    queue = rows(con, f"SELECT id, target FROM extraction WHERE source_id = ? "
                      f"AND status = 'pending' AND id IN "
                      f"({','.join('?' * len(wanted))})", (source_id, *wanted))
    queue.sort(key=lambda r: (order.get(r["target"], 9), r["id"]))

    done = failed = 0
    for row in queue:
        try:
            if action == "reject":
                ingest_store.reject(con, row["id"])
            else:
                ingest_store.accept(con, row["id"], edits=edits.get(str(row["id"])) or {})
            done += 1
        except (LookupError, ValueError):
            failed += 1

    # Bullets whose entry was accepted in this same pass.
    if action == "accept":
        for row in rows(con, "SELECT id FROM extraction WHERE source_id = ? "
                             "AND status = 'pending' AND target = 'bullet' "
                             "AND parent_id IN (SELECT id FROM extraction "
                             "WHERE status = 'accepted' AND source_id = ?)",
                        (source_id, source_id)):
            try:
                ingest_store.accept(con, row["id"])
                done += 1
            except (LookupError, ValueError):
                failed += 1

    return {"done": done, "failed": failed, "action": action}


def patch_extraction(con, extraction_id: int, body: dict) -> dict:
    """Edit a proposal in place, before it is promoted. Staging only — this
    cannot touch the library."""
    edits = body.get("payload")
    if not isinstance(edits, dict):
        raise Bad("payload must be an object")
    row = con.execute("SELECT payload, status FROM extraction WHERE id = ?",
                      (extraction_id,)).fetchone()
    if row is None:
        raise Bad(f"no proposal with id {extraction_id}")
    if row["status"] != "pending":
        raise Bad(f"that proposal is already {row['status']}")
    merged = {**json.loads(row["payload"]), **edits}
    with con:
        con.execute("UPDATE extraction SET payload = ? WHERE id = ?",
                    (json.dumps(merged, ensure_ascii=False), extraction_id))
    return {"payload": merged}


def delete_source(con, source_id: int) -> dict:
    """Discard an import. Anything already promoted stays in the library."""
    with con:
        cur = con.execute("DELETE FROM source WHERE id = ?", (source_id,))
    return {"deleted": cur.rowcount}


# ------------------------------------------------------------------ routing --

def route(con, method: str, path: str, body: dict):
    tail = [p for p in path.strip("/").split("/") if p][1:]   # after 'api'
    n = len(tail)

    if method == "GET":
        if tail == ["meta"]:
            return get_meta(con)
        if tail == ["imports"]:
            return get_imports(con)
        if n == 2 and tail[0] == "imports":
            return get_review(con, int(tail[1]))
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
        if tail == ["contacts"]:
            return create_contact(con, body)
        if tail == ["imports"]:
            return import_file(con, body)
        if n == 3 and tail[0] == "imports" and tail[2] == "decide":
            return decide_many(con, int(tail[1]), body)
        if n == 3 and tail[0] == "extractions" and tail[2] == "decide":
            return decide(con, int(tail[1]), body)
        if n == 3 and tail[0] == "versions" and tail[2] == "sends":
            return record_send(con, int(tail[1]), body)
        if tail == ["documents"]:
            return create_document(con, body)
        if tail == ["generate"]:
            return generate(con, body)
        if tail == ["reveal"]:
            return reveal(con, body)
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
            return patch_profile(con, body)         # a singleton; the id is ignored
        if n == 4 and tail[0] == "documents" and tail[2] == "place":
            return patch_placement(con, int(tail[1]), int(tail[3]), body)
        if n == 4 and tail[0] == "documents" and tail[2] == "bullets":
            return set_bullet(con, int(tail[1]), int(tail[3]), body)
        if n == 4 and tail[0] == "documents" and tail[2] == "skills":
            return set_skill(con, int(tail[1]), int(tail[3]), body)
        if n == 4 and tail[0] == "documents" and tail[2] == "references":
            return set_reference(con, int(tail[1]), int(tail[3]), body)
        if n == 2 and tail[0] == "extractions":
            return patch_extraction(con, int(tail[1]), body)
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
        if n == 2 and tail[0] == "imports":
            return delete_source(con, int(tail[1]))
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
        """Hand a saved file to the browser as a save, not a page.

        Only the three saved files are reachable. `kind` indexes a fixed table,
        and the file's own name is rebuilt from the database off ?doc=, so
        nothing in the query string ever becomes part of a path.
        """
        mimes = {"pdf": "application/pdf", "typ": "text/plain; charset=utf-8",
                 "docx": "application/vnd.openxmlformats-officedocument"
                         ".wordprocessingml.document"}
        if kind not in mimes:
            self.send_error(404)
            return

        query = parse_qs(urlparse(self.path).query)
        doc = query.get("doc", [""])[0]
        if doc.isdigit():
            target = SAVE_DIR / download_name(self.con, int(doc), kind)
        elif kind == "typ":
            target = GENERATED       # no document named: fall back to the build copy
        else:
            target = None
        if target is None or not target.is_file():
            # ASCII only: this goes in the HTTP status line, which is latin-1.
            self.send_error(404, "nothing generated yet - press Generate first")
            return
        mime = mimes[kind]

        # The page passes ?name= because only it knows what the user is saving
        # as. Sanitised here anyway: this lands in someone's Downloads.
        wanted = query.get("name", [""])[0]
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


DB_DIR = ROOT / "db"
SEEDS = {"starter": DB_DIR / "starter.sql",    # a blank CV, ready to fill in
         "example": DB_DIR / "seed.sql",       # the worked example that ships with the repo
         "none": None}                         # tables only, nothing in them


def create_database(path: Path, seed: str) -> None:
    """Build the database on first run, so nobody has to run sqlite3 by hand.

    This is the whole install step. `schema.sql` makes the tables; the seed
    decides what is in them — a blank CV with conventional headings by default,
    or the example CV in the repo if you want something to click around in.
    """
    if seed not in SEEDS:
        raise SystemExit(f"--seed must be one of {', '.join(SEEDS)}")
    schema = DB_DIR / "schema.sql"
    if not schema.is_file():
        raise SystemExit(f"cannot build a database: {schema} is missing")

    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(schema.read_text())
        source = SEEDS[seed]
        if source is not None:
            if not source.is_file():
                raise SystemExit(f"cannot build a database: {source} is missing")
            con.executescript(source.read_text())
        con.commit()
    finally:
        con.close()
    print(f"created {path}  ({seed})")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=ROOT / "db" / "cv.db", type=Path)
    ap.add_argument("--port", default=8000, type=int)
    ap.add_argument("--seed", default="starter", choices=sorted(SEEDS),
                    help="what to put in the database if it does not exist yet: "
                         "'starter' is a blank CV, 'example' is the one in the repo")
    args = ap.parse_args()

    if not args.db.exists():
        create_database(args.db, args.seed)

    Handler.con = connect(args.db)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"cv_db  ·  {args.db}\n        ·  http://127.0.0.1:{args.port}   (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
