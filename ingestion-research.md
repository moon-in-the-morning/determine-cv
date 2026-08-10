# Ingestion, without a model

Research memo, 2026-08-10. The question: people should be able to drop in
papers, old CVs and resumes, and job descriptions, and have the rows land in
`db/cv.db` — with no LLM anywhere in the pipeline.

**Short answer: this is more tractable than it sounds, and it fits the project
better than the alternative.** Publications are exactly solved by public APIs
and need no guessing at all. Job postings mostly ship machine-readable metadata
already. The CV itself is the only real parsing problem, and CVs are a
conventional enough genre that rules go a long way — with the crucial property
that when rules fail, they fail *visibly*, which is a guarantee a model can't
offer.

The organizing idea: **`parse()` is the inverse of `render()`.** `cv_typst.render()`
is a pure function from rows to text. The parser is a pure function from text to
proposed rows — no network, no I/O, no dependencies, same input always giving
the same output. That symmetry is the whole design.

---

## 1. The membrane: extraction proposes, a human promotes

The schema's argument is one trusted copy of each fact and `ORDER BY` clauses
that end in a unique column, so the same rows produce a byte-identical file every
run. A parser writing straight into `entry` puts guessed text into the layer the
document model trusts. Even a deterministic parser guesses — determinism means
*the same* guess every time, not the right one.

So, three tables between the file and the library:

```sql
CREATE TABLE source (            -- the file someone dropped in
  id, kind, filename, sha256, text, imported_at
);

CREATE TABLE extraction (        -- one proposed row, not yet real
  id, source_id, target_table,   -- 'entry' | 'bullet' | 'skill' | 'reference'
  payload,                       -- JSON matching the target table's columns
  char_start, char_end,          -- exact span in source.text
  rule,                          -- which rule produced it
  status,                        -- pending | accepted | rejected | merged
  entry_id,                      -- set on accept: what it became
  parser_version
);

CREATE TABLE unparsed (          -- text the parser could not place
  id, source_id, char_start, char_end, section_guess
);
```

`unparsed` is the important one, and the reason to prefer rules here.

### The coverage guarantee

Every character of `source.text` is either inside an `extraction` span or inside
an `unparsed` span. The parser asserts this — it's a straight interval-coverage
check over the input, and it fails the test suite if it doesn't hold.

That gives a claim no model-based extractor can make: **"this CV is 94% accounted
for, and here are the 31 lines that aren't."** A language model has no obligation
to account for every token it read; a line it silently ignored is
indistinguishable from a line that wasn't there. A rule-based parser that is
*required* to place every character can only fail loudly. For a tool whose
premise is that you can trust what's in the database, that's the whole ballgame.

The related property: `parser_version` plus `source.sha256` means a re-parse is
meaningful. Improve a rule, re-run over every stored source, and **diff** — rows
already accepted stay accepted, and the diff shows exactly what the improvement
newly caught. Re-running a prompt gives you gratuitously different output and
nothing to diff against.

---

## 2. Publications: exactly solved, no parsing at all

The longest, most tedious section of an academic CV is also the one that needs no
inference, because publication metadata has authoritative public sources:

