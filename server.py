#!/usr/bin/env python3
"""cv_db — local entry form.

A tiny JSON API over db/cv.db plus the static files in web/. Standard library
only: no venv, no npm, nothing to install. Run it, open the page, type.

    python3 server.py            # http://127.0.0.1:8000
    python3 server.py --port 9000 --db db/cv.db

Binds to loopback only. There is no auth, so do not put it on a network.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

KINDS = ("position", "education", "project", "publication")

# Columns the client may set on an entry, in schema order.
ENTRY_FIELDS = (
    "kind", "org", "title", "note", "location",
    "date_display", "start_ym", "end_ym", "is_current", "url", "summary",
)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


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


def next_order(con, table, column, key) -> int:
    sql = f"SELECT COALESCE(MAX(sort_order), 0) + 1 FROM {table} WHERE {column} = ?"
    return con.execute(sql, (key,)).fetchone()[0]


# ---------------------------------------------------------------- API: read --

def get_meta(con) -> dict:
    return {
        "kinds": list(KINDS),
        "categories": [r["category"] for r in
                       rows(con, "SELECT DISTINCT category FROM skill ORDER BY category")],
        "orgs": [r["org"] for r in
                 rows(con, "SELECT DISTINCT org FROM entry WHERE org IS NOT NULL ORDER BY org")],
        "variants": rows(con, "SELECT id, slug, title FROM variant ORDER BY id"),
        "sections": rows(con, "SELECT id, variant_id, heading FROM section "
                              "ORDER BY variant_id, sort_order"),
    }


def get_entries(con) -> list[dict]:
    entries = rows(con, """
        SELECT id, kind, org, title, note, location, date_display,
               start_ym, end_ym, is_current, url, summary
        FROM entry
        ORDER BY kind, COALESCE(start_ym, '') DESC, id DESC
    """)
    by_id = {e["id"]: e for e in entries}
    for e in entries:
        e["bullets"] = []
        e["skills"] = []
        e["variants"] = []

    for b in rows(con, "SELECT id, entry_id, text, sort_order FROM bullet "
                       "ORDER BY entry_id, sort_order, id"):
        by_id[b["entry_id"]]["bullets"].append(b)

    for s in rows(con, """
        SELECT es.entry_id, s.id, s.name, s.category
        FROM entry_skill es JOIN skill s ON s.id = es.skill_id
        ORDER BY es.entry_id, s.category, s.name
    """):
        by_id[s["entry_id"]]["skills"].append(s)

    for v in rows(con, """
        SELECT ve.entry_id, v.slug, sec.heading
        FROM variant_entry ve
        JOIN variant v   ON v.id = ve.variant_id
        JOIN section sec ON sec.id = ve.section_id
        ORDER BY ve.entry_id, v.id
    """):
        by_id[v["entry_id"]]["variants"].append(v)

    return entries


def get_skills(con) -> list[dict]:
    return rows(con, """
        SELECT s.id, s.name, s.category, s.detail, s.sort_order,
               (SELECT COUNT(*) FROM entry_skill es WHERE es.skill_id = s.id) AS uses
        FROM skill s
        ORDER BY s.category, s.sort_order, s.name
    """)


# --------------------------------------------------------------- API: write --

def create_entry(con, body: dict) -> dict:
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
            con.execute("INSERT INTO bullet (entry_id, text, sort_order) VALUES (?, ?, ?)",
                        (entry_id, text, i))

        for skill_id in body.get("skill_ids") or []:
            con.execute("INSERT OR IGNORE INTO entry_skill (entry_id, skill_id) VALUES (?, ?)",
                        (entry_id, int(skill_id)))

        variant_id, section_id = body.get("variant_id"), body.get("section_id")
        if variant_id and section_id:
            place_entry(con, entry_id, int(variant_id), int(section_id))

    return {"id": entry_id}


def place_entry(con, entry_id: int, variant_id: int, section_id: int) -> None:
    """Put an entry into a variant under a heading. Without this it renders nowhere."""
    owner = con.execute("SELECT variant_id FROM section WHERE id = ?", (section_id,)).fetchone()
    if owner is None or owner["variant_id"] != variant_id:
        raise Bad("that section belongs to a different variant")
    con.execute(
        "INSERT OR REPLACE INTO variant_entry (variant_id, entry_id, section_id, sort_order) "
        "VALUES (?, ?, ?, ?)",
        (variant_id, entry_id, section_id, next_order(con, "variant_entry", "section_id", section_id)),
    )


def split_bullets(raw) -> list[str]:
    """One bullet per line. A leading '-' or '•' is decoration, not text."""
    if not raw:
        return []
    lines = raw if isinstance(raw, list) else str(raw).splitlines()
    out = []
    for line in lines:
        text = str(line).strip().lstrip("-•*").strip()
        if text:
            out.append(text)
    return out


def create_skill(con, body: dict) -> dict:
    name = clean(body.get("name"))
    category = clean(body.get("category"))
    if not name:
        raise Bad("a skill needs a name")
    if not category:
        raise Bad("a skill needs a category — it is the bold label in the Skills section")

    order = body.get("sort_order")
    order = int(order) if str(order or "").strip() else next_order(con, "skill", "category", category)
    try:
        with con:
            cur = con.execute(
                "INSERT INTO skill (name, category, detail, sort_order) VALUES (?, ?, ?, ?)",
                (name, category, clean(body.get("detail")), order),
            )
    except sqlite3.IntegrityError:
        raise Bad(f"a skill named {name!r} already exists")
    return {"id": cur.lastrowid}


def add_bullet(con, entry_id: int, body: dict) -> dict:
    text = clean(body.get("text"))
    if not text:
        raise Bad("a bullet needs text")
    with con:
        cur = con.execute("INSERT INTO bullet (entry_id, text, sort_order) VALUES (?, ?, ?)",
                          (entry_id, text, next_order(con, "bullet", "entry_id", entry_id)))
    return {"id": cur.lastrowid}


def link_skills(con, entry_id: int, body: dict) -> dict:
    ids = [int(i) for i in (body.get("skill_ids") or [])]
    with con:
        for skill_id in ids:
            con.execute("INSERT OR IGNORE INTO entry_skill (entry_id, skill_id) VALUES (?, ?)",
                        (entry_id, skill_id))
    return {"linked": len(ids)}


def delete_row(con, table: str, row_id: int) -> dict:
    with con:
        cur = con.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    return {"deleted": cur.rowcount}


# ------------------------------------------------------------------ routing --

def route(con, method: str, path: str, body: dict):
    parts = [p for p in path.strip("/").split("/") if p]  # e.g. ['api','entries','3']

    if method == "GET":
        if parts == ["api", "meta"]:
            return get_meta(con)
        if parts == ["api", "entries"]:
            return get_entries(con)
        if parts == ["api", "skills"]:
            return get_skills(con)

    if method == "POST":
        if parts == ["api", "entries"]:
            return create_entry(con, body)
        if parts == ["api", "skills"]:
            return create_skill(con, body)
        if len(parts) == 4 and parts[:2] == ["api", "entries"] and parts[3] == "bullets":
            return add_bullet(con, int(parts[2]), body)
        if len(parts) == 4 and parts[:2] == ["api", "entries"] and parts[3] == "skills":
            return link_skills(con, int(parts[2]), body)
        if len(parts) == 4 and parts[:2] == ["api", "entries"] and parts[3] == "place":
            with con:
                place_entry(con, int(parts[2]), int(body["variant_id"]), int(body["section_id"]))
            return {"ok": True}

    if method == "DELETE":
        if len(parts) == 3 and parts[:2] == ["api", "entries"]:
            return delete_row(con, "entry", int(parts[2]))
        if len(parts) == 3 and parts[:2] == ["api", "skills"]:
            return delete_row(con, "skill", int(parts[2]))
        if len(parts) == 3 and parts[:2] == ["api", "bullets"]:
            return delete_row(con, "bullet", int(parts[2]))
        if len(parts) == 5 and parts[:2] == ["api", "entries"] and parts[3] == "skills":
            with con:
                con.execute("DELETE FROM entry_skill WHERE entry_id = ? AND skill_id = ?",
                            (int(parts[2]), int(parts[4])))
            return {"ok": True}

    raise Bad(f"no route for {method} {path}")


class Handler(BaseHTTPRequestHandler):
    con: sqlite3.Connection = None  # set in main()
    server_version = "cv_db"

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.api("GET", path, {})
        else:
            self.static(path)

    def do_POST(self):
        self.api("POST", urlparse(self.path).path, self.read_json())

    def do_DELETE(self):
        self.api("DELETE", urlparse(self.path).path, {})

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

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
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
