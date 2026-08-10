"""LaTeX in, blocks out.

LaTeX CVs look like the hard case and are close to the easy one, because of a
property the format has and PDFs don't: **a user-defined command is a template
declaration.** Someone whose CV is built on `\\newcommand{\\job}[4]{...}` has
already told us their entries have four fields and has already marked where
each one starts and stops — fourteen times, identically. We do not need to know
what the four *mean*. We notice the arity, sniff what we can (a date looks like
a date), and ask the reviewer once; the answer applies to all fourteen. That is
the correction-propagation idea arriving for free, declared in the source
instead of inferred from it.

So there are three tiers, in descending order of confidence:

  1. **Known CV classes.** `moderncv` and friends have documented signatures,
     so `\\cventry{years}{title}{employer}{city}{grade}{description}` maps
     straight onto columns with nothing guessed.
  2. **User-defined commands.** Arity from `\\newcommand`, fields sniffed per
     argument, one confirmation covering every use.
  3. **Everything else.** `\\section` is a heading, `\\item` is a bullet, and
     the prose in between is de-marked-up and handed to the generic segmenter.

Offsets index the raw `.tex`, so a proposal points at the actual line the user
can open — which is why nothing here rewrites the text before scanning it.
"""

from __future__ import annotations

import re
import unicodedata

from .ir import Block, Doc

CONTROL = re.compile(r"\\([A-Za-z]+)(\*?)")

# ------------------------------------------------------------------- detex ----

# A trailing accent command plus its base letter, composed properly rather than
# approximated — an academic CV is full of names that deserve their diacritics.
COMBINING = {
    "'": "\u0301", "`": "\u0300", '"': "\u0308", "^": "\u0302", "~": "\u0303",
    "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "c": "\u0327",
    "H": "\u030b", "k": "\u0328", "r": "\u030a", "d": "\u0323", "b": "\u0331",
}

LETTERS = {
    "ss": "ß", "aa": "å", "AA": "Å", "o": "ø", "O": "Ø", "l": "ł", "L": "Ł",
    "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "i": "ı", "j": "ȷ",
}

# Take no arguments and contribute nothing to the text.
DROP = {
    "hfill", "vfill", "noindent", "centering", "raggedright", "raggedleft",
    "bigskip", "medskip", "smallskip", "par", "maketitle", "hline", "hrule",
    "newpage", "clearpage", "pagebreak", "linebreak", "bfseries", "itshape",
    "mdseries", "upshape", "normalfont", "normalsize", "small", "footnotesize",
    "scriptsize", "tiny", "large", "Large", "LARGE", "huge", "Huge", "sc",
    "scshape", "sf", "sffamily", "tt", "ttfamily", "rm", "rmfamily", "bf", "it",
    "em", "boldmath", "protect", "leavevmode", "strut", "toprule", "midrule",
    "bottomrule",
}

# Contribute their first argument and nothing else.
TEXT1 = {
    "textbf", "textit", "textsl", "textsc", "textrm", "textsf", "texttt",
    "textnormal", "emph", "underline", "uline", "mbox", "text", "so", "st",
    "textsuperscript", "textsubscript", "caption", "title", "author",
}

SPACES = {"quad", "qquad", "hspace", "vspace", ",", ";", ":", "!", " "}


def _arg(text: str, i: int) -> tuple[str, int] | None:
    """`text[i]` should be `{`; return its contents and the index just past `}`."""
    if i >= len(text) or text[i] != "{":
        return None
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    return None


def _optional(text: str, i: int) -> tuple[str, int]:
    """Skip a `[...]` optional argument if one is here."""
    if i < len(text) and text[i] == "[":
        depth, j = 0, i
        while j < len(text):
            if text[j] == "[":
                depth += 1
            elif text[j] == "]":
                depth -= 1
                if depth == 0:
                    return text[i + 1:j], j + 1
            j += 1
    return "", i


