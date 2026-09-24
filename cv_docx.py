"""Rows → .docx. The only file that knows OOXML.

The mirror of `cv_typst.py`. Same rows, same shapes, same rule about which
entry becomes which block — a different set of strings on the way out.

A .docx is a zip of XML parts, so this needs nothing installed: `zipfile` and
string formatting are enough. That keeps the promise the README makes, which
`typst` already strains by being an external binary the PDF depends on. A Word
file has no such dependency, which is the point of having this route at all:
it is the one output that works on a machine with nothing on it.

Pages opens .docx directly, so "export for Pages" and "export for Word" are the
same button.

What this deliberately does NOT do:
  - No numbering.xml. Bullets are a literal "•" with a hanging indent, which
    every reader renders identically and every parser reads as text. Word's
    list machinery buys auto-numbering we do not use and costs two more parts.
  - No theme, no fonts embedded. The template's Garamond is named, with Times
    New Roman behind it, exactly as in cv-template.typ.
  - No density scaling. `document.density` is not honoured here because it is
    not honoured by the Typst side either (cv-template.typ hardcodes it), and
    two formats disagreeing about spacing would be worse than both ignoring it.
"""

from __future__ import annotations

import io
import sqlite3
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

# The query layer lives once, in cv_typst.fetch. Importing it here is what
# keeps the two renderers from drifting: a column added for one appears in the
# other, and a document composes identically whichever button was pressed.
from cv_typst import fetch

# ---------------------------------------------------------------- style knobs
# The same values as cv-template.typ, converted to Word's units.
#   sz      = half-points  (11pt -> 22)
#   spacing = twentieths of a point, for both leading and letter-spacing
#   twips   = 1/20 pt, for margins and indents (1in = 1440)

FONT = "Adobe Garamond Pro"
FONT_FALLBACK = "Times New Roman"

INK = "000000"
INK_SOFT = "2B2B2B"

SIZE_BASE = 22        # 11pt
SIZE_NAME = 42        # 21pt
SIZE_SECTION = 23     # 11.5pt
SIZE_SUB = 20         # 10pt
SIZE_CONTACT = 21     # 10.5pt

TRACK_NAME = 9        # ~0.04em at 21pt
TRACK_SECTION = 12    # the section headings are letter-spaced in the template

MARGIN = 1224         # 0.85in
PAGE = {"us-letter": (12240, 15840), "a4": (11906, 16838)}

BULLET_INDENT = 200   # hanging indent for the "•"


def _esc(text) -> str:
    return escape(str(text if text is not None else ""))


