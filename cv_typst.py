"""Rows → Typst. The only module that knows Typst syntax.

`render(con, document_id)` is a pure function of what is in the database: same
rows in, byte-identical file out. Every ORDER BY ends in a unique column so
nothing is left to SQLite's discretion, which is the point of the exercise.

Nothing here talks to HTTP, so it can be checked by diffing its output rather
than by clicking through a browser:

    python3 -c "import sqlite3, cv_typst; print(cv_typst.render(sqlite3.connect('db/cv.db'), 1))"
"""

from __future__ import annotations

import sqlite3

HEADER = '#import "cv-template.typ": cv, section, entry, skill, item'

# Typst markup characters that would otherwise be read as syntax. Backslash
# first, or it would escape the backslashes added afterwards.
MARKUP_SPECIALS = "\\#$*_`<>@[]~"

# A line beginning with one of these starts a list, heading, or term.
LINE_LEADERS = ("-", "+", "=", "/")


def esc_markup(text: str) -> str:
    """Escape text destined for a content block `[...]`.

    Straight quotes are deliberately left alone — Typst turns them into
    typographic quotes, which is what a publication title wants.
    """
    out = str(text)
    for ch in MARKUP_SPECIALS:
        out = out.replace(ch, "\\" + ch)
    stripped = out.lstrip()
    if stripped.startswith(LINE_LEADERS):
        lead = out[: len(out) - len(stripped)]
        out = lead + "\\" + stripped
    return out


