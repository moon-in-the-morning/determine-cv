#!/usr/bin/env python3
"""    python3 -m unittest discover -s ingest -t .

The one that matters is `TestRoundTrip`. `cv_typst.render()` wrote the file, so
the correct parse is not a matter of opinion — every assertion in it is a fact
about the renderer, not a judgement about a CV. It exercises the whole spine
(blocks, spans, coverage, proposals) with no fixture to argue with, which is
why it is worth having before any lossy format is admitted.

`test_coverage_is_total` is the one to watch. It asserts that a file this tool
wrote is accounted for down to the character, and it is the property the design
sells: text the parser cannot place has to show up as a gap, so a gap of zero
on a known-good file means the accounting is real and not merely plausible.
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv_typst                                              # noqa: E402
from ingest import parse, propose, read                      # noqa: E402
from ingest.detect import detect                             # noqa: E402
from ingest.ir import coverage                               # noqa: E402
from ingest.latex import detex                               # noqa: E402
from ingest.segment import (date_fields, find_date, find_location,  # noqa: E402
                            kind_for, segment, sniff)
from ingest.typst import unesc_markup, unesc_string          # noqa: E402

SCHEMA = (ROOT / "db" / "schema.sql").read_text()

ENTRIES = [
    # kind, org, title, note, location, date_display, bullets
    ("position", "Museum of Natural History", "Provenance Research Intern",
     "Anthropology Department; supervisor: Dr. A. Reyes", "Chicago, IL",
     "Sept. 2025 – June 2026",
     ["Catalogued 1,400 objects against the NAGPRA inventory.",
      "Wrote the *first* pass of a [tricky] summary — with #markup in it."]),
    ("education", "University of Chicago", "MA, Anthropology",
     "Advisor: Dr. B. Okonkwo", "Chicago, IL", "2023 – 2025", []),
    ("position", "Field Museum", "Collections Assistant", None, "Chicago, IL",
     "Summer 2022", ["Ran the EMu migration."]),
]


def build() -> sqlite3.Connection:
    """A small library and one document over it, in memory."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)

    con.execute("INSERT INTO profile (id, full_name, pronouns, summary) "
                "VALUES (1, 'Moon Goldstein', 'they/them', 'A short profile.')")
    for order, (kind, value, display) in enumerate([
            ("email", "mailto:moony@uchicago.edu", "moony@uchicago.edu"),
            ("city", "Chicago, IL", None)]):
        con.execute("INSERT INTO contact (profile_id, kind, value, display, "
                    "sort_order) VALUES (1,?,?,?,?)", (kind, value, display, order))

    for kind, org, title, note, location, dates, bullets in ENTRIES:
        entry_id = con.execute(
            "INSERT INTO entry (kind, org, title, note, location, date_display) "
            "VALUES (?,?,?,?,?,?)",
            (kind, org, title, note, location, dates)).lastrowid
        for order, text in enumerate(bullets):
            con.execute("INSERT INTO bullet (entry_id, text, sort_order) "
                        "VALUES (?,?,?)", (entry_id, text, order))

    for order, (name, category, detail) in enumerate([
            ("Python", "Technical", None),
            ("EMu collections management", "Technical", None),
            ("Levantine Arabic", "Languages", "A2")]):
        con.execute("INSERT INTO skill (name, category, detail, sort_order) "
                    "VALUES (?,?,?,?)", (name, category, detail, order))

    con.execute("INSERT INTO reference (name, title, org, email, phone) "
                "VALUES ('Dr. Helen Robbins', 'Repatriation Director', "
                "'Field Museum of Natural History', 'hrobbins@example.org', "
                "'+1 312 555 0142')")

    document_id = con.execute(
        "INSERT INTO document (slug, title) VALUES ('full-cv', 'Full CV')"
    ).lastrowid
    sections = {}
    for order, (heading, style) in enumerate([
            ("Research Experience", "entries"), ("Education", "entries"),
            ("Technical Skills", "skills"), ("References", "references")]):
        sections[heading] = con.execute(
            "INSERT INTO section (document_id, heading, style, sort_order) "
            "VALUES (?,?,?,?)", (document_id, heading, style, order)).lastrowid

    placement = [(1, "Research Experience"), (2, "Education"),
                 (3, "Research Experience")]
    for order, (entry_id, heading) in enumerate(placement):
        con.execute("INSERT INTO doc_entry (document_id, entry_id, section_id, "
                    "sort_order) VALUES (?,?,?,?)",
                    (document_id, entry_id, sections[heading], order))
    for skill_id in (1, 2, 3):
        con.execute("INSERT INTO doc_skill (document_id, skill_id) VALUES (?,?)",
                    (document_id, skill_id))
    con.execute("INSERT INTO doc_reference (document_id, reference_id) VALUES (?,1)",
                (document_id,))
    con.commit()
    return con