def _skip_space(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\n":
        i += 1
    return i


def _absorb(text: str, i: int) -> int:
    """Spaces after a control *word*, which TeX itself swallows.

    `Stra\\ss e` is "Straße", not "Straß e" — the space ends the command name
    rather than being a space. Newlines are left alone: TeX would absorb those
    too, but they are the only paragraph signal the segmenter gets downstream.
    """
    while i < len(text) and text[i] in " \t":
        i += 1
    return i


def flat(value: str) -> str:
    """One field, one line.

    A brace group wrapping onto a second line is ordinary LaTeX and means
    nothing — `{Museum of\\nNatural History}` is one organisation, and storing
    the line break would put it in the database and then in the PDF.
    """
    return re.sub(r"\s+", " ", value).strip()


def _args(text: str, i: int, count: int) -> tuple[list[str], int]:
    """Up to `count` brace groups, skipping whitespace and optionals between."""
    out: list[str] = []
    while len(out) < count:
        j = _skip_space(text, i)
        _, j = _optional(text, j)
        j = _skip_space(text, j)
        got = _arg(text, j)
        if got is None:
            break
        out.append(got[0])
        i = got[1]
    return out, i


def detex(s: str) -> str:
    """LaTeX source to the text a reader would see. Lossy on purpose."""
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]

        if c == "%" and (i == 0 or s[i - 1] != "\\"):
            nl = s.find("\n", i)
            i = len(s) if nl < 0 else nl + 1
            continue

        if c == "\\":
            m = CONTROL.match(s, i)
            if m:
                name = m.group(1)
                i = m.end()
                if name in LETTERS and not m.group(2):
                    out.append(LETTERS[name])
                    i = _absorb(s, i)
                    continue
                if name in COMBINING:                      # \c{c}, \v{s}, \u{a}
                    body, i = _args(s, i, 1)
                    base = detex(body[0]) if body else ""
                    out.append(unicodedata.normalize(
                        "NFC", (base[:1] or " ") + COMBINING[name]) + base[1:])
                    continue
                if name in DROP:
                    _, i = _optional(s, _skip_space(s, i))
                    i = _absorb(s, i)
                    continue
                if name in SPACES:
                    _, i = _args(s, i, 1) if name in ("hspace", "vspace") else ([], i)
                    out.append(" ")
                    continue
                if name in TEXT1:
                    body, i = _args(s, i, 1)
                    out.append(detex(body[0]) if body else "")
                    continue
                if name == "href":
                    body, i = _args(s, i, 2)
                    out.append(detex(body[1]) if len(body) > 1 else "")
                    continue
                if name == "url":
                    body, i = _args(s, i, 1)
                    out.append(body[0] if body else "")
                    continue
                if name in ("begin", "end"):
                    _, i = _args(s, i, 1)
                    continue
                if name == "item":
                    out.append("\n")
                    continue
                # Unknown command: drop the name, keep whatever it wrapped.
                body, i = _args(s, i, 9)
                out.append(" ".join(detex(b) for b in body if b.strip()))
                continue

            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == "\\":
                out.append("\n")
                i += 2
                continue
            if nxt in COMBINING and i + 2 < len(s):        # \'e, \"o, \~n
                base = s[i + 2]
                out.append(unicodedata.normalize("NFC", base + COMBINING[nxt]))
                i += 3
                continue
            out.append(nxt)                                 # \& \% \_ \# \$ \{ \}
            i += 2
            continue

        if c == "~":
            out.append(" ")
            i += 1
            continue
        if c in "{}":
            i += 1
            continue
        if s.startswith("---", i):
            out.append("—")
            i += 3
            continue
        if s.startswith("--", i):
            out.append("–")
            i += 2
            continue

        out.append(c)
        i += 1

    text = "".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


# ------------------------------------------------------- known CV signatures --

# Positional meaning of the classes people actually use. `None` marks an
# argument the class prints but we have no column for.
SIGNATURES = {
    # moderncv
    "cventry": ("date_display", "title", "org", "location", "note", "_body"),
    "cvitem": ("_header", "_body"),
    "cvline": ("_header", "_body"),
    "cvlistitem": ("_body",),
    "cvdoubleitem": ("_header", "_body", None, None),
    "cvitemwithcomment": ("_header", "_body", "note"),
    # europecv
    "ecvitem": ("_header", "_body"),
    # currvita
    "cvitemshort": ("_header", "_body"),
}

HEADINGS = {"section", "subsection", "subsubsection", "chapter", "cvsection",
            "ecvsection", "resheading", "cvheading"}

LISTS = {"itemize", "enumerate", "description", "cvitems", "cvhonors",
         "cvsubentries", "highlights"}


def _bullets_from(doc: Doc, raw: str, base: int, parent: int) -> int:
    """`\\item` runs inside an argument or a list environment."""
    found = 0
    for m in re.finditer(r"\\item\b", raw):
        start = m.end()
        nxt = re.search(r"\\item\b|\\end\{", raw[start:])
        stop = start + (nxt.start() if nxt else len(raw) - start)
        body = flat(detex(raw[start:stop]))
        if not body:
            continue
        doc.add(Block(text=body, role="bullet", start=base + start,
                      end=base + stop, style={"of": parent}, rule="latex.item"))
        found += 1
    return found


