"""Word documents and archives — both of them zips, for different reasons.

`.docx` is the best-case input and the surprise of this build: it needs no
third-party library, because a Word file is a zip of XML and `zipfile` and
`xml.etree` are both standard library. It is also the most *explicit* format
here — Word records outright that a paragraph is `Heading 1` and that another
is a list item, so there is nothing to infer. Most people's old resumes are
Word files, which makes this the highest-yield reader in the set.

A plain `.zip` is not a document at all; it is a bundle. An Overleaf export, a
folder of applications, a LinkedIn data export. It routes each member back
through the top of the pipeline and yields several sources instead of one.

A docx has no readable source text, so `Doc.text` is the text this module
reconstructs, and that is what gets stored in `source.text` and what every
offset indexes. The provenance is still exact — it just points into our
extraction rather than into a file the reviewer could open in a text editor.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree

from .ir import Block, Doc
from .segment import looks_like_heading

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Members that are never a person's document.
JUNK = re.compile(r"(^|/)(__MACOSX/|\.DS_Store$|\.git/|Thumbs\.db$)")


def _text_of(node) -> str:
    """All the text in a `w:p`, with tabs and breaks kept as separators."""
    parts: list[str] = []
    for child in node.iter():
        if child.tag == f"{W}t":
            parts.append(child.text or "")
        elif child.tag == f"{W}tab":
            parts.append("\t")
        elif child.tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
    return "".join(parts)


def _style_of(node) -> tuple[str, bool, bool]:
    """(style name, is a list item, is entirely bold)."""
    props = node.find(f"{W}pPr")
    name = ""
    numbered = False
    if props is not None:
        style = props.find(f"{W}pStyle")
        if style is not None:
            name = style.get(f"{W}val", "")
        numbered = props.find(f"{W}numPr") is not None

    runs = node.findall(f"{W}r")
    texted = [r for r in runs if r.find(f"{W}t") is not None]
    bold = bool(texted) and all(
        (r.find(f"{W}rPr") is not None and r.find(f"{W}rPr").find(f"{W}b") is not None)
        for r in texted)
    return name, numbered, bold


def read_docx(data: bytes) -> Doc:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        try:
            xml = archive.read("word/document.xml")
        except KeyError as exc:                              # pragma: no cover
            raise ValueError("not a Word document: no word/document.xml") from exc

    root = ElementTree.fromstring(xml)
    body = root.find(f"{W}body")
    paragraphs: list[tuple[str, str, bool, bool]] = []

    for node in (body if body is not None else root).iter():
        if node.tag == f"{W}p":
            style, numbered, bold = _style_of(node)
            paragraphs.append((_text_of(node), style, numbered, bold))

    # Build the canonical text and the blocks together, so offsets are exact
    # against the string we are about to store.
    doc = Doc(text="", kind="docx")
    pieces: list[str] = []
    offset = 0

    for text, style, numbered, bold in paragraphs:
        line = text.strip()
        if not line:
            pieces.append("\n")
            offset += 1
            continue

        start = offset
        end = start + len(line)
        pieces.append(line + "\n")
        offset = end + 1

        heading_style = style.lower().startswith(("heading", "title", "subtitle"))
        if heading_style or (bold and looks_like_heading(line)):
            doc.add(Block(text=line.rstrip(":"), role="heading", start=start,
                          end=end, fields={"heading": line.rstrip(":")},
                          style={"word_style": style or "bold"},
                          rule="docx.heading"))
        elif numbered or style.lower().startswith("list"):
            doc.add(Block(text=line, role="bullet", start=start, end=end,
                          rule="docx.list"))
        else:
            doc.add(Block(text=line, role="para", start=start, end=end,
                          style={"bold": bold}, rule="docx.para"))

    doc.text = "".join(pieces)
    return doc


def members(data: bytes) -> list[tuple[str, bytes]]:
    """Every plausible document inside an archive, largest first.

    Order matters a little: an Overleaf export has one `.tex` that owns
    `\\begin{document}` and several that are included into it, and the biggest
    file is usually the one a person means.
    """
    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for info in archive.infolist():
            if info.is_dir() or JUNK.search(info.filename):
                continue
            if info.file_size == 0 or info.file_size > 64 * 1024 * 1024:
                continue
            out.append((info.filename, archive.read(info)))
    out.sort(key=lambda pair: -len(pair[1]))
    return out