class TestRoundTrip(unittest.TestCase):
    """render() then parse() — the renderer wrote it, so the answer is known."""

    @classmethod
    def setUpClass(cls):
        cls.con = build()
        cls.source = cv_typst.render(cls.con, 1)
        cls.parsed = parse("cv.generated.typ", cls.source.encode())[0]
        cls.entries = [p for p in cls.parsed.proposals if p.target == "entry"]
        cls.bullets = [p for p in cls.parsed.proposals if p.target == "bullet"]

    def test_kind_detected(self):
        self.assertEqual(detect("cv.generated.typ", self.source.encode()), "typst")
        self.assertEqual(detect("nameless", self.source.encode()), "typst")

    def test_coverage_is_total(self):
        """Nothing this tool wrote should be text the parser cannot place."""
        fraction, gaps = coverage(self.parsed.doc)
        detail = "\n".join(repr(g.text[:80]) for g in gaps)
        self.assertEqual(gaps, [], f"unplaced text in our own output:\n{detail}")
        self.assertEqual(fraction, 1.0)

    def test_every_entry_came_back(self):
        self.assertEqual(len(self.entries), len(ENTRIES))

    def test_document_order_not_library_order(self):
        """The renderer writes section by section, so the parse comes back in
        print order. That is the correct answer, not a bug to sort away."""
        self.assertEqual([p.payload.get("org") for p in self.entries],
                         ["Museum of Natural History", "Field Museum",
                          "University of Chicago"])

    def test_fields_survive_exactly(self):
        """An entry WITH bullets renders as `#entry`, one field per named
        argument, so every column comes back untouched."""
        by_org = {p.payload.get("org"): p.payload for p in self.entries}
        for _, org, title, note, location, dates, bullets in ENTRIES:
            if not bullets:
                continue
            with self.subTest(org=org):
                got = by_org[org]
                self.assertEqual(got.get("title"), title)
                self.assertEqual(got.get("date_display"), dates)
                self.assertEqual(got.get("location"), location)
                self.assertEqual(got.get("note"), note)

    def test_bulletless_entries_lose_their_note(self):
        """An entry WITHOUT bullets renders as `#item`, and `render_item`
        reuses that shape's note line for `dates · location` — so the entry's
        own `note` column is never written to the page at all.

        The parser is right to return None here; there is nothing in the file
        to return. This is a lossy path in the RENDERER, and it is the reason
        to have a round-trip test: `entry.note` is a column you can fill in the
        library and never see printed, and nothing else would have said so.
        """
        uchicago = next(p.payload for p in self.entries
                        if p.payload.get("org") == "University of Chicago")
        self.assertIsNone(uchicago.get("note"))
        self.assertNotIn("Okonkwo", self.source)

        # Everything the `#item` shape *does* carry still survives the trip.
        self.assertEqual(uchicago.get("title"), "MA, Anthropology")
        self.assertEqual(uchicago.get("date_display"), "2023 – 2025")
        self.assertEqual(uchicago.get("location"), "Chicago, IL")

    def test_bullets_survive_with_their_markup(self):
        expected = [b for e in ENTRIES for b in e[6]]
        self.assertEqual([b.payload["text"] for b in self.bullets], expected)

    def test_bullets_hang_under_the_right_entry(self):
        parents = {}
        for bullet in self.bullets:
            owner = self.parsed.proposals[bullet.parent]
            parents.setdefault(owner.payload.get("org"), []).append(
                bullet.payload["text"])
        self.assertEqual(parents["Museum of Natural History"], ENTRIES[0][6])
        self.assertEqual(parents["Field Museum"], ENTRIES[2][6])

    def test_kind_comes_from_the_heading_not_the_row(self):
        """`kind` is not written to Typst at all, so it has to be inferred —
        and the section heading is the only evidence there is."""
        by_org = {p.payload.get("org"): p.payload.get("kind") for p in self.entries}
        self.assertEqual(by_org["University of Chicago"], "education")
        self.assertEqual(by_org["Museum of Natural History"], "position")

    def test_skills_and_their_categories(self):
        skills = [p.payload for p in self.parsed.proposals if p.target == "skill"]
        self.assertEqual(
            [(s["name"], s["category"], s["detail"]) for s in skills],
            [("Python", "Technical", None),
             ("EMu collections management", "Technical", None),
             ("Levantine Arabic", "Languages", "A2")])

    def test_reference_fields_are_identified_not_positional(self):
        ref = next(p.payload for p in self.parsed.proposals
                   if p.target == "reference")
        self.assertEqual(ref["name"], "Dr. Helen Robbins")
        self.assertEqual(ref["email"], "hrobbins@example.org")
        self.assertEqual(ref["phone"], "+1 312 555 0142")
        self.assertEqual(ref["title"], "Repatriation Director")
        self.assertEqual(ref["org"], "Field Museum of Natural History")

    def test_profile_and_contacts(self):
        profile = next(p.payload for p in self.parsed.proposals
                       if p.target == "profile")
        self.assertEqual(profile["full_name"], "Moon Goldstein")
        contacts = [p.payload for p in self.parsed.proposals
                    if p.target == "contact"]
        self.assertEqual(contacts[0]["kind"], "email")
        self.assertEqual(contacts[0]["value"], "mailto:moony@uchicago.edu")
        self.assertEqual(contacts[1]["kind"], "city")

    def test_quotes_point_at_real_source(self):
        for proposal in self.parsed.proposals:
            if proposal.end > proposal.start:
                self.assertEqual(
                    proposal.quote,
                    self.source[proposal.start:proposal.end][:400])

    def test_parsing_is_deterministic(self):
        again = parse("cv.generated.typ", self.source.encode())[0]
        self.assertEqual([(p.target, p.payload, p.start, p.end)
                          for p in again.proposals],
                         [(p.target, p.payload, p.start, p.end)
                          for p in self.parsed.proposals])