# ---------------------------------------------------------------------- read --

def read(text: str) -> Doc:
    doc = Doc(text=text, kind="latex")

    cls = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", text)
    if cls:
        doc.meta["class"] = cls.group(1).strip()

    # Commands the author defined for themselves, and how many slots each has.
    # This is the template declaration the reviewer will map once.
    defined: dict[str, int] = {}
    for m in re.finditer(r"\\(?:newcommand|renewcommand|providecommand)\*?\s*"
                         r"\{?\\([A-Za-z]+)\}?\s*(?:\[(\d+)\])?", text):
        defined[m.group(1)] = int(m.group(2) or 0)
    doc.meta["defined"] = {k: v for k, v in defined.items() if v}

    # The preamble is real content but not CV content. Claiming it keeps the
    # coverage figure honest rather than flattering.
    body_at = 0
    begin = re.search(r"\\begin\s*\{document\}", text)
    if begin:
        body_at = begin.end()
        doc.add(Block(text=f"preamble ({doc.meta.get('class', 'unknown class')})",
                      role="meta", start=0, end=body_at, rule="latex.preamble"))

    i, run_start = body_at, body_at
    in_list = 0
    last_entry = -1

    def flush(upto: int) -> None:
        """Emit whatever plain text has accumulated since the last command."""
        nonlocal run_start
        raw = text[run_start:upto]
        if raw.strip():
            body = detex(raw)
            if body:
                doc.add(Block(text=body, role="para", start=run_start, end=upto,
                              rule="latex.text"))
        run_start = upto

    while i < len(text):
        c = text[i]

        if c == "%" and text[i - 1:i] != "\\":
            nl = text.find("\n", i)
            nl = len(text) if nl < 0 else nl
            flush(i)
            doc.add(Block(text=text[i:nl].strip(), role="meta", start=i, end=nl,
                          rule="latex.comment"))
            i = run_start = nl
            continue

        if c != "\\":
            i += 1
            continue

        m = CONTROL.match(text, i)
        if not m:
            i += 2
            continue
        name, start = m.group(1), i

        if name == "begin":
            got, after = _args(text, m.end(), 1)
            env = got[0].strip() if got else ""
            if env in LISTS:
                in_list += 1
                flush(start)
                run_start = after
            elif env == "document":
                pass
            i = after
            continue

        if name == "end":
            got, after = _args(text, m.end(), 1)
            env = got[0].strip() if got else ""
            if env in LISTS and in_list:
                in_list -= 1
                # The list body between begin and end holds the \item runs.
                _bullets_from(doc, text[run_start:start], run_start, last_entry)
                run_start = after
            i = after
            continue

        if name in HEADINGS:
            flush(start)
            got, after = _args(text, m.end(), 1)
            heading = flat(detex(got[0])) if got else ""
            doc.add(Block(text=heading, role="heading", start=start, end=after,
                          fields={"heading": heading}, rule="latex.section"))
            i = run_start = after
            continue

        if name == "item" and in_list:
            i = m.end()
            continue

        if name in SIGNATURES:
            flush(start)
            slots = SIGNATURES[name]
            got, after = _args(text, m.end(), len(slots))
            fields: dict[str, str] = {}
            body_raw = ""
            for slot, raw in zip(slots, got):
                value = flat(detex(raw))
                if slot is None or not value:
                    continue
                if slot == "_body":
                    body_raw = raw
                elif slot == "_header":
                    fields["date_display" if _is_datelike(value) else "note"] = value
                else:
                    fields[slot] = value
            if body_raw and "\\item" not in body_raw:
                fields.setdefault("summary", flat(detex(body_raw)))

            last_entry = start
            doc.add(Block(text=fields.get("title") or fields.get("org", ""),
                          role="entry", start=start, end=after, fields=fields,
                          rule=f"latex.{name}"))
            if body_raw and "\\item" in body_raw:
                _bullets_from(doc, body_raw, text.index(body_raw, start), start)
            i = run_start = after
            continue

        if name in defined and defined[name]:
            flush(start)
            got, after = _args(text, m.end(), defined[name])
            last_entry = start
            values = [flat(detex(a)) for a in got]
            doc.add(Block(
                text=" · ".join(v for v in values if v),
                role="template", start=start, end=after,
                fields={"_command": name, "_args": values},
                rule="latex.template"))
            i = run_start = after
            continue

        i = m.end()

    flush(len(text))
    return doc


def _is_datelike(value: str) -> bool:
    return bool(re.search(r"(?:19|20)\d{2}", value)) and len(value) <= 40