def esc_string(text: str) -> str:
    """Escape text destined for a "quoted string" argument."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def arg(name: str, value) -> str | None:
    """One `name: "value",` argument line, or None when the field is empty."""
    return f'  {name}: "{esc_string(value)}",' if value else None


# --------------------------------------------------------------------- read --

def fetch(con: sqlite3.Connection, document_id: int) -> dict:
    con.row_factory = sqlite3.Row
    q = lambda sql, *a: [dict(r) for r in con.execute(sql, a)]

    document = con.execute("SELECT * FROM document WHERE id = ?", (document_id,)).fetchone()
    if document is None:
        raise LookupError(f"no document with id {document_id}")
    profile = con.execute("SELECT * FROM profile WHERE id = 1").fetchone()

    return {
        "document": dict(document),
        "profile": dict(profile) if profile else {},
        "contacts": q("SELECT kind, value, display FROM contact ORDER BY sort_order, id"),
        "sections": q("""SELECT id, heading, style, sort_order FROM section
                         WHERE document_id = ? AND include = 1
                         ORDER BY sort_order, id""", document_id),
        "entries": q("""SELECT e.*, de.section_id, de.sort_order AS entry_order
                        FROM doc_entry de JOIN entry e ON e.id = de.entry_id
                        WHERE de.document_id = ? AND de.include = 1
                        ORDER BY de.section_id, de.sort_order, e.id""", document_id),
        # A bullet with no doc_bullet row prints: pulling in an entry brings all
        # of its bullets, and rows exist only where one has been cut.
        "bullets": q("""SELECT b.entry_id, b.text
                        FROM doc_entry de
                        JOIN bullet b ON b.entry_id = de.entry_id
                        LEFT JOIN doc_bullet db
                               ON db.document_id = de.document_id AND db.bullet_id = b.id
                        WHERE de.document_id = ? AND de.include = 1
                          AND COALESCE(db.include, 1) = 1
                        ORDER BY b.entry_id, b.sort_order, b.id""", document_id),
        # Categories print in the order they were first entered.
        "skills": q("""SELECT s.category, s.name, s.detail
                       FROM doc_skill ds JOIN skill s ON s.id = ds.skill_id
                       WHERE ds.document_id = ?
                       ORDER BY (SELECT MIN(x.id) FROM skill x WHERE x.category = s.category),
                                s.sort_order, s.id""", document_id),
    }


# -------------------------------------------------------------------- blocks --

def render_header(profile: dict, contacts: list[dict], document: dict) -> str:
    lines = ["#show: cv.with(", f'  name: "{esc_string(profile.get("full_name", ""))}",']

    subtitle = "  •  ".join(filter(None, [
        f'Legal name: {profile["legal_name"]}' if profile.get("legal_name") else None,
        profile.get("pronouns"),
    ]))
    if subtitle:
        lines.append(f'  subtitle: "{esc_string(subtitle)}",')

    if contacts:
        lines.append("  contacts: (")
        for c in contacts:
            shown = c["display"] or c["value"]
            if c["kind"] == "link" or c["value"].startswith(("mailto:", "http")):
                lines.append(f'    link("{esc_string(c["value"])}")[{esc_markup(shown)}],')
            else:
                lines.append(f'    "{esc_string(shown)}",')
        lines.append("  ),")

    if document.get("paper") and document["paper"] != "us-letter":
        lines.append(f'  paper: "{esc_string(document["paper"])}",')

    lines.append(")")
    return "\n".join(lines)


def render_entry(e: dict, bullets: list[str]) -> str:
    """An entry with bullets renders as #entry; one without renders as #item.

    That is the whole rule — it needs no column, because having bullets is
    already the difference between the two shapes in cv-template.typ.
    """
    if bullets:
        args = [a for a in (
            arg("org", e["org"]),
            arg("role", e["title"]),
            arg("dates", e["date_display"]),
            arg("location", e["location"]),
            arg("note", e["note"]),
        ) if a]
        body = "\n".join(f"  - {esc_markup(b)}" for b in bullets)
        return "#entry(\n" + "\n".join(args) + "\n)[\n" + body + "\n]"
    return render_item(e)


def render_item(e: dict) -> str:
    """One-liners: publications name the venue in the note; everything else
    bolds the organisation and puts the date there instead."""
    if e["kind"] == "publication":
        note = ", ".join(filter(None, [e["org"], e["date_display"]]))
        return _item(note, esc_markup(e["summary"] or e["title"] or e["org"] or ""))

    note = "  ·  ".join(filter(None, [e["date_display"], e["location"]]))
    head = f'*{esc_markup(e["org"])}*' if e["org"] else ""
    tail = esc_markup(e["summary"] or e["title"] or "")
    return _item(note, f"{head} — {tail}" if head and tail else head or tail)


def _item(note: str, body: str) -> str:
    opener = f'#item(note: "{esc_string(note)}")[' if note else "#item["
    return f"{opener}\n  {body}\n]"


def render_skills(skills: list[dict]) -> str:
    """Group by category, join with commas, detail in parentheses."""
    groups: dict[str, list[str]] = {}
    for s in skills:
        shown = f'{s["name"]} ({s["detail"]})' if s["detail"] else s["name"]
        groups.setdefault(s["category"], []).append(esc_markup(shown))
    return "\n".join(f'#skill("{esc_string(cat)}")[{", ".join(names)}]'
                     for cat, names in groups.items())


# ------------------------------------------------------------------ document --

def render(con: sqlite3.Connection, document_id: int) -> str:
    data = fetch(con, document_id)
    bullets: dict[int, list[str]] = {}
    for b in data["bullets"]:
        bullets.setdefault(b["entry_id"], []).append(b["text"])

    out = [HEADER, "", render_header(data["profile"], data["contacts"], data["document"])]

    for sec in data["sections"]:
        blocks = []

        if sec["style"] == "profile":
            if data["profile"].get("summary"):
                blocks.append(esc_markup(data["profile"]["summary"]))
        elif sec["style"] == "skills":
            rendered = render_skills(data["skills"])
            if rendered:
                blocks.append(rendered)
        else:
            for e in data["entries"]:
                if e["section_id"] == sec["id"]:
                    blocks.append(render_entry(e, bullets.get(e["id"], [])))

        # A heading with nothing under it would print as a bare rule.
        if not blocks:
            continue

        out.append("")
        out.append(f'#section("{esc_string(sec["heading"])}")')
        for block in blocks:
            out.append("")
            out.append(block)

    return "\n".join(out) + "\n"