def _rpr(*, bold=False, italic=False, size=SIZE_BASE, color=INK, track=0) -> str:
    """A run's formatting. Order matters to the schema, so it is fixed here."""
    parts = [f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>']
    if bold:
        parts.append("<w:b/>")
    if italic:
        parts.append("<w:i/>")
    if track:
        parts.append(f'<w:spacing w:val="{track}"/>')
    parts.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    parts.append(f'<w:color w:val="{color}"/>')
    return "<w:rPr>" + "".join(parts) + "</w:rPr>"


def _run(text, **kw) -> str:
    # xml:space="preserve" or Word eats the spaces between joined runs.
    return f'<w:r>{_rpr(**kw)}<w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'


def _para(runs, *, align=None, before=0, after=0, line=260,
          indent=0, hanging=0, border=False) -> str:
    """One paragraph. `runs` is already-rendered XML."""
    pr = ['<w:pPr>']
    if align:
        pr.append(f'<w:jc w:val="{align}"/>')
    if border:
        pr.append('<w:pBdr><w:bottom w:val="single" w:sz="8" '
                  'w:space="2" w:color="000000"/></w:pBdr>')
    if indent or hanging:
        pr.append(f'<w:ind w:left="{indent}" w:hanging="{hanging}"/>')
    pr.append(f'<w:spacing w:before="{before}" w:after="{after}" '
              f'w:line="{line}" w:lineRule="auto"/>')
    pr.append("</w:pPr>")
    return "<w:p>" + "".join(pr) + (runs or "") + "</w:p>"


# ------------------------------------------------------------------- blocks --

def _header(profile: dict, contacts: list[dict]) -> list[str]:
    out = [_para(_run(str(profile.get("full_name") or "").upper(),
                      bold=True, size=SIZE_NAME, track=TRACK_NAME),
                 align="center", after=60)]

    subtitle = "  •  ".join(filter(None, [
        f'Legal name: {profile["legal_name"]}' if profile.get("legal_name") else None,
        profile.get("pronouns"),
    ]))
    if subtitle:
        out.append(_para(_run(subtitle, italic=True, size=SIZE_SUB, color=INK_SOFT),
                         align="center", after=50))

    if contacts:
        shown = []
        for c in contacts:
            label = c["display"] or c["value"]
            # A mailto: that never got a display value would otherwise print
            # the scheme, which is right in a link and wrong as text.
            shown.append(label[len("mailto:"):] if label.startswith("mailto:") else label)
        out.append(_para(_run("  •  ".join(shown), size=SIZE_CONTACT),
                         align="center", after=60))
    return out


def _section(heading: str) -> str:
    return _para(_run(heading.upper(), bold=True, size=SIZE_SECTION,
                      track=TRACK_SECTION),
                 before=280, after=120, border=True)


def _bullets(texts: list[str]) -> list[str]:
    return [_para(_run("•\t") + _run(t),
                  indent=BULLET_INDENT, hanging=BULLET_INDENT, before=40, after=0)
            for t in texts]


def _entry(e: dict, bullets: list[str]) -> list[str]:
    """Same rule as the Typst side: bullets make it an entry, none make it an item."""
    if not bullets:
        return _item(e)

    head = " — ".join(filter(None, [e.get("org"), e.get("title")]))
    out = [_para(_run(head, bold=True), before=220, after=0)]

    meta = "  ·  ".join(filter(None, [e.get("date_display"), e.get("location")]))
    if meta:
        out.append(_para(_run(meta, italic=True, size=SIZE_SUB, color=INK_SOFT),
                         before=0, after=0))
    if e.get("note"):
        out.append(_para(_run(e["note"], italic=True, size=SIZE_SUB, color=INK_SOFT),
                         before=0, after=0))
    out += _bullets(bullets)
    return out


def _item(e: dict) -> list[str]:
    """One-liners. Publications name the venue underneath; everything else
    bolds the organisation and carries the date there instead."""
    if e.get("kind") == "publication":
        body = e.get("summary") or e.get("title") or e.get("org") or ""
        note = ", ".join(filter(None, [e.get("org"), e.get("date_display")]))
        out = [_para(_run(body), before=200, after=0)]
        if note:
            out.append(_para(_run(note, italic=True, size=SIZE_SUB, color=INK_SOFT),
                             before=0, after=0))
        return out

    tail = e.get("summary") or e.get("title") or ""
    runs = _run(e["org"], bold=True) if e.get("org") else ""
    if runs and tail:
        runs += _run(" — ") + _run(tail)
    elif not runs:
        runs = _run(tail)
    out = [_para(runs, before=200, after=0)]

    note = "  ·  ".join(filter(None, [e.get("date_display"), e.get("location")]))
    if note:
        out.append(_para(_run(note, italic=True, size=SIZE_SUB, color=INK_SOFT),
                         before=0, after=0))
    return out


def _line_item(e: dict) -> list[str]:
    """The date, then what it was. Nothing else — an itemized section shows
    less than an entries one, it does not store less."""
    head = e.get("summary") or e.get("title") or ""
    tail = ", ".join(p for p in (e.get("org"), e.get("location")) if p)
    body = f"{head}, {tail}" if head and tail else head or tail
    runs = ""
    if e.get("date_display"):
        runs += _run(e["date_display"] + "\t", italic=True, color=INK_SOFT)
    runs += _run(body)
    return [_para(runs, before=100, after=0)]


def _skills(skills: list[dict]) -> list[str]:
    groups: dict[str, list[str]] = {}
    for s in skills:
        shown = f'{s["name"]} ({s["detail"]})' if s["detail"] else s["name"]
        groups.setdefault(s["category"], []).append(shown)
    return [_para(_run(cat + ": ", bold=True) + _run(", ".join(names)),
                  before=120, after=0)
            for cat, names in groups.items()]


def _skill_lines(skills: list[dict]) -> list[str]:
    out = []
    for s in skills:
        runs = _run(s["name"])
        if s["detail"]:
            runs += _run(" – " + s["detail"], italic=True, color=INK_SOFT)
        out.append(_para(runs, before=60, after=0))
    return out


def _reference(r: dict) -> list[str]:
    out = [_para(_run(r["name"], bold=True), before=200, after=0)]
    rest = [r["title"], r["org"], r["department"],
            *str(r["address"] or "").splitlines(), r["email"], r["phone"]]
    for line in rest:
        if str(line or "").strip():
            out.append(_para(_run(line, size=SIZE_SUB, color=INK_SOFT),
                             before=0, after=0))
    return out


# ----------------------------------------------------------------- document --

def render_body(con: sqlite3.Connection, document_id: int) -> str:
    """Every paragraph of the document, as one run of XML.

    Walks the sections in exactly the order `cv_typst.render` walks them, and
    skips an empty heading for the same reason: it would print as a bare rule.
    """
    data = fetch(con, document_id)

    bullets: dict[int, list[str]] = {}
    for b in data["bullets"]:
        bullets.setdefault(b["entry_id"], []).append(b["text"])

    out = _header(data["profile"], data["contacts"])

    for sec in data["sections"]:
        blocks: list[str] = []

        if sec["style"] == "profile":
            if data["profile"].get("summary"):
                blocks.append(_para(_run(data["profile"]["summary"]),
                                    before=120, after=0))
        elif sec["style"] in ("skills", "skill-lines"):
            chosen = [s for s in data["skills"]
                      if not sec["category"] or s["category"] == sec["category"]]
            if chosen:
                blocks += (_skills(chosen) if sec["style"] == "skills"
                           else _skill_lines(chosen))
        elif sec["style"] == "references":
            for r in data["references"]:
                blocks += _reference(r)
        elif sec["style"] == "itemized":
            for e in data["entries"]:
                if e["section_id"] == sec["id"]:
                    blocks += _line_item(e)
        else:
            for e in data["entries"]:
                if e["section_id"] == sec["id"]:
                    blocks += _entry(e, bullets.get(e["id"], []))

        if not blocks:
            continue
        out.append(_section(sec["heading"]))
        out += blocks

    return "".join(out)


def _document_xml(body: str, paper: str) -> str:
    width, height = PAGE.get(paper, PAGE["us-letter"])
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}"
        f'<w:sectPr><w:pgSz w:w="{width}" w:h="{height}"/>'
        f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" '
        f'w:left="{MARGIN}" w:header="0" w:footer="0" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    "</Types>"
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    "</Relationships>"
)

