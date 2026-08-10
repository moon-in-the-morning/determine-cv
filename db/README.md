# cv_db

SQLite. One file, no server, ships with macOS and Python — and your data is
genuinely relational, so a document store would just make you hand-maintain
the joins.

```sh
sqlite3 cv.db < schema.sql
sqlite3 cv.db < seed.sql   # optional — rebuilds the rows from a dump
```

To start empty, load `schema.sql` alone and fill it through the form
(`python3 server.py`).

## The two ideas the schema is built on

**One library, many documents.** Everything you have ever done lives once in
`entry`, `bullet`, and `skill`. That half of the schema has no idea any
document exists. A `document` is a saved arrangement over the library: its own
headings, its own selection, its own order.

So the same teaching assistantship sits under "Teaching" in your CV and "Work
Experience" in a resume, with one copy of the bullets. Fix a typo once and
every document has it. Delete a document and not one line of experience goes
with it.

A new document starts **empty** — no headings, nothing selected. You add the
headings you want and pull in the experience that belongs under them.

**Positions, education, projects, and publications are one table.** They all
render the same way: bold title line, italic date/location line, optional note
line, bullets. So they're `entry` rows distinguished by `kind`, mirroring the
`entry()` function in `cv-template.typ`.

## Tables

**The library** — no column here refers to a document.

| Table | Holds |
| --- | --- |
| `profile`, `contact` | Name, legal name, pronouns, the Profile paragraph, email/phone/city. |
| `entry` | Every line-item. `kind` = position / education / project / publication. |
| `bullet` | A **pool** of bullets per entry, not a fixed list. |
| `skill`, `entry_skill` | Skills, and which experience evidences them. |

**The documents** — arrangements over that library.

| Table | Holds |
| --- | --- |
| `document` | One row per CV or resume you keep, with its `density` and `paper`. |
| `section` | The headings, **owned by the document**. `style` says how the block renders. |
| `doc_entry` | Which entry sits under which heading, in what order. No row = not in that document. |
| `doc_bullet` | Bullets a document has cut. **No row means the bullet prints.** |
| `doc_skill` | Which skills a document prints. Opt-in: a new document has none. |

Note the two defaults pull in opposite directions, and both are deliberate.
Pulling an entry into a document should bring all its bullets, so `doc_bullet`
only records cuts. Skills are a deliberate selection every time, so `doc_skill`
records inclusions.

## Four decisions worth knowing

**Dates are stored twice.** CV dates are prose — "Autumn 2025", "Expected June
2027", "2018 – 2019". Storing them as `DATE` loses the wording and gains
nothing. So `date_display` prints verbatim, and `start_ym`/`end_ym` are
sortable `YYYY-MM` keys used *only* for offering the library in a sensible
order. They are never printed.

**`section.style` decides which template function runs.** It's what makes
generation mechanical instead of a judgment call:

| `style` | Renders as |
| --- | --- |
| `entries` | `#entry(...)[- bullets]`, or `#item(note: ...)[...]` when an entry has no bullets |
| `skills` | `#skill("Category")[comma-separated names]` |
| `profile` | bare prose from `profile.summary` |

**Bullets are a pool.** To reword one for a particular application, add another
row — each document chooses which it prints. Nothing overwrites your original
phrasing, and the alternative stays one click away.

**An entry in no document is normal, not broken.** It's in the library, ready
to be pulled into whatever you write next.

## Querying it

Four views do the assembly, each scoped to a document and ordered so the output
is byte-identical run to run.

```sql
-- One document, in render order
SELECT heading, org, title, date_display FROM v_entry
WHERE document = 'full-cv' ORDER BY section_order, entry_order;

-- Where does one entry appear, and under what heading each time?
SELECT d.title, s.heading FROM doc_entry de
  JOIN document d ON d.id = de.document_id
  JOIN section  s ON s.id = de.section_id
 WHERE de.entry_id = 5;

-- Skills to experience, in both directions
SELECT e.org, e.date_display FROM entry_skill es
  JOIN entry e ON e.id = es.entry_id
  JOIN skill s ON s.id = es.skill_id
 WHERE s.name = 'Python' ORDER BY e.start_ym DESC;

-- In the library but in no document yet
SELECT id, org, title FROM entry
 WHERE id NOT IN (SELECT entry_id FROM doc_entry);

-- Gap check: experience with no skills attached
SELECT id, org, title FROM entry
 WHERE kind = 'position' AND id NOT IN (SELECT entry_id FROM entry_skill);
```

## Scripts

| Script | What it does |
| --- | --- |
| `dump_seed.py` | Writes `seed.sql` from `cv.db`. Deterministic, so the diff shows only what you edited. |
| `migrate_to_single_document.py` | One-off: multi-variant → single document with include flags. |
| `migrate_to_documents.py` | One-off: that → this library-and-documents schema. |

Both migrations have already run. They're kept as the record of what happened
to the data, and each leaves a `cv.db.pre-*` backup beside the database.

## Seeding it from existing documents

If you transcribe an existing CV out of a PDF, **proofread before generating
anything from it.** Extracted text garbles ligatures, dashes, and diacritics,
so check names and titles against the originals.