class TestEscaping(unittest.TestCase):
    def test_markup_and_string_escapes_invert(self):
        for text in ['He said "hi" — a \\ backslash',
                     "*bold* #call [brackets] <angle> ~tilde @at",
                     "- leading dash", "= leading equals"]:
            self.assertEqual(unesc_markup(cv_typst.esc_markup(text)), text)
            self.assertEqual(unesc_string(cv_typst.esc_string(text)), text)


class TestDates(unittest.TestCase):
    def test_shapes_found(self):
        for text in ["Sept. 2025 – June 2026", "2019–present", "Autumn 2025",
                     "Expected June 2027", "2015-2018", "January 2020 to March 2021",
                     "Summer 2022"]:
            with self.subTest(text=text):
                self.assertIsNotNone(find_date(text), text)

    def test_sort_keys_derived(self):
        self.assertEqual(date_fields("Sept. 2025 – June 2026"),
                         {"date_display": "Sept. 2025 – June 2026",
                          "start_ym": "2025-09", "end_ym": "2026-06"})
        self.assertEqual(date_fields("2019–present")["is_current"], 1)
        self.assertEqual(date_fields("Autumn 2025")["start_ym"], "2025-09")

    def test_display_is_never_normalised(self):
        """The whole reason locating beats understanding."""
        for text in ["Sept. 2025 – June 2026", "Expected June 2027", "2019–present"]:
            self.assertEqual(date_fields(text)["date_display"], text)