| Route | Gives | Cost |
| --- | --- | --- |
| **BibTeX / RIS import** | Whatever Zotero already holds | stdlib; a `.bib` parser is ~80 lines |
| **ORCID public API** (`pub.orcid.org/v3.0/{id}/works`) | The author's entire claimed works list, one call | `urllib` + `json`, no key |
| **DOI → [Crossref](https://api.crossref.org)** | Title, authors, venue, volume/issue/pages, date | No key. Regex the DOI off the PDF's first page. |
| **[OpenAlex](https://api.openalex.org)** | Same, plus filter by `author.orcid` for a whole list | No key |

Order of preference: **ORCID or BibTeX in bulk → DOI lookup per-paper**. Crossref
returns ground truth; nothing is being inferred, so nothing can be wrong in the
way parsing is wrong. Most academics already keep a Zotero library, which makes
the `.bib` path both the smallest thing to build and probably the largest single
win.

Mapping is clean: `entry(kind='publication')`, `org` = venue, `title` = article
title, `date_display` = the year as printed, `url` = the DOI link.

[GROBID](https://github.com/grobidOrg/grobid) exists for PDFs with no DOI — ML,
TEI XML out, 55+ labels, runs as a Docker service. It's a model, just not a
language model, and it's the right call only if DOI-less preprints turn out to
matter. Skip it until they do.

---

## 3. The CV: rules go further than expected

### The format ladder

How hard this is depends entirely on what you're handed, and the difference is
large enough that it should drive the build order:

| Input | Structural signal | Deps |
| --- | --- | --- |
| `.bib`, `.ris`, `resume.json`, ORCID | Already structured | stdlib |
| **`.docx`** | Explicit `Heading 1` / `List Paragraph` styles | **stdlib** — a `.docx` is a zip of XML: `zipfile` + `xml.etree` |
| **`.html`** | Explicit `<h2>`, `<li>`, `<strong>` | **stdlib** — `html.parser` |
| `.pdf` (text layer) | Font size, weight, x/y coordinates, indentation | `pdfplumber` |
| `.txt` | Indentation and blank lines only | stdlib |
| scanned `.pdf` | Nothing without OCR | out of scope |

Two things worth noticing. **DOCX is the best case, not the worst** — old
resumes are overwhelmingly Word files, and Word tells you outright which
paragraphs are headings. It needs no third-party library. And **the existing
workflow already sidesteps PDF**: every file in `reference-cvs/` has a `.txt`
alongside it. If the parser takes text and PDF extraction is a separate,
swappable pre-step, the parser itself stays pure and stdlib-only, and pypdf —
already blessed in the README's ATS-check one-liner — covers the PDF case
without contaminating the core.

### Why CVs are tractable

They're a conventional genre, and `reference-cvs/README.md` already documented
the convention: ordering is `Education → Appointments → Publications → Grants →
Teaching → Talks → Service` with only small permutations. Five independently
written academic CVs agreeing on section order is exactly the regularity a rule
system needs.

**Sections.** Match candidate heading lines against a controlled vocabulary of
~60 canonical names with known variants (`Appointments` / `Academic Appointments`
/ `Professional Experience` / `Employment`). Corroborate with formatting: all
caps, larger font, bold, preceded by a rule or a wide vertical gap, followed by
a differently-shaped line. In DOCX and HTML this is not a heuristic at all — the
heading is tagged.

**Entry boundaries.** The reliable invariant: **every CV entry carries a date.**
So a date-bearing line at entry indentation opens a new entry, and everything
until the next one belongs to it. That single rule does most of the segmentation
work.

**Fields.** Here the schema does the parser an enormous favour. `date_display`
is stored *verbatim* — so the parser only has to **locate** the date, never
understand it. Locating is easy; understanding is where date parsers go to die.
`start_ym`/`end_ym` are derived where the shape is recognizable and left NULL
otherwise, which the schema already permits and the reviewer can fill in.

- **Dates** — ~15 patterns cover the genre: `Sept. 2025 – June 2026`,
  `2019–present`, `Autumn 2025`, `Expected June 2027`, `(2023)`, plus
  hyphen/en-dash/em-dash variants.
- **Location** — `City, ST` / `City, Country` at line end, validated against a
  short state and country list.
- **Bullets vs. prose** — a rule, not a judgment, and the schema already
  anticipates both: lines with a leading marker become `bullet` rows; an
  unmarked paragraph becomes `summary` ("prose blurb, for entries without
  bullets"). That's Owens' paragraph-per-appointment style handled correctly by
  construction rather than by inference.
- **Org vs. title** — the genuinely hard one when there's no separator. Don't
  try to win it; see below.

**Skills.** The reference CVs have no Skills sections, so extraction here means
matching a controlled vocabulary of tools and methods against the full text and
proposing `skill` rows linked via `entry_skill` to whichever entry the mention
fell inside. That's a better use of `entry_skill` than anything currently
populating it — it records *where in the CV the skill was evidenced*, which is
exactly what the schema comment says the table is for.

### Two techniques that do the heavy lifting

**Learn the template from the document itself.** CVs differ wildly from each
other but are rigidly self-consistent internally — one author uses one entry
format throughout. So within a section, count line shapes and take the most
frequent as that document's template, then apply it to the rest. This is pure
frequency counting, fully deterministic, and it adapts per document without any
learned model. It's how a rule system absorbs the variation between CVs instead
of drowning in it.

**Make one correction propagate.** Parse a section, show the reviewer the first
entry, let them fix it — then re-apply that correction as a rule to the rest of
the section. *"You marked the second field as the organization. Apply to the
other 13 entries under Appointments?"* One human judgment becomes fourteen
correct rows.

That mechanism is also the answer to org-vs-title: don't disambiguate, offer a
swap and propagate it. Getting one keystroke from the reviewer is cheaper and
more reliable than any amount of cleverness, and it's a strictly better
interaction than reading a model's confident guess and wondering.

### Effort, honestly

Section vocabulary ~100 lines of data; date patterns ~50; entry segmentation
~150; field assignment ~200; DOCX and HTML readers ~150 each; test harness ~100.
Call it 600–900 lines. A couple of focused weekends, not a quarter.

### Measure it before believing it

`reference-cvs/` is already a nine-document corpus of real academic CVs spanning
PDF, HTML, and text, bulleted and prose, 8–10 pages each — a ready-made golden-file
test suite, and better than most parser projects start with. **Build the harness
first:** hand-write the expected rows for two CVs, run the parser, report
per-field precision and coverage. Then there's a real number instead of my
guess, and every rule change is measured against it.

---

## 4. Job postings: mostly free, and a different feature

Postings don't produce `entry` rows. They're the *selection* input — the thing
you build a targeted document against. Two useful facts:

- **Google for Jobs requires sites to embed [schema.org `JobPosting`](https://schema.org/JobPosting)
  JSON-LD**, so a large share of posting URLs hand over title, org, location,
  qualifications, and dates as structured data with no parsing at all. Pull the
  `<script type="application/ld+json">` block with stdlib `html.parser`.
- **Matching is classical IR, not inference.** Tokenize the posting, match against
  `skill.name` plus a synonym table, and rank entries by BM25 or plain TF-IDF over
  their bullets. ~100 lines, deterministic, explainable — and it can show *which
  bullet* matched *which phrase in the posting*, which is more useful than a
  similarity score.

A `posting` table plus a match view over `entry_skill` is a self-contained
feature that never touches the library.

---

## 5. What buying this costs, and what it buys

**Given up:** normalization and rewording (unwanted anyway — bullets are a pool
you edit by hand); genuinely unconventional CVs, which land in `unparsed` rather
than being handled; org/title disambiguation, traded for a keystroke; and
scanned documents, which need OCR.

**Bought:**

- **Zero dependencies for the core.** `parse()` is stdlib. DOCX and HTML are
  stdlib. Only PDF needs pypdf, and only in a swappable pre-step. The README's
  "standard library only — no venv, no npm, nothing to install" survives intact,
  which is load-bearing for a tool meant to outlive its author's patience.
- **No key, no account, no network, no per-document cost, no vendor.** Nothing
  leaves the machine — which matters given `reference-cvs/` is other people's
  documents and gitignored for that reason.
- **Testable against a corpus you already have**, with golden files and a real
  accuracy number.
- **Failures are legible and fixable once.** Find the rule, fix the rule, and
  every future document benefits. Prompt-tuning doesn't compose like that.
- **Coverage and diffable re-parses** (§1) — the properties that make the
  database trustworthy, which is the point of the whole project.

For reference, the alternative was rejected on shape as much as principle: the
commercial resume-parsing industry (Affinda, Textkernel, RChilli) and the
open-source builders (OpenResume, Reactive Resume) all target the 1–2 page
industry résumé and normalize to [JSON Resume](https://docs.jsonresume.org/schema),
which has no Grants, no Talks, no Service, and a thin `publications` array. A
10-page academic CV gets flattened into a shape you'd then have to un-flatten.
`entry` — one row shape with a `kind` discriminator, a bullet pool, verbatim
dates alongside sort keys, and headings owned by the document — is genuinely
richer than the standard here. Worth supporting `resume.json` as an
import/export adapter at the edges so data isn't locked in, but not as the
internal model.

---

## 6. Build order

1. **BibTeX / RIS import.** Smallest, stdlib, and probably the biggest single win.
2. **ORCID / DOI → Crossref import.** Also stdlib. Together these fill
   Publications with no guessing.
3. **`source` / `extraction` / `unparsed` tables and the review screen.** Build
   the membrane before anything writes through it — and exercise it with the
   importers above, where proposals are known-good, so the review UI is working
   before it has to handle wrong answers.
4. **Test harness over `reference-cvs/`.** Expected rows for two CVs, precision
   and coverage reported. Before writing the parser, so there's a target.
5. **The CV parser**, easiest input format first: DOCX → HTML → text → PDF.
6. **Correction propagation** in the review UI. Highest leverage per line of
   code in the whole plan.
7. **Postings**: JSON-LD scrape, `posting` table, BM25 match view.

## 7. Open questions

- `db/cv.db` is committed to the repo. Ingesting other people's CVs makes that
  a problem to solve first.
- Does `source` keep the original file, or only its text and hash? Keeping it
  makes re-parsing with improved rules possible; not keeping it is the safer
  default. Text plus sha256 is probably the right middle.
- After promotion, does the link back to the source survive? Current sketch:
  `extraction.entry_id` keeps it one-way, enough for provenance without
  constraining later editing.
