"""What every reader produces, and what every reader is judged by.

A reader turns bytes into a `Doc`: the canonical text of the source, plus
`Block`s that each claim a span of it. Nothing downstream knows whether a block
came from Typst, LaTeX, or a PDF's text layer — only what it claims to be and,
where the format said so outright, which fields it already knows.

THE SPAN IS THE POINT. Every block carries offsets into `Doc.text`, so a
proposal can always show the reviewer the exact source it came from, and
`coverage()` can say what fraction of the file was accounted for. A parser that
must place every character can only fail loudly: text it did not understand
shows up as a gap rather than as silence.

`Doc.text` is the source as a person would see it — the actual `.typ` or `.tex`
bytes, not a cleaned-up rendering. Offsets that point at something the reviewer
cannot open are not provenance. For formats with no readable source (PDF, docx)
it is the extracted text, and that text is what gets stored in `source.text`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class MissingDependency(RuntimeError):
    """A reader needs something that isn't installed.

    Raised instead of letting an ImportError escape, so the caller can say
    which format is unavailable and what to do instead. Every reader except
    `pdf` is standard-library only, and this exists to keep that fact visible
    rather than incidental.
    """


# What a block claims to be. Readers assign these; the segmenter refines
# 'line' into something better when it can.
ROLES = (
    "meta",      # preamble, imports, document metadata — real, but not content
    "heading",   # a section heading
    "entry",     # a whole entry whose fields the format stated outright
    "bullet",
    "para",      # a paragraph of prose
    "line",      # a line whose role is not yet decided
    "template",  # an unrecognised command used with positional arguments
)


@dataclass
class Block:
    text: str                          # readable text, markup removed
    role: str
    start: int                         # offsets into Doc.text
    end: int
    fields: dict = field(default_factory=dict)   # what the format stated outright
    style: dict = field(default_factory=dict)    # bold/italic/level/indent hints
    rule: str = ""                     # which reader rule produced this

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"unknown block role: {self.role}")


@dataclass
class Doc:
    text: str
    kind: str                          # 'typst' | 'latex' | 'markdown' | 'text' | ...
    blocks: list[Block] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)   # what the reader couldn't do

    def add(self, block: Block) -> Block:
        self.blocks.append(block)
        return block


@dataclass
class Proposal:
    """One row we think belongs in the library, and where it came from.

    `parent` is an index into the proposal list, not a database id — nothing
    here has an id yet. Bullets point at the entry they hang under; the
    promoter resolves both at once when the reviewer accepts.
    """
    target: str                        # 'entry' | 'bullet' | 'skill' | 'reference' | 'profile' | 'contact'
    payload: dict
    start: int
    end: int
    rule: str
    parent: int | None = None
    confidence: float = 1.0
    quote: str = ""
    page: int | None = None      # PDFs only; offsets index extracted text


# ------------------------------------------------------------------ coverage --

@dataclass
class Gap:
    start: int
    end: int
    text: str


def merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Overlapping and touching spans collapsed into one another."""
    out: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def coverage(doc: Doc) -> tuple[float, list[Gap]]:
    """Fraction of the source's non-whitespace characters some block claimed,
    and every gap that is not purely whitespace.

    Whitespace gaps are not failures — the space between two blocks belongs to
    neither. Anything else is text the parser read and could not place, which
    is exactly what the reviewer needs to see.
    """
    claimed = merge([(b.start, b.end) for b in doc.blocks])

    gaps: list[Gap] = []
    cursor = 0
    for start, end in claimed + [(len(doc.text), len(doc.text))]:
        if start > cursor:
            chunk = doc.text[cursor:start]
            if chunk.strip():
                gaps.append(Gap(cursor, start, chunk))
        cursor = max(cursor, end)

    total = sum(1 for c in doc.text if not c.isspace())
    if not total:
        return 1.0, gaps
    missed = sum(1 for g in gaps for c in g.text if not c.isspace())
    return (total - missed) / total, gaps


def check_no_overlap(doc: Doc) -> list[tuple[Block, Block]]:
    """Blocks that claim the same characters.

    Not fatal — a heading block and the entry block beneath it may legitimately
    nest — but two *entries* overlapping means a segmentation bug, and it is
    cheaper to catch it here than to wonder why a bullet appeared twice.
    """
    ordered = sorted(doc.blocks, key=lambda b: (b.start, b.end))
    clashes = []
    for a, b in zip(ordered, ordered[1:]):
        if b.start < a.end and not (a.start <= b.start and b.end <= a.end):
            clashes.append((a, b))
    return clashes
