"""Bytes in, proposed rows out.

`parse()` is a pure function: same bytes in, same proposals out, no network, no
clock, no model. That is the same property `cv_typst.render()` has in the other
direction, and it is deliberate — the two are inverses, and neither is allowed
to depend on anything but its input.

Nothing here writes to the library. A reader produces blocks, the segmenter
refines them, and this module turns them into `Proposal`s that a human accepts
or rejects. `entry`, `bullet`, and `skill` stay a place where every row was put
there on purpose; `extraction` is where the guesses live until someone agrees
with them.

    from ingest import parse
    for source in parse("cv.tex", open("cv.tex", "rb").read()):
        print(source.coverage, len(source.proposals))
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from . import detect as _detect
from . import html as _html
from . import latex as _latex
from . import office as _office
from . import text as _text
from . import typst as _typst
from .ir import (Block, Doc, Gap, MissingDependency, Proposal, check_no_overlap,
                 coverage)
from .segment import segment, find_location, looks_like_heading

__all__ = ["parse", "read", "propose", "Source", "MissingDependency",
           "Doc", "Block", "Proposal"]

PARSER_VERSION = "1"

# Columns a proposal may fill on `entry`. Anything a reader invents that is not
# here is dropped rather than passed to SQLite, so a reader cannot quietly
# widen the schema.
ENTRY_COLUMNS = ("kind", "org", "title", "note", "location", "date_display",
                 "start_ym", "end_ym", "is_current", "url", "summary")

READERS_NOT_BUILT = {
    "bibtex": "BibTeX import is the next thing on the list, not this one.",
    "json": "JSON Resume import is planned as an interchange adapter.",
}


@dataclass
class Source:
    """One document and what we made of it."""
    name: str
    kind: str
    sha256: str
    doc: Doc
    proposals: list[Proposal] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    coverage: float = 0.0

    @property
    def text(self) -> str:
        return self.doc.text


# ---------------------------------------------------------------- reading ----

def read(filename: str, data: bytes, kind: str | None = None) -> Doc:
    """One file to a `Doc`. Raises on a format with no reader."""
    kind = kind or _detect.detect(filename, data)

    if kind in READERS_NOT_BUILT:
        raise ValueError(f"{kind}: {READERS_NOT_BUILT[kind]}")

    if kind == "docx":
        return _office.read_docx(data)
    if kind == "pdf":
        from . import pdf as _pdf                            # optional dependency
        return _pdf.read(data)

    text = _detect.decode(data)
    if kind == "typst":
        return _typst.read(text)
    if kind == "latex":
        return _latex.read(text)
    if kind == "markdown":
        return _text.read_markdown(text)
    if kind == "html":
        return _html.read(text)
    if kind == "text":
        return _text.read_text(text)

    raise ValueError(f"no reader for {kind!r} ({filename})")


# --------------------------------------------------------------- proposing ---

def _contact_kind(value: str) -> str:
    if "@" in value and "://" not in value:
        return "email"
    if value.startswith(("http://", "https://", "www.")):
        return "link"
    if sum(c.isdigit() for c in value) >= 7:
        return "phone"
    return "city"


def _profile(doc: Doc, out: list[Proposal]) -> None:
    """Name and contact line, where the format stated them outright."""
    if not doc.meta.get("name"):
        return
    header = next((b for b in doc.blocks if b.rule == "typst.header"), None)
    start, end = (header.start, header.end) if header else (0, 0)
    # Every proposal quotes its own span, without exception — the header's
    # fields all come out of one block, so they all quote that block.
    quote = doc.text[start:end][:400]

    out.append(Proposal(target="profile",
                        payload={"full_name": doc.meta["name"]},
                        start=start, end=end, rule="header.name", quote=quote))

    for order, contact in enumerate(doc.meta.get("contacts", [])):
        value = contact.get("value", "")
        out.append(Proposal(
            target="contact",
            payload={"kind": _contact_kind(contact.get("display") or value),
                     "value": value,
                     "display": contact.get("display"),
                     "sort_order": order},
            start=start, end=end, rule="header.contact", quote=quote))


# Headings whose lines are skills rather than experience. The label before a
# colon becomes the category, which is how "Languages:" arrives as a language.
SKILL_HEADINGS = ("skill", "skills", "language", "languages", "technical",
                  "competencies", "competences", "tools", "software",
                  "technical skills", "languages and skills")


def _looks_like_name(line: str) -> bool:
    words = line.split()
    return (1 < len(words) <= 5 and not any(c.isdigit() for c in line)
            and "@" not in line and ":" not in line)


def _plain_header(doc: Doc, out: list[Proposal]) -> None:
    """Name and contacts for formats that mark neither — .docx, .txt, .pdf.

    Only the text above the first heading is considered. That region is the
    letterhead by convention in every CV, and confining the guess to it is why
    a stray email in a publication title cannot become your address.
    """
    for block in doc.blocks:
        if block.role == "heading":
            break
        if block.role not in ("para", "line"):
            continue

        offset = 0
        for line in block.text.splitlines(keepends=True):
            start = block.start + offset
            offset += len(line)
            text = line.strip()
            if not text:
                continue
            end = start + len(text)

            if "@" in text and "://" not in text:
                kind = "email"
                payload = {"kind": kind, "value": f"mailto:{text}", "display": text}
            elif text.startswith(("http://", "https://", "www.")):
                payload = {"kind": "link", "value": text, "display": None}
            elif sum(c.isdigit() for c in text) >= 7:
                payload = {"kind": "phone", "value": text, "display": None}
            elif find_location(text) and find_location(text).group(0).strip() == text:
                payload = {"kind": "city", "value": text, "display": None}
            elif not any(p.target == "profile" for p in out) and _looks_like_name(text):
                out.append(Proposal(target="profile", payload={"full_name": text},
                                    start=start, end=end, rule="header.name.plain",
                                    confidence=0.8, quote=text))
                continue
            else:
                continue

            payload["sort_order"] = sum(1 for p in out if p.target == "contact")
            out.append(Proposal(target="contact", payload=payload, start=start,
                                end=end, rule="header.contact.plain",
                                confidence=0.9, quote=text))


def _plain_skills(doc: Doc, out: list[Proposal]) -> None:
    """`Technical: Python, SQL` under a skills heading, one skill per name.

    Splitting on commas is a rule, not a judgement: the line already committed
    to a list by writing one. A parenthesised aside stays with its skill as
    `detail`, which is where "French (fluent)" belongs.
    """
    for block in doc.blocks:
        if block.role not in ("para", "line"):
            continue
        heading = (block.style.get("heading") or "").strip().lower().rstrip(":")
        if heading not in SKILL_HEADINGS:
            continue

        offset = 0
        for line in block.text.splitlines(keepends=True):
            start = block.start + offset
            offset += len(line)
            text = line.strip()
            if not text or looks_like_heading(text):
                continue

            label, _, listed = text.partition(":")
            if not listed.strip():
                label, listed = heading.title(), text
            category = label.strip() or heading.title()

            for name in listed.split(","):
                name = name.strip(" ;.")
                if not name:
                    continue
                detail = None
                if name.endswith(")") and "(" in name:
                    name, _, tail = name.rpartition("(")
                    name, detail = name.strip(), tail.rstrip(")").strip()
                if not name:
                    continue
                out.append(Proposal(
                    target="skill",
                    payload={"name": name, "category": category, "detail": detail},
                    start=start, end=start + len(text),
                    rule="skills.list", confidence=0.7, quote=text))


def propose(doc: Doc) -> list[Proposal]:
    """Blocks to proposed rows. Blocks that stayed prose produce nothing —
    which is the correct outcome, and shows up as unplaced text rather than
    as an invented entry."""
    out: list[Proposal] = []
    _profile(doc, out)
    if not any(p.target == "profile" for p in out):
        _plain_header(doc, out)
    _plain_skills(doc, out)

    by_start: dict[int, int] = {}       # block.start → index in `out`
    last_entry: int | None = None
    pages = doc.meta.get("pages")

    def page_at(offset: int) -> int | None:
        if not pages:
            return None
        for span in pages:
            if span["start"] <= offset < span["end"]:
                return span["page"]
        return None

    for block in doc.blocks:
        quote = doc.text[block.start:block.end][:400]

        if block.role in ("entry", "template"):
            fields = dict(block.fields)
            table = fields.pop("_table", "entry")
            fields.pop("_args", None)
            fields.pop("_command", None)

            if table == "skill":
                payload = {k: fields.get(k) for k in ("name", "category", "detail")}
                payload["category"] = payload["category"] or block.style.get("heading") or "Skills"
                confidence = 1.0 if block.fields.get("category") else 0.6
            elif table == "reference":
                payload = {k: v for k, v in fields.items()
                           if k in ("name", "title", "org", "department",
                                    "address", "email", "phone")}
                confidence = 0.9
            else:
                payload = {k: v for k, v in fields.items() if k in ENTRY_COLUMNS}
                # A joined line is a real proposal with a real caveat: the
                # reviewer still has to say where the organisation ended.
                confidence = 0.5 if block.style.get("joined") else 0.9

            by_start[block.start] = len(out)
            last_entry = len(out)
            out.append(Proposal(target=table, payload=payload, start=block.start,
                                end=block.end, rule=block.rule,
                                confidence=confidence, quote=quote,
                                page=page_at(block.start)))

        elif block.role == "bullet":
            parent = by_start.get(block.style.get("of"), last_entry)
            if parent is None:
                continue           # a bullet with no entry above it is loose text
            out.append(Proposal(target="bullet",
                                payload={"text": block.text},
                                start=block.start, end=block.end,
                                rule=block.rule, parent=parent, quote=quote,
                                page=page_at(block.start)))

    return out


# ------------------------------------------------------------------ parsing --

def _one(name: str, data: bytes, kind: str | None = None) -> Source:
    doc = read(name, data, kind)
    segment(doc)
    fraction, gaps = coverage(doc)
    for a, b in check_no_overlap(doc):
        doc.notes.append(f"overlapping blocks: {a.rule}@{a.start} / {b.rule}@{b.start}")
    return Source(name=name, kind=doc.kind,
                  sha256=hashlib.sha256(data).hexdigest(), doc=doc,
                  proposals=propose(doc), gaps=gaps, coverage=fraction)


def parse(filename: str, data: bytes) -> list[Source]:
    """Every document in `data`. A list because an archive holds several.

    A zip is a bundle, not a document — an Overleaf export, a folder of old
    applications. Each member goes back through the top of the pipeline, and
    members with no reader are reported rather than silently dropped.
    """
    kind = _detect.detect(filename, data)
    if kind != "zip":
        return [_one(filename, data, kind)]

    out: list[Source] = []
    for member, blob in _office.members(data):
        inner = _detect.detect(member, blob)
        if inner in ("zip", "unknown") or inner in READERS_NOT_BUILT:
            continue                                  # no nested archives
        try:
            out.append(_one(f"{filename}!{member}", blob, inner))
        except (ValueError, MissingDependency) as exc:
            source = Source(name=f"{filename}!{member}", kind=inner,
                            sha256=hashlib.sha256(blob).hexdigest(),
                            doc=Doc(text="", kind=inner))
            source.doc.notes.append(str(exc))
            out.append(source)
    return out