class TestLocations(unittest.TestCase):
    def test_real_places(self):
        self.assertEqual(find_location("Chicago, IL").group(0), "Chicago, IL")
        self.assertEqual(find_location("Cambridge, UK").group(0), "Cambridge, UK")
        self.assertEqual(
            find_location("New Haven, CT").group(0), "New Haven, CT")

    def test_not_a_place(self):
        """Validated, not pattern-matched — the whole point."""
        self.assertIsNone(find_location("Chicago, Director of Research"))
        self.assertIsNone(find_location("Robbins, Helen"))


class TestSniff(unittest.TestCase):
    def test_explicit_separator_is_split(self):
        got = sniff("Field Museum — Collections Assistant, Summer 2022, Chicago, IL")
        self.assertEqual(got["org"], "Field Museum")
        self.assertEqual(got["date_display"], "Summer 2022")
        self.assertEqual(got["location"], "Chicago, IL")

    def test_no_separator_is_left_joined(self):
        """A coin flip declined, on purpose."""
        got = sniff("Field Museum Collections Assistant 2022")
        self.assertTrue(got.get("_joined"))
        self.assertNotIn("org", got)


class TestLatex(unittest.TestCase):
    SOURCE = r"""
\documentclass[11pt]{moderncv}
\newcommand{\job}[4]{\textbf{#2} #1 \\ #3 \\ #4}
\begin{document}
\section{Experience}
\cventry{Sept. 2025 -- June 2026}{Provenance Research Intern}{Museum of
Natural History}{Chicago, IL}{Anthropology Department}{
  \begin{itemize}
    \item Catalogued 1,400 objects against the NAGPRA inventory.
    \item Ran the EMu migration.
  \end{itemize}}
\section{Education}
\job{2023 -- 2025}{MA, Anthropology}{University of Chicago}{Chicago, IL}
\end{document}
"""

    def setUp(self):
        self.parsed = parse("cv.tex", self.SOURCE.encode())[0]

    def test_class_and_user_commands_noticed(self):
        self.assertEqual(self.parsed.doc.meta["class"], "moderncv")
        self.assertEqual(self.parsed.doc.meta["defined"], {"job": 4})

    def test_known_signature_maps_without_guessing(self):
        entry = next(p for p in self.parsed.proposals if p.rule == "latex.cventry")
        self.assertEqual(entry.payload["title"], "Provenance Research Intern")
        self.assertEqual(entry.payload["org"], "Museum of Natural History")
        self.assertEqual(entry.payload["location"], "Chicago, IL")
        self.assertEqual(entry.payload["date_display"], "Sept. 2025 – June 2026")

    def test_bullets_found_inside_the_argument(self):
        bullets = [p.payload["text"] for p in self.parsed.proposals
                   if p.target == "bullet"]
        self.assertEqual(bullets, [
            "Catalogued 1,400 objects against the NAGPRA inventory.",
            "Ran the EMu migration."])

    def test_user_command_becomes_a_template(self):
        """Arity from \\newcommand, fields sniffed, one confirmation for all uses."""
        entry = next(p for p in self.parsed.proposals if p.rule == "latex.template")
        self.assertEqual(entry.payload["date_display"], "2023 – 2025")
        self.assertEqual(entry.payload["location"], "Chicago, IL")
        self.assertEqual(entry.payload["kind"], "education")

    def test_detex_handles_accents_and_escapes(self):
        self.assertEqual(detex(r"Nicola Carboni, \'Ecole \& Mus\'ee"),
                         "Nicola Carboni, École & Musée")
        self.assertEqual(detex(r"\textbf{Bold} and \emph{italic}"),
                         "Bold and italic")
        self.assertEqual(detex(r"Stra\ss e \c{c}edilla"), "Straße çedilla")


