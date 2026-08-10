"""Typst in, blocks out — the exact inverse of `cv_typst.render`.

This reader exists twice over. Obviously, so a CV built with this tool can be
read back into it. Less obviously, and more usefully: it is the only reader
whose correct answer is *knowable*, because `cv_typst.py` wrote the file. So
`parse(render(rows))` is a test with no judgement in it, and it exercises the
whole spine — blocks, spans, coverage, proposals — before any lossy format
gets near it. When the round-trip test fails, the bug is real.

WHAT ROUND-TRIPS EXACTLY: `#entry` — org, role, dates, location, note, and
every bullet, since the renderer writes each field to its own named argument.

WHAT DOES NOT, AND CANNOT: `#item` and `#line-item` *join* fields on the way
out — a line-item's body is `title, org, location` run together with commas,
and no reader can know where the seams were. `entry.kind` is not written at all;
the template picks a shape from whether bullets exist, not from the kind. Those
come back as a single field with the join intact, and the reviewer splits them.
Guessing the seam is exactly the kind of confident wrong answer this design is
meant to avoid, so the parser declines to.
"""

from __future__ import annotations

import re

from .ir import Block, Doc

IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
NAMED = re.compile(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)\Z", re.S)
BULLET = re.compile(r"^[ \t]*-[ \t]+(.*)$")

# From cv_typst.MARKUP_SPECIALS. Kept as a literal rather than imported so the
# reader stays usable on a Typst file this tool did not write.
MARKUP_SPECIALS = "\\#$*_`<>@[]~"


# ------------------------------------------------------------------ scanning --

def _scan(text: str, i: int, open_ch: str, close_ch: str) -> int:
    """`text[i]` is `open_ch`; return the index just past its partner.

    Strings and backslash escapes are transparent, which matters because
    `esc_markup` escapes `[` and `]` — an unescaped bracket really is
    structure, and an escaped one really is a character.
    """
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            i = _scan_string(text, i)
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError(f"unbalanced {open_ch!r} at {i}")


def _scan_string(text: str, i: int) -> int:
    """`text[i]` is the opening quote; return the index just past the closing one."""
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    raise ValueError("unterminated string")


