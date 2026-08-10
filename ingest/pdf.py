"""PDF — the only reader that needs something installed, and the weakest one.

A PDF has no structure to recover, only a text layer to read and a layout to
guess from. That makes it the bottom of the format ladder: everything above it
states its headings outright, and this one has to infer them. Where a `.docx`
or a `.tex` exists, use that instead — the answer will be better.

`pypdf` is the dependency, and it is one this project already blesses: the
README's ATS check is a `pypdf` one-liner. When it isn't installed we say so
and point at the workflow `reference-cvs/` already uses — extract to `.txt`
once, ingest the text — rather than failing with an ImportError traceback.

Page numbers are kept in `doc.meta['pages']` as spans, so a proposal drawn from
page 7 can say so even though offsets are into the extracted text.
"""

from __future__ import annotations

from .ir import Doc, MissingDependency
from .text import read_text

ADVICE = (
    "PDF support needs pypdf: `pip install pypdf`.\n"
    "Or extract the text once and ingest that instead — which is what\n"
    "reference-cvs/ already does, and gives better offsets for review:\n"
    "    python3 -c \"from pypdf import PdfReader; "
    "print(chr(10).join(p.extract_text() for p in PdfReader('cv.pdf').pages))\" > cv.txt"
)


def extract(data: bytes) -> tuple[str, list[dict]]:
    """Text of every page, and where each page starts and ends in it."""
    try:
        from pypdf import PdfReader                          # noqa: PLC0415
    except ImportError:                                      # pragma: no cover
        try:
            from PyPDF2 import PdfReader                     # noqa: PLC0415
        except ImportError as exc:
            raise MissingDependency(ADVICE) from exc

    from io import BytesIO

    reader = PdfReader(BytesIO(data))
    chunks: list[str] = []
    pages: list[dict] = []
    offset = 0

    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
        if not text.endswith("\n"):
            text += "\n"
        pages.append({"page": number, "start": offset, "end": offset + len(text)})
        chunks.append(text)
        offset += len(text)

    return "".join(chunks), pages


def read(data: bytes) -> Doc:
    text, pages = extract(data)
    doc = read_text(text, kind="pdf")
    doc.meta["pages"] = pages
    if not text.strip():
        doc.notes.append(
            "no text layer — this looks like a scan, which needs OCR "
            "(out of scope: nothing here guesses at pixels)")
    return doc


def page_of(doc: Doc, offset: int) -> int | None:
    """Which page an offset fell on, for a proposal to cite."""
    for span in doc.meta.get("pages", []):
        if span["start"] <= offset < span["end"]:
            return span["page"]
    return None