class TestMarkdownAndText(unittest.TestCase):
    MD = """# Moon Goldstein

## Research Experience

Museum of Natural History — Provenance Research Intern
Sept. 2025 – June 2026 · Chicago, IL

- Catalogued **1,400** objects.
- Ran the [EMu migration](https://example.org).

## Education

University of Chicago — MA, Anthropology, 2023 – 2025
"""

    def test_markdown_headings_and_bullets(self):
        parsed = parse("cv.md", self.MD.encode())[0]
        headings = [b.text for b in parsed.doc.blocks if b.role == "heading"]
        self.assertIn("Research Experience", headings)
        bullets = [p.payload["text"] for p in parsed.proposals
                   if p.target == "bullet"]
        self.assertEqual(bullets,
                         ["Catalogued 1,400 objects.", "Ran the EMu migration."])

    def test_markdown_kind_from_heading(self):
        parsed = parse("cv.md", self.MD.encode())[0]
        education = [p for p in parsed.proposals
                     if p.target == "entry"
                     and p.payload.get("kind") == "education"]
        self.assertTrue(education)

    def test_plain_text_headings_are_recognised(self):
        text = ("EDUCATION\n\n"
                "University of Chicago — MA, Anthropology\n"
                "2023 – 2025 · Chicago, IL\n")
        parsed = parse("cv.txt", text.encode())[0]
        headings = [b.text for b in parsed.doc.blocks if b.role == "heading"]
        self.assertEqual(headings, ["EDUCATION"])
        entry = next(p for p in parsed.proposals if p.target == "entry")
        self.assertEqual(entry.payload["kind"], "education")


class TestDocxAndZip(unittest.TestCase):
    @staticmethod
    def docx_bytes() -> bytes:
        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        body = f"""<?xml version="1.0"?>
<w:document xmlns:w="{W}"><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Experience</w:t></w:r></w:p>
<w:p><w:r><w:t>Field Museum — Collections Assistant, Summer 2022, Chicago, IL</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>Ran the EMu migration.</w:t></w:r></w:p>
</w:body></w:document>"""
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", body)
        return buffer.getvalue()

    def test_docx_uses_word_styles_not_guesses(self):
        data = self.docx_bytes()
        self.assertEqual(detect("cv.docx", data), "docx")
        parsed = parse("cv.docx", data)[0]
        headings = [b for b in parsed.doc.blocks if b.role == "heading"]
        self.assertEqual([h.text for h in headings], ["Experience"])
        self.assertEqual(headings[0].style["word_style"], "Heading1")
        bullets = [p.payload["text"] for p in parsed.proposals
                   if p.target == "bullet"]
        self.assertEqual(bullets, ["Ran the EMu migration."])

    def test_zip_yields_one_source_per_member(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("cv.md", TestMarkdownAndText.MD)
            archive.writestr("notes.txt", "EDUCATION\n\nSomewhere, 2020\n")
            archive.writestr("__MACOSX/._cv.md", "junk")
        data = buffer.getvalue()
        self.assertEqual(detect("bundle.zip", data), "zip")
        names = sorted(s.name.split("!")[1] for s in parse("bundle.zip", data))
        self.assertEqual(names, ["cv.md", "notes.txt"])


class TestHeadings(unittest.TestCase):
    def test_kind_mapping(self):
        self.assertEqual(kind_for("Peer-Reviewed Publications"), "publication")
        self.assertEqual(kind_for("EDUCATION"), "education")
        self.assertEqual(kind_for("Current Projects"), "project")
        self.assertEqual(kind_for("Academic Appointments"), "position")
        self.assertEqual(kind_for(None), "position")


if __name__ == "__main__":
    unittest.main(verbosity=2)
