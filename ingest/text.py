"""Plain text and Markdown.

Markdown is the easy one and worth taking seriously: `##` is a heading with no
inference required, and `-` is a bullet. Plain text is the floor — indentation,
blank lines, and the shape of a line are the only signals there are, so this is
where `looks_like_heading` earns its keep and where the generic segmenter does
most of the work afterwards.
"""

from __future__ import annotations

import re

from .ir import Block, Doc
from .segment import looks_like_heading

ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SETEXT = re.compile(r"^\s*(=+|-{3,})\s*$")
RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
MD_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")


def _lines(text: str):
    """(offset, line-with-newline) pairs, so offsets stay exact."""
    offset = 0
    for line in text.splitlines(keepends=True):
        yield offset, line
        offset += len(line)


def demd(s: str) -> str:
    """Markdown emphasis removed. Link text kept, target dropped."""
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])(\*|_)(?!\s)(.+?)(?<!\s)\1(?![\w*])", r"\2", s)
    return s.strip()


class _Buffer:
    """Consecutive non-blank lines, flushed as one paragraph block."""

    def __init__(self, doc: Doc, rule: str):
        self.doc, self.rule = doc, rule
        self.start: int | None = None
        self.end = 0
        self.parts: list[str] = []

    def add(self, offset: int, line: str, text: str) -> None:
        if self.start is None:
            self.start = offset
        self.end = offset + len(line.rstrip("\n"))
        self.parts.append(text)

    def flush(self) -> None:
        if self.start is None:
            return
        body = "\n".join(self.parts).strip()
        if body:
            self.doc.add(Block(text=body, role="para", start=self.start,
                               end=self.end, rule=self.rule))
        self.start, self.parts = None, []


def read_markdown(text: str) -> Doc:
    doc = Doc(text=text, kind="markdown")
    buffer = _Buffer(doc, "markdown.para")
    rows = list(_lines(text))

    skip_next = False
    for index, (offset, line) in enumerate(rows):
        if skip_next:
            skip_next = False
            continue
        bare = line.rstrip("\n")
        end = offset + len(bare)

        atx = ATX.match(bare)
        if atx:
            buffer.flush()
            heading = demd(atx.group(2))
            doc.add(Block(text=heading, role="heading", start=offset, end=end,
                          fields={"heading": heading},
                          style={"level": len(atx.group(1))},
                          rule="markdown.atx"))
            continue

        # Setext: this line is the heading, the next one underlines it.
        nxt = rows[index + 1][1].rstrip("\n") if index + 1 < len(rows) else ""
        if bare.strip() and SETEXT.match(nxt) and not RULE.match(bare):
            buffer.flush()
            heading = demd(bare)
            doc.add(Block(text=heading, role="heading", start=offset,
                          end=rows[index + 1][0] + len(nxt),
                          fields={"heading": heading},
                          style={"level": 1 if nxt.startswith("=") else 2},
                          rule="markdown.setext"))
            skip_next = True
            continue

        if RULE.match(bare):
            buffer.flush()
            doc.add(Block(text=bare.strip(), role="meta", start=offset, end=end,
                          rule="markdown.rule"))
            continue

        bullet = MD_BULLET.match(bare)
        if bullet:
            buffer.flush()
            doc.add(Block(text=demd(bullet.group(1)), role="bullet",
                          start=offset + bullet.start(1), end=end,
                          rule="markdown.bullet"))
            continue

        if not bare.strip():
            buffer.flush()
            continue

        buffer.add(offset, line, demd(bare))

    buffer.flush()
    return doc


DIGITS = re.compile(r"\d+")


def furniture(text: str) -> set[str]:
    """Running headers and footers, found by the one thing that defines them:
    they repeat.

    A CV extracted from a PDF carries "Miriam Posner, page 3 of 10" on every
    page, and that line is not experience. Normalising the digits away makes
    the ten variants one string, and a short line appearing on most pages is
    furniture rather than content. No page-number regex required — this also
    catches a bare running name, a footer URL, or a date stamp.
    """
    seen: dict[str, int] = {}
    for line in text.splitlines():
        bare = line.strip()
        if bare and len(bare) <= 90:
            key = DIGITS.sub("#", bare)
            seen[key] = seen.get(key, 0) + 1
    return {key for key, count in seen.items() if count >= 3}


def read_text(text: str, kind: str = "text") -> Doc:
    doc = Doc(text=text, kind=kind)
    buffer = _Buffer(doc, f"{kind}.para")
    repeated = furniture(text)

    for offset, line in _lines(text):
        bare = line.rstrip("\n")
        end = offset + len(bare)

        if not bare.strip():
            buffer.flush()
            continue

        # Claimed as meta, not dropped: it is really in the file, so coverage
        # should still count it — it just isn't a row.
        if DIGITS.sub("#", bare.strip()) in repeated:
            buffer.flush()
            doc.add(Block(text=bare.strip(), role="meta", start=offset, end=end,
                          rule=f"{kind}.furniture"))
            continue

        if looks_like_heading(bare):
            buffer.flush()
            heading = bare.strip().rstrip(":")
            doc.add(Block(text=heading, role="heading", start=offset, end=end,
                          fields={"heading": heading}, rule=f"{kind}.heading"))
            continue

        buffer.add(offset, line, bare)

    buffer.flush()
    return doc
