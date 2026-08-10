# CV template (Typst)

Single-column, ATS-friendly, Adobe Garamond Pro. Everything left-aligned —
no right-aligned dates, no grids.

## Files

| File | What it's for |
| --- | --- |
| `db/` | The database — your experience. See [db/README](db/README.md). |
| `server.py` | Local web app: enter, edit, tick, generate. |
| `cv_typst.py` | Rows → Typst. The only file that knows Typst syntax. |
| `web/` | The interface: `index.html`, `app.js`, `style.css`. |
| `cv-template.typ` | The styling. Edit only to restyle. |
| `cv.typ` | Hand-written template with `{{placeholders}}`, if you'd rather write one by hand. |
| `cv.generated.typ` | What the Generate button writes. Overwritten every run — don't edit it. |

## How it works

Everything you have ever done lives once in a library of `entry`, `bullet`, and
`skill` rows. A **document** is a saved arrangement over that library: its own
headings, its own selection, its own order.

So one teaching assistantship sits under "Teaching" in your CV and "Work
Experience" in a resume, with a single copy of the bullets. Fix a typo once and
every document has it. Delete a document and not one line of experience goes
with it.

```sh
python3 server.py        # → http://127.0.0.1:8000
```

Standard library only — no venv, no npm, nothing to install. Loopback-bound
and unauthenticated, so keep it local.

### Build

The document you're working on, in print order. The picker top-left switches
between documents; everything you change writes straight to the database.

- **Add headings** — whatever you want them called. They belong to this
  document, so renaming one here changes nothing anywhere else.
- **Move an entry between headings** with the dropdown on its row. That's the
  same library row appearing somewhere else, not a copy.
- **Cut a single bullet** and it stops printing *in this document only*.
- **Click any text to edit it** — headings, dates, bullet wording. It saves
  when you click away; Escape cancels. Edits to a bullet or a date are to the
  library, so every document sees them.
- **Generate** writes `cv.generated.typ`, compiles the PDF if the box is
  ticked, and opens a save dialog so you choose where it lands. A heading with
  nothing under it is skipped, so it never prints as a bare rule.

### Documents

Create, rename, annotate, delete. A new document starts **blank** — no
headings, nothing selected — or you can copy another document's headings and
selection to start from. Deleting one removes only the arrangement.

### Library

Every entry you have, once. Each shows which documents use it, or flags **in no
document** — which is a normal state, not a broken one. Add an entry to the
current document under any heading, and filter to "not in this document" when
building something new.

An entry **with** bullets renders as `#entry`; one **without** renders as
`#item`. That's the whole rule — it needs no setting.

Dates are entered twice on purpose: `date_display` prints verbatim
("Sept. 2025 – June 2026"), while `start_ym`/`end_ym` are `YYYY-MM` sort keys
used only to order the library. They are never printed.

### Skills

The category is the bold label in the Skills section, so reuse an existing one
where you can. Ticking a skill prints it **in the document you're building**;
editing its name changes it everywhere.

## Generating without the browser

`cv_typst.render()` is a pure function of the rows, so it needs no server —
pass a connection and a document id:

```sh
python3 -c "import sqlite3, cv_typst; print(cv_typst.render(sqlite3.connect('db/cv.db'), 1))"
```

Same rows in, byte-identical file out — every `ORDER BY` ends in a unique
column, so nothing is left to SQLite's discretion.

`web/style.css` is deliberately plain and self-contained. Swapping in a UI
framework means replacing that one file — the markup in `index.html` is
semantic and the fetch layer in `app.js` doesn't touch styling.

## Build

```sh
typst compile cv.typ      # one-off build
typst watch cv.typ        # rebuild on save, for live editing
```

Everything marked `{{like this}}` in `cv.typ` is yours to replace. Delete any
field you don't need — omitted lines collapse and the layout closes up.

## The pieces

```typst
#section("Research Experience")

#entry(
  org: "Museum of Natural History",
  role: "Provenance Research Intern",
  dates: "Sept. 2025 – June 2026",
  location: "Chicago, IL",
  note: "Anthropology Department; supervisor: Dr. A. Reyes",
)[
  - First bullet.
  - Second bullet.
]

#skill("Technical")[EMu collections management, Crystal Reports, Python]

#item(note: "Qur'anic Ethics Seminar, December 2025")[Title of the talk.]
```

`entry` stacks four left-aligned lines and drops any you leave out:

```
Museum of Natural History — Provenance Research Intern         <- bold
Sept. 2025 – June 2026 · Chicago, IL                           <- italic
Anthropology Department; supervisor: ...                       <- italic
• bullets
```

## Fitting the page

Open `cv-template.typ` and change one number:

```typst
#let density = 1.0   // 0.8 dense · 0.9 snug · 1.0 default · 1.15 airy
```

It scales every gap and the line spacing together, so the page tightens
without any one element looking squeezed.

Other knobs at the top of the same file: `cv-font`, `base-size`, `name-size`,
`use-kerning`, `ink`/`ink-soft`, `rule-weight`, and `meta-sep` (the `·`
between date and location). Paper size, margins, and `header-align` are
arguments to `cv()` in `cv.typ`.

## Why it parses cleanly

Applicant tracking systems read a PDF as a flat text stream. This template
keeps that stream identical to what you see:

- **One column, no sidebars or text boxes.** Multi-column layouts interleave
  unrelated lines in the extracted text.
- **No grids and nothing right-aligned.** Dates and locations sit on their own
  left-aligned line, so there is no column order for a parser to get wrong.
- **Conventional headings** (EXPERIENCE, EDUCATION, SKILLS). Parsers match
  these against a known list; clever names fall through.
- **Skills as running text**, not chips or a grid, so every term is picked up.
- **No icons, images, or text-as-graphic.** Nothing meaningful is unselectable.
- **Hyphenation off**, so keywords are never split across lines.
- **Kerning off** (`use-kerning: false`). Garamond emits pairs like `Tr` and
  `Te` as separate text runs, which made extractors read `Tribal` as
  `T ribal` and `Technical` as `T echnical` — a silently missed keyword.
  Verified against one extractor (pypdf); the fix costs a little tightness in
  those pairs and is worth it. Flip the knob if you disagree.

To check any edit yourself, extract the text back out and read it:

```sh
python3 -c "from pypdf import PdfReader; print(PdfReader('cv.pdf').pages[0].extract_text())"
```

If that output reads correctly top to bottom, a parser will see the same thing.

## Two notes on section order

- Sections are laid out experience → education → skills → publications. The
  blocks in `cv.typ` are self-contained, so reordering them is a cut and paste.
- Dates get their own line rather than being run into the entry title, which
  is what keeps them from colliding when a title runs long.
