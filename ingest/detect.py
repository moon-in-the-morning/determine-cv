"""Which reader gets the file.

Extension first, because it is what the user meant, then content as a
tie-breaker and a correction. The one that actually matters: `.docx`, `.odt`,
`.pages` and a plain `.zip` are all PKZip archives, so the magic bytes alone
cannot tell a Word document from a folder of them — and a `.tex` file and a
`.txt` file are both just text.
"""

from __future__ import annotations

from pathlib import Path

# Extension → reader name. Anything not here falls through to sniffing.
BY_SUFFIX = {
    ".typ": "typst",
    ".tex": "latex",
    ".ltx": "latex",
    ".latex": "latex",
    ".bib": "bibtex",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".text": "text",
    ".html": "html",
    ".htm": "html",
    ".docx": "docx",
    ".pdf": "pdf",
    ".zip": "zip",
    ".json": "json",
}

ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def sniff(data: bytes) -> str | None:
    """Format from content alone, for files with a missing or lying suffix."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(ZIP_MAGIC):
        # word/document.xml is the only reliable tell; a .docx is a zip whose
        # first entry is usually [Content_Types].xml, which .odt has too.
        return "docx" if b"word/document.xml" in data[:8192] else "zip"

    head = data[:4096].decode("utf-8", "replace")
    if "\\documentclass" in head or "\\begin{document}" in head:
        return "latex"
    if '#import "cv-template.typ"' in head or "#show: cv.with(" in head:
        return "typst"
    if head.lstrip().startswith("@") and "{" in head:      # @article{...
        return "bibtex"
    if "<html" in head.lower() or "<!doctype html" in head.lower():
        return "html"
    return None


def detect(filename: str, data: bytes) -> str:
    """Reader name for this file. 'unknown' if nothing claims it."""
    sniffed = sniff(data)

    # A zip's real identity is only knowable from content, so content wins for
    # the archive family. Everywhere else the suffix is the better signal —
    # a .tex full of prose is still LaTeX.
    if sniffed in ("zip", "docx", "pdf"):
        return sniffed

    suffix = Path(filename).suffix.lower()
    if suffix in BY_SUFFIX:
        return BY_SUFFIX[suffix]
    return sniffed or ("text" if _looks_textual(data) else "unknown")


def _looks_textual(data: bytes) -> bool:
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def decode(data: bytes) -> str:
    """Text of a source file, newlines normalised.

    Offsets index into what this returns, so the normalisation has to happen
    once, here, before any reader sees the text — otherwise a CRLF file's spans
    would be off by one per line against the text we store.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:                                                    # pragma: no cover
        text = data.decode("utf-8", "replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")