_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    "</Relationships>"
)

# Only the Normal style, so that a reader with no Garamond still falls back the
# way the template intends rather than to whatever Word's default happens to be.
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:docDefaults><w:rPrDefault><w:rPr>"
    f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>'
    f'<w:sz w:val="{SIZE_BASE}"/><w:szCs w:val="{SIZE_BASE}"/>'
    "</w:rPr></w:rPrDefault></w:docDefaults>"
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
    '<w:name w:val="Normal"/><w:rPr>'
    f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}"/>'
    f'<w:sz w:val="{SIZE_BASE}"/></w:rPr></w:style>'
    "</w:styles>"
)


def _core_xml(title: str, author: str, stamp: dict | None) -> str:
    version = f" · version {stamp['version']}" if stamp else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{_esc(title)}</dc:title>"
        f"<dc:creator>{_esc(author)}</dc:creator>"
        f"<cp:keywords>{_esc('cv_db' + version)}</cp:keywords>"
        "</cp:coreProperties>"
    )


def write(con: sqlite3.Connection, document_id: int, path,
          stamp: dict | None = None) -> None:
    """Build the .docx at `path`.

    `stamp` is the same {"version", "created_at", "digest"} the Typst side
    takes, and goes the same place: into the file's metadata, never onto the
    page. Nothing here is part of the digest — the digest is computed from the
    Typst render, so that a document compares equal to itself regardless of
    which formats were asked for.
    """
    data = fetch(con, document_id)
    name = str(data["profile"].get("full_name") or "")
    body = render_body(con, document_id)

    # Built in memory and written once. A failure part-way through leaves no
    # file at all, rather than a truncated zip that Word would refuse and that
    # would sit on the Desktop looking like output.
    buf = io.BytesIO()
    # A fixed date so two runs of the same rows produce the same bytes — the
    # property the whole project is built around.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, content in (
            ("[Content_Types].xml", _CONTENT_TYPES),
            ("_rels/.rels", _RELS),
            ("word/_rels/document.xml.rels", _DOC_RELS),
            ("word/styles.xml", _STYLES),
            ("docProps/core.xml", _core_xml(f"{name} - Curriculum Vitae", name, stamp)),
            ("word/document.xml", _document_xml(body, data["document"].get("paper"))),
        ):
            info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, content)

    Path(path).write_bytes(buf.getvalue())