def _split_top(body: str) -> list[str]:
    """A `(...)` body split on its top-level commas."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            i = _scan_string(body, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(body[start:i])
            start = i + 1
        i += 1
    if body[start:].strip():
        parts.append(body[start:])
    return parts


def unesc_string(s: str) -> str:
    """Inverse of `cv_typst.esc_string`."""
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def unesc_markup(s: str) -> str:
    """Inverse of `cv_typst.esc_markup`.

    Only the characters the renderer escapes are unescaped, so a backslash that
    was always a backslash survives as one.
    """
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in MARKUP_SPECIALS + "-+=/":
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _value(raw: str) -> str:
    """Decode one argument value: a quoted string, a content block, or neither."""
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return unesc_string(raw[1:-1])
    if raw.startswith("[") and raw.endswith("]"):
        return unesc_markup(raw[1:-1]).strip()
    return raw


def _args(body: str) -> tuple[dict[str, str], list[str]]:
    """Named and positional arguments of a call, decoded."""
    named: dict[str, str] = {}
    positional: list[str] = []
    for part in _split_top(body):
        m = NAMED.match(part)
        if m and not part.strip().startswith(("[", '"', "(")):
            named[m.group(1)] = _value(m.group(2))
        elif part.strip():
            positional.append(_value(part))
    return named, positional


def _call(text: str, i: int) -> tuple[dict, list, str, int] | None:
    """Parse `#name(...)[...]` starting at the `#`.

    Returns (named args, positional args, content body, end offset). Both the
    parens and the trailing content block are optional — `#skill-line[English]`
    and `#item[...]` are as legal as the full form.
    """
    m = IDENT.match(text, i + 1)
    if not m:
        return None
    j = m.end()

    named, positional = {}, []
    if j < len(text) and text[j] == "(":
        end = _scan(text, j, "(", ")")
        named, positional = _args(text[j + 1:end - 1])
        j = end

    content = ""
    if j < len(text) and text[j] == "[":
        end = _scan(text, j, "[", "]")
        content = text[j + 1:end - 1]
        j = end

    return named, positional, content, j


# ------------------------------------------------------------------ handlers --

def _bullets(doc: Doc, content: str, base: int, parent_start: int) -> int:
    """Bullet blocks for a `#entry` body. Returns how many were found."""
    found, offset = 0, 0
    for line in content.splitlines(keepends=True):
        m = BULLET.match(line.rstrip("\n"))
        if m:
            start = base + offset + m.start(1)
            doc.add(Block(
                text=unesc_markup(m.group(1)).strip(),
                role="bullet",
                start=start,
                end=start + len(m.group(1)),
                style={"of": parent_start},
                rule="typst.bullet",
            ))
            found += 1
        offset += len(line)
    return found


def _read_header(doc: Doc, named: dict, start: int, end: int) -> None:
    """`#show: cv.with(...)` — the name, subtitle, and contact line."""
    doc.meta["name"] = named.get("name", "")
    if named.get("subtitle"):
        doc.meta["subtitle"] = named["subtitle"]
    if named.get("paper"):
        doc.meta["paper"] = named["paper"]

    contacts = []
    raw = named.get("contacts", "")
    if raw.startswith("(") and raw.endswith(")"):
        for part in _split_top(raw[1:-1]):
            part = part.strip()
            link = re.match(r'link\(\s*"((?:[^"\\]|\\.)*)"\s*\)\s*\[(.*)\]\Z', part, re.S)
            if link:
                contacts.append({"value": unesc_string(link.group(1)),
                                 "display": unesc_markup(link.group(2))})
            elif part.startswith('"'):
                shown = _value(part)
                contacts.append({"value": shown, "display": shown})
    doc.meta["contacts"] = contacts

    doc.add(Block(text=named.get("name", ""), role="meta", start=start, end=end,
                  fields={"contacts": contacts}, rule="typst.header"))


def _read_item(doc: Doc, named: dict, content: str, start: int, end: int) -> None:
    """`#item` — undo `render_item`, but only where the seam is unambiguous.

    Two shapes come out of the renderer. A publication puts `org, date` in the
    note and the citation in the body. Everything else bolds the organisation
    into the body as `*org* — rest` and puts `date · location` in the note. The
    leading `*` is the tell, and it is reliable: `esc_markup` escapes any
    asterisk that came from the text itself.
    """
    body = unesc_markup(content).strip()
    note = named.get("note", "")
    fields: dict[str, str] = {}

    bolded = re.match(r"\*(.+?)\*\s+—\s+(.+)\Z", body, re.S)
    if bolded:
        fields["org"] = bolded.group(1).strip()
        fields["title"] = bolded.group(2).strip()
        parts = [p.strip() for p in note.split("·") if p.strip()]
        if parts:
            fields["date_display"] = parts[0]
        if len(parts) > 1:
            fields["location"] = parts[1]
    else:
        fields["kind"] = "publication"
        fields["summary"] = body
        # `org, date` — split on the last comma only when the tail reads as a date.
        m = re.match(r"(.*),\s*([^,]*\d{4}[^,]*)\Z", note)
        if m:
            fields["org"] = m.group(1).strip()
            fields["date_display"] = m.group(2).strip()
        elif note:
            fields["org"] = note

    doc.add(Block(text=body, role="entry", start=start, end=end,
                  fields=fields, rule="typst.item"))


def _read_line_item(doc: Doc, named: dict, content: str, start: int, end: int) -> None:
    """`#line-item` — the date is separate, the rest is welded together.

    `render_line_item` joins title, organisation, and location into one string
    with commas, and `join_tail` varies the punctuation by whether the head
    ended a sentence. That is not invertible, so the whole body goes into
    `title` and the reviewer splits it. Deliberately not guessed.
    """
    body = unesc_markup(content).strip()
    fields = {"title": body}
    if named.get("date"):
        fields["date_display"] = named["date"]
    doc.add(Block(text=body, role="entry", start=start, end=end, fields=fields,
                  style={"joined": True}, rule="typst.line-item"))


def _read_skill(doc: Doc, positional: list, content: str, start: int, end: int) -> None:
    """`#skill("Category")[a, b (detail), c]`.

    Splitting on `, ` is the inverse of the renderer's join and is lossy for a
    skill whose own name contains a comma. Rare enough to accept, common
    enough to say out loud.
    """
    category = positional[0] if positional else ""
    for name in unesc_markup(content).split(","):
        name = name.strip()
        if not name:
            continue
        detail = None
        m = re.match(r"(.+?)\s*\(([^()]*)\)\Z", name)
        if m:
            name, detail = m.group(1).strip(), m.group(2).strip()
        doc.add(Block(text=name, role="entry", start=start, end=end,
                      fields={"_table": "skill", "name": name,
                              "category": category, "detail": detail},
                      rule="typst.skill"))


def _read_skill_line(doc: Doc, named: dict, content: str, start: int, end: int) -> None:
    """`#skill-line` prints no category — the heading was doing that job."""
    doc.add(Block(text=unesc_markup(content).strip(), role="entry",
                  start=start, end=end,
                  fields={"_table": "skill", "name": unesc_markup(content).strip(),
                          "category": None, "detail": named.get("detail")},
                  rule="typst.skill-line"))


def _read_reference(doc: Doc, named: dict, positional: list, content: str,
                    start: int, end: int) -> None:
    """`#reference` stacks whichever fields were non-empty, so position alone
    cannot say which is which. Email and phone identify themselves; the rest
    keep their printed order — title, org, department, then address."""
    name = positional[0] if positional else unesc_markup(content).strip()
    fields = {"_table": "reference", "name": name}

    lines: list[str] = []
    raw = named.get("lines", "")
    if raw.startswith("(") and raw.endswith(")"):
        lines = [_value(p) for p in _split_top(raw[1:-1]) if p.strip()]

    rest = []
    for line in lines:
        if "@" in line and " " not in line.strip():
            fields["email"] = line
        elif re.fullmatch(r"[-+().\d\sxX]{7,}", line):
            fields["phone"] = line
        else:
            rest.append(line)
    for key, value in zip(("title", "org", "department"), rest):
        fields[key] = value
    if len(rest) > 3:
        fields["address"] = "\n".join(rest[3:])

    doc.add(Block(text=name, role="entry", start=start, end=end, fields=fields,
                  rule="typst.reference"))


# ---------------------------------------------------------------------- read --

def read(text: str) -> Doc:
    doc = Doc(text=text, kind="typst")
    i = 0
    loose = 0        # start of text no construct has claimed yet

    def flush(upto: int) -> None:
        """Bare markup between calls — a `profile` section is exactly this.

        `render()` writes a profile's prose with no wrapper around it, so a
        reader that only claims `#`-prefixed calls silently drops it. Coverage
        is what caught that on a real file; this is the fix.
        """
        nonlocal loose
        raw = text[loose:upto]
        if raw.strip():
            doc.add(Block(text=unesc_markup(raw).strip(), role="para",
                          start=loose + (len(raw) - len(raw.lstrip())),
                          end=loose + len(raw.rstrip()), rule="typst.prose"))
        loose = upto

    while i < len(text):
        c = text[i]

        if c == "/" and text.startswith("//", i):
            flush(i)
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            doc.add(Block(text=text[i:end].strip(), role="meta", start=i, end=end,
                          rule="typst.comment"))
            i = loose = end
            continue

        if c != "#" or (i and text[i - 1] == "\\"):
            i += 1
            continue

        m = IDENT.match(text, i + 1)
        if not m:
            i += 1
            continue
        name = m.group(0)

        # `#show: cv.with(...)` is a rule, not a call — find its argument list.
        if name == "show":
            flush(i)
            open_paren = text.find("(", m.end())
            if open_paren < 0:
                i = m.end()
                continue
            try:
                end = _scan(text, open_paren, "(", ")")
            except ValueError:
                doc.notes.append("unbalanced `#show: cv.with(` — header skipped")
                i = m.end()
                continue
            named, _ = _args(text[open_paren + 1:end - 1])
            _read_header(doc, named, i, end)
            i = loose = end
            continue

        if name == "import":
            flush(i)
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            doc.add(Block(text=text[i:end], role="meta", start=i, end=end,
                          rule="typst.import"))
            i = loose = end
            continue

        if name not in ("section", "entry", "item", "line-item", "skill",
                        "skill-line", "reference"):
            i = m.end()
            continue

        flush(i)
        try:
            parsed = _call(text, i)
        except ValueError as exc:
            doc.notes.append(f"{name} at {i}: {exc}")
            i = m.end()
            continue
        if parsed is None:
            i = m.end()
            continue
        named, positional, content, end = parsed

        if name == "section":
            heading = positional[0] if positional else ""
            doc.add(Block(text=heading, role="heading", start=i, end=end,
                          fields={"heading": heading}, rule="typst.section"))

        elif name == "entry":
            fields = {k: v for k, v in (
                ("org", named.get("org")),
                ("title", named.get("role")),
                ("date_display", named.get("dates")),
                ("location", named.get("location")),
                ("note", named.get("note")),
            ) if v}
            # The bullets sit inside this span; nesting is fine for coverage
            # and is what tells the promoter which entry they belong to.
            body_start = text.rindex("[", i, end) + 1
            doc.add(Block(text=named.get("org", "") or named.get("role", ""),
                          role="entry", start=i, end=end, fields=fields,
                          rule="typst.entry"))
            _bullets(doc, content, body_start, i)

        elif name == "item":
            _read_item(doc, named, content, i, end)
        elif name == "line-item":
            _read_line_item(doc, named, content, i, end)
        elif name == "skill":
            _read_skill(doc, positional, content, i, end)
        elif name == "skill-line":
            _read_skill_line(doc, named, content, i, end)
        elif name == "reference":
            _read_reference(doc, named, positional, content, i, end)

        i = loose = end

    flush(len(text))
    return doc
