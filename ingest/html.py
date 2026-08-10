"""HTML, via the standard library's own parser.

Second only to `.docx` for explicitness — `<h2>` is a heading and `<li>` is a
bullet, with nothing inferred. Two of the CVs in `reference-cvs/` are HTML
because their authors publish them as web pages, which is common enough among
academics to be worth reading directly rather than via the PDF.

Offsets index the raw HTML, so a proposal points at the actual markup. That is
what `getpos()` is for, and why this keeps a table of line starts.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from .ir import Block, Doc
from .segment import looks_like_heading

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCKS = HEADINGS | {"p", "li", "div", "section", "article", "td", "th", "tr",
                     "dd", "dt", "blockquote", "figcaption", "header", "footer"}
SKIP = {"script", "style", "head", "noscript", "svg"}
BOLD = {"strong", "b", "h1", "h2", "h3"}


class _Reader(HTMLParser):
    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.doc = Doc(text=text, kind="html")
        self.starts = [0]
        for line in text.splitlines(keepends=True):
            self.starts.append(self.starts[-1] + len(line))
        self.skipping = 0
        self.tag: str | None = None
        self.start = 0
        self.parts: list[str] = []
        self.bold = 0

    # `getpos()` is 1-based on lines and 0-based within them. Named `_where`
    # rather than `offset` because HTMLParser already owns `self.offset`,
    # and shadowing it replaces this method with an int mid-parse.
    def _where(self) -> int:
        line, column = self.getpos()
        return min(self.starts[line - 1] + column, len(self.doc.text))

    def flush(self, end: int) -> None:
        body = re.sub(r"\s+", " ", "".join(self.parts)).strip()
        if body and self.tag:
            role = "heading" if self.tag in HEADINGS else (
                "bullet" if self.tag == "li" else "para")
            if role == "para" and self.bold and looks_like_heading(body):
                role = "heading"
            block = Block(text=body.rstrip(":") if role == "heading" else body,
                          role=role, start=self.start, end=max(end, self.start),
                          style={"tag": self.tag}, rule=f"html.{self.tag}")
            if role == "heading":
                block.fields["heading"] = block.text
            self.doc.add(block)
        self.tag, self.parts = None, []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skipping += 1
            return
        if tag == "br":
            self.parts.append("\n")
            return
        if tag in BOLD:
            self.bold += 1
        if tag in BLOCKS:
            self.flush(self._where())
            self.tag, self.start, self.parts = tag, self._where(), []

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
            return
        if tag in BOLD:
            self.bold = max(0, self.bold - 1)
        if tag in BLOCKS and self.tag == tag:
            self.flush(self._where() + len(tag) + 3)

    def handle_data(self, data):
        if not self.skipping and self.tag:
            self.parts.append(data)


def read(text: str) -> Doc:
    reader = _Reader(text)
    reader.feed(text)
    reader.flush(len(text))
    reader.close()

    # Everything outside <body> — doctype, head, scripts — is real text in the
    # file that is not CV content. Claim it so coverage measures the document,
    # not the boilerplate around it.
    body = re.search(r"<body[^>]*>", text, re.I)
    if body and reader.doc.blocks:
        reader.doc.add(Block(text="<head>", role="meta", start=0,
                             end=body.end(), rule="html.head"))
    return reader.doc
