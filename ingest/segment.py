"""Field sniffing and the generic segmenter — the rules that carry the formats
which did not tell us anything.

The reliable invariant of the genre: **every CV entry carries a date.** That is
what the segmenter leans on. A date-bearing line at entry level opens an entry;
lines under it that are not date-bearing belong to it; lines with a bullet
marker are bullets. Most of the work is done by that one observation.

The schema does the rest of the work for us, and it is worth saying why. Because
`date_display` prints verbatim and `start_ym`/`end_ym` exist only to sort, the
parser has to *locate* a date, never *understand* one. Locating is easy;
understanding is where date parsers go to die. Where the shape is recognisable
we derive the sort keys; where it isn't we leave them NULL, which the schema
already allows, and the reviewer fills them in.

What this module deliberately does NOT do is split an organisation from a title
when no separator says where the seam is. That is a coin flip dressed up as a
result. The whole line goes into `title` with `joined` set, and the review UI
offers a split the reviewer confirms once per section.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- dates ------

MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.?"
SEASON = r"(?:Spring|Summer|Autumn|Fall|Winter)"
YEAR = r"(?:1[89]|20)\d{2}"
POINT = rf"(?:(?:{MONTH}|{SEASON})\s+)?{YEAR}"
OPEN = r"(?:[Pp]resent|[Cc]urrent(?:ly)?|[Oo]ngoing|[Nn]ow)"
DASH = r"\s*(?:–|—|--|-|to|until|through)\s*"
PREFIX = r"(?:Expected|Anticipated|Forthcoming|In progress[,;]?|Since|From)\s+"

DATE = re.compile(rf"(?:{PREFIX})?{POINT}(?:{DASH}(?:{POINT}|{OPEN}))?")

MONTH_NUM = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05",
             "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
             "nov": "11", "dec": "12"}

# Sort keys only — these never print, so mapping a season to the middle of its
# quarter costs nothing and keeps "Autumn 2025" ordering after "Summer 2025".
SEASON_NUM = {"spring": "03", "summer": "06", "autumn": "09", "fall": "09",
              "winter": "12"}


def find_date(text: str) -> re.Match | None:
    """The date span in a line, if there is one."""
    return DATE.search(text)


def ym(point: str) -> str | None:
    """'Sept. 2025' → '2025-09'. 'YYYY' when no month is named."""
    year = re.search(YEAR, point)
    if not year:
        return None
    head = point[:year.start()].strip().lower().rstrip(".")
    if head[:3] in MONTH_NUM:
        return f"{year.group(0)}-{MONTH_NUM[head[:3]]}"
    if head in SEASON_NUM:
        return f"{year.group(0)}-{SEASON_NUM[head]}"
    return year.group(0)


def date_fields(display: str) -> dict:
    """`date_display` verbatim, plus whatever sort keys are derivable."""
    fields: dict[str, object] = {"date_display": display.strip()}
    points = re.findall(rf"(?:(?:{MONTH}|{SEASON})\s+)?{YEAR}", display)
    if points:
        fields["start_ym"] = ym(points[0])
    if len(points) > 1:
        fields["end_ym"] = ym(points[-1])
    elif re.search(OPEN, display):
        fields["is_current"] = 1
    return fields


# ------------------------------------------------------------- locations -----

STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR",
}

COUNTRIES = {
    "UK", "USA", "US", "Canada", "England", "Scotland", "Wales", "Ireland",
    "France", "Germany", "Italy", "Spain", "Portugal", "Netherlands", "Belgium",
    "Switzerland", "Austria", "Sweden", "Norway", "Denmark", "Finland",
    "Poland", "Greece", "Turkey", "Israel", "Jordan", "Lebanon", "Egypt",
    "Morocco", "India", "China", "Japan", "Korea", "Australia", "Mexico",
    "Brazil", "Argentina", "Chile", "Peru", "Kenya", "Ghana", "Nigeria",
    "South Africa", "New Zealand",
}

LOCATION = re.compile(
    r"\b([A-Z][\w.'’-]+(?:[ -][A-Z][\w.'’-]+)*),\s*"
    r"([A-Z]{2}\b|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")


def find_location(text: str) -> re.Match | None:
    """`City, ST` or `City, Country`, validated rather than pattern-matched.

    Without the validation this happily reads "Chicago, Director of Research"
    as a place, which is the kind of plausible wrong answer that costs a
    reviewer more time than a blank field would.
    """
    for m in LOCATION.finditer(text):
        tail = m.group(2)
        if tail in STATES or tail in COUNTRIES:
            return m
    return None


# ---------------------------------------------------------------- headings ---

# Canonical section names and the variants people actually write. Used to
# recognise a heading in formats that don't mark them, and to pick a `kind`.
HEADING_KINDS = (
    (r"publicat|articles|book chapters|books|papers|preprint|proceedings|"
     r"bibliograph|refereed|peer.reviewed|in print|edited volume", "publication"),
    (r"educat|degrees|academic training|dissertation|thesis|qualification",
     "education"),
    (r"project|software|exhibit|dataset|tool|portfolio|digital work", "project"),
)

HEADING_WORDS = (
    r"education|experience|employment|appointment|position|research|teaching|"
    r"publication|presentation|talk|lecture|conference|grant|fellowship|award|"
    r"honor|honour|service|skill|language|affiliation|membership|reference|"
    r"profile|summary|objective|interest|training|certification|exhibition|"
    r"project|review|workshop|volunteer|leadership|activities|professional"
)

IS_HEADING = re.compile(rf"^\s*(?:{HEADING_WORDS})\b", re.I)


def kind_for(heading: str | None) -> str:
    """Which `entry.kind` a section implies. `position` is the residual."""
    if heading:
        low = heading.lower()
        for pattern, kind in HEADING_KINDS:
            if re.search(pattern, low):
                return kind
    return "position"


def looks_like_heading(line: str) -> bool:
    """A standalone line that is naming a section rather than saying something.

    Three signals, any one of which is enough: it matches the vocabulary, it is
    shouted, or it is short and unpunctuated. Formats that tag their headings
    never come here — this is for `.txt` and for PDF text layers.
    """
    text = line.strip()
    if not text or len(text) > 70 or text.endswith((".", ",", ";", ":")):
        return bool(text) and len(text) <= 70 and text.endswith(":")
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.85:
        return True
    if IS_HEADING.match(text) and len(text.split()) <= 6:
        return True
    return False


# ------------------------------------------------------------------ sniffing --

BULLET_MARKER = re.compile(r"^\s*[•‣▪◦·*–—-]\s+(.*)$")


def sniff(line: str) -> dict:
    """Everything a single line will admit to, and nothing more.

    Date and location are extracted and removed; whatever is left goes into
    `title` whole. Splitting that remainder into organisation and title is the
    reviewer's one keystroke — see the module docstring.
    """
    fields: dict[str, object] = {}
    rest = line.strip()

    date = find_date(rest)
    if date:
        fields.update(date_fields(date.group(0)))
        rest = (rest[:date.start()] + " " + rest[date.end():]).strip()

    place = find_location(rest)
    if place:
        fields["location"] = place.group(0).strip()
        rest = (rest[:place.start()] + " " + rest[place.end():]).strip()

    rest = re.sub(r"\s{2,}", " ", rest).strip(" ,;·|–—-")
    if rest:
        # An explicit separator is the one case where the seam is stated, not
        # inferred, so it is the one case we act on.
        split = re.split(r"\s+[—–]\s+|\s+\|\s+", rest, maxsplit=1)
        if len(split) == 2 and all(p.strip() for p in split):
            fields["org"], fields["title"] = split[0].strip(), split[1].strip()
        else:
            fields["title"] = rest
            fields["_joined"] = True
    return fields


def sniff_template(args: list[str]) -> dict:
    """Assign a user-defined command's positional arguments by what they look like.

    A `\\newcommand` says how many fields there are but not what they mean.
    Dates and places identify themselves; of what remains, the longest argument
    is the description and the first is the headline. Whatever this gets wrong,
    the reviewer corrects once for the command — not once per use.
    """
    fields: dict[str, object] = {}
    leftover: list[tuple[int, str]] = []

    for index, value in enumerate(args):
        value = value.strip()
        if not value:
            continue
        if "date_display" not in fields and find_date(value) and len(value) <= 40:
            fields.update(date_fields(value))
        elif "location" not in fields and find_location(value):
            fields["location"] = value
        else:
            leftover.append((index, value))

    if leftover:
        longest = max(leftover, key=lambda p: len(p[1]))
        if len(longest[1]) > 90:
            fields["summary"] = longest[1]
            leftover = [p for p in leftover if p[0] != longest[0]]
    if leftover:
        fields["title"] = leftover[0][1]
    if len(leftover) > 1:
        fields["org"] = leftover[1][1]
    if len(leftover) > 2:
        fields["note"] = "; ".join(v for _, v in leftover[2:])
    return fields


# ----------------------------------------------------------------- segmenting --

def segment(doc) -> None:
    """Refine a Doc in place: paragraphs into entries, kinds from headings.

    Only paragraphs that actually contain dated lines are broken up. A section
    of continuous prose — a Profile, or Owens' paragraph-per-appointment style —
    has no entry structure to find, so it stays whole and becomes a summary.
    Splitting it would invent boundaries that aren't there.
    """
    from .ir import Block

    heading: str | None = None
    rebuilt: list = []
    run: list = []          # consecutive paragraphs, pending coalescence

    def flush() -> None:
        """Segment the paragraphs gathered so far as one region.

        Word gives every paragraph its own block, so an entry's title line and
        its date line arrive separately and neither can see the other. Plain
        text hands over the whole section at once, which is why it segments
        correctly and .docx did not. Re-slicing the source between the first
        and last paragraph restores that view — and taking the slice from
        `doc.text` rather than joining the block texts keeps every offset
        exact, which the coverage check depends on.
        """
        if not run:
            return
        block = run[0] if len(run) == 1 else Block(
            text=doc.text[run[0].start:run[-1].end], role="para",
            start=run[0].start, end=run[-1].end,
            style=dict(run[0].style), rule="segment.joined")
        children = _split_para(doc, block, heading, Block)
        rebuilt.extend(children if children else [block])
        run.clear()

    for block in doc.blocks:
        if block.role != "para":
            flush()

        if block.role == "heading":
            heading = block.text
            rebuilt.append(block)
            continue

        if block.role in ("entry", "template"):
            block.style.setdefault("heading", heading)
            if "_table" not in block.fields:
                block.fields.setdefault("kind", kind_for(heading))
            if block.role == "template":
                block.fields.update(sniff_template(block.fields.get("_args", [])))
                block.fields.setdefault("kind", kind_for(heading))
            rebuilt.append(block)
            continue

        if block.role != "para":
            rebuilt.append(block)
            continue

        run.append(block)

    flush()
    doc.blocks = rebuilt


def _split_para(doc, block, heading, Block) -> list:
    """One paragraph into entry and bullet blocks, or nothing if it has no dates."""
    lines = block.text.splitlines(keepends=True)
    if not any(find_date(l) for l in lines):
        block.style.setdefault("heading", heading)
        return []

    out: list = []
    offset = 0
    current: object = None

    for line in lines:
        start = block.start + offset
        offset += len(line)
        stripped = line.strip()
        if not stripped:
            continue

        marker = BULLET_MARKER.match(line)
        if marker and current is not None:
            out.append(Block(text=marker.group(1).strip(), role="bullet",
                             start=start + marker.start(1),
                             end=start + marker.end(1),
                             style={"of": current.start}, rule="segment.bullet"))
            continue

        if find_date(stripped) or current is None:
            fields = sniff(stripped)

            # A bare date line directly beneath an entry that has no date yet
            # COMPLETES that entry instead of opening a second one. Every CV
            # entry carries a date, so "Newberry Library — Research Fellow"
            # and "Sept. 2024 – Present" are two halves of one entry. Only
            # fold when the line offers nothing but a date and a place: a line
            # naming an organisation is a new entry however many dates it has.
            if (current is not None
                    and current.role == "entry"
                    and not current.fields.get("date_display")
                    and fields.get("date_display")
                    and not fields.get("org") and not fields.get("title")):
                for key, value in fields.items():
                    current.fields.setdefault(key, value)
                current.end = start + len(line.rstrip("\n"))
                continue

            fields["kind"] = kind_for(heading)
            current = Block(text=stripped, role="entry", start=start,
                            end=start + len(line.rstrip("\n")), fields=fields,
                            style={"heading": heading,
                                   "joined": fields.pop("_joined", False)},
                            rule="segment.entry")
            out.append(current)
            continue

        # An undated line under an entry is its qualifier — department,
        # advisor, supervisor. That is exactly what `note` is for.
        if current is not None and not current.fields.get("note"):
            current.fields["note"] = stripped
            current.end = start + len(line.rstrip("\n"))
        else:
            out.append(Block(text=stripped, role="line", start=start,
                             end=start + len(line.rstrip("\n")),
                             style={"heading": heading}, rule="segment.loose"))
    return out
