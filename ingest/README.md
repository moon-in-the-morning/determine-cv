# ingest — documents in, proposed rows out

No model, no network, no key, no cost. `parse()` is a pure function of its
bytes, the same way `cv_typst.render()` is a pure function of its rows. The two
are inverses, and the Typst reader exists partly to prove it.

```sh
python3 -m ingest cv.tex
python3 -m ingest reference-cvs/posner-miriam-ucla-dh.txt --gaps
python3 -m ingest applications.zip --json
python3 -m unittest discover -s ingest -t .
```

## Nothing here writes to the library

Extraction **proposes**; a human **promotes**. Parsed rows land in `source`,
`extraction`, and `unparsed` (see `db/schema.sql`), and only `store.accept()`
moves one into `entry`/`bullet`/`skill`/`reference`. That line is the point:
everything in the library was put there on purpose, which is what the document
model rests on.

```sh
python3 db/migrate_add_ingestion.py      # adds the three tables. Additive; no rebuild.
```

## Coverage, and what it does and doesn't prove

Every character of `source.text` is either inside an `extraction` span or
inside an `unparsed` span, and the parser asserts it. So the review screen can
say *"94% of this CV is accounted for, and here are the 31 lines that aren't."*
A parser obliged to place all of its input can only fail visibly.

**Coverage measures placement, not correctness** — and the corpus makes the
distinction concrete. Posner's CV reads at 100% coverage and yields ten entries
for a ten-page document: perfect accounting, wrong answer. The number tells you
nothing escaped notice. It does not tell you the boundaries were right. Both
need measuring, and only the first one is measured today.

## The format ladder

Higher is better. Where two versions of a document exist, ingest the higher one.

| Format | Signal | Deps | State |
| --- | --- | --- | --- |
| `.typ` | Our own output — every field in its own named argument | stdlib | **exact**, round-trip tested |
| `.tex` | `\section`, class signatures, `\newcommand` arity | stdlib | good |
| `.docx` | Word's own `Heading 1` / list styles | **stdlib** (`zipfile` + `xml.etree`) | good |
| `.html` | `<h2>`, `<li>` — nothing inferred | stdlib | good |
| `.md` | `##`, `-` | stdlib | good |
| `.zip` | a bundle — each member routed back through the top | stdlib | good |
| `.txt` | indentation, blank lines, line shape | stdlib | **weak on long CVs** |
| `.pdf` | a text layer and a guess | `pypdf` | **weak**; prefer a `.txt` sidecar |
| scanned `.pdf` | nothing without OCR | — | out of scope |

`.docx` being stdlib is the useful surprise: a Word file is a zip of XML that
says outright which paragraph is a heading, and most people's old resumes are
Word files. PDF is the only reader with a dependency, and it fails with an
instruction rather than a traceback.

## What LaTeX gets right that PDF cannot

A `\newcommand{\job}[4]{...}` is a **template declaration**. The author has
already said their entries have four fields and already marked where each one
starts and stops, identically, every time they used it. We do not need to know
what the four mean: we take the arity, sniff what identifies itself (a date
looks like a date, `Chicago, IL` looks like a place), and ask once. The answer
applies to every use. That is correction-propagation arriving for free,
declared in the source rather than inferred from it.

## What it refuses to guess

Splitting an organisation from a title with no separator between them is a coin
flip dressed as a result. The whole line goes into `title` with
`confidence 0.5`, and the review screen offers the split for the reviewer to
confirm once per section. Same for `#line-item` bodies, which the renderer
welded together on the way out and no reader can unweld.

`find_location` validates against state and country lists rather than matching
`Word, Word` — otherwise "Chicago, Director of Research" reads as a place,
which costs a reviewer more time than an empty field would.

## Why the schema makes this easy

`date_display` prints verbatim and `start_ym`/`end_ym` exist only to sort. So
the parser has to **locate** a date, never **understand** one. Locating is easy;
understanding is where date parsers die. Where the shape is recognisable we
derive the sort keys, and where it isn't we leave them NULL — which the schema
already allows.

## Files

| File | What it's for |
| --- | --- |
| `__init__.py` | `parse()`, `propose()` — the orchestration and the public API |
| `ir.py` | `Block`, `Doc`, `Proposal`, and `coverage()` |
| `detect.py` | Which reader gets the file, by suffix and magic bytes |
| `segment.py` | Dates, locations, headings, and the generic segmenter |
| `typst.py` `latex.py` `office.py` `html.py` `text.py` `pdf.py` | The readers |
| `store.py` | Proposals → staging tables; `accept()` → the library |
| `__main__.py` | The CLI above |
| `test_ingest.py` | 33 tests, `TestRoundTrip` first |

## Known weak spots

- **The generic segmenter on PDF-derived text.** A CV extracted from a PDF may
  arrive with no line structure at all, and one-entry-per-page is what that
  looks like. Measured, not guessed: see the table in `ingest-research.md`.
- **Per-field precision is unmeasured.** Coverage is. The next step is
  hand-written expected rows for two CVs and a precision number per field —
  step 4 of the build order, and not to be skipped just because coverage
  already reads well.
- **Not built yet:** BibTeX/RIS and JSON Resume import, both of which are
  exact rather than inferred and both of which should exist before more effort
  goes into guessing at prose.
