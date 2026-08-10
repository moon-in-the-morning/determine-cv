# cv_db

SQLite. One file, no server, ships with macOS and Python — and your data is
genuinely relational, so a document store would just make you hand-maintain
the joins.

You do not normally build this by hand — `python3 server.py` creates `cv.db` on
first run, from `schema.sql` plus one of the seeds:

| Seed | What you get |
| --- | --- |
| `starter.sql` | *(default)* A blank CV: one document, conventional headings, nothing in them. |
| `seed.sql` | The worked example — a real CV, filled in. `--seed example`. |
| none | Tables and nothing else. `--seed none`. |

By hand, if you want to:

```sh
sqlite3 cv.db < schema.sql
sqlite3 cv.db < starter.sql
```

**`cv.db` is not tracked by git, and `seed.sql` is.** That is the whole
arrangement: the repo carries the recipe and the example, your working database
stays yours. It is also what keeps the `send` table — the record of which cut of
the CV went to whom — out of the repository, since `dump_seed.py` never writes
those rows. See the note at the top of that script.

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
| `reference` | Professional referees. `relation` is your note to yourself and never prints. |

**The documents** — arrangements over that library.

| Table | Holds |
| --- | --- |
| `document` | One row per CV or resume you keep, with its `density` and `paper`. |
| `section` | The headings, **owned by the document**. `style` says how the block renders. |
| `doc_entry` | Which entry sits under which heading, in what order. No row = not in that document. |
| `doc_bullet` | Bullets a document has cut. **No row means the bullet prints.** |
| `doc_skill` | Which skills a document prints. Opt-in: a new document has none. |
| `doc_reference` | Which referees a document names. Opt-in, like skills. |

Note the two defaults pull in opposite directions, and both are deliberate.
Pulling an entry into a document should bring all its bullets, so `doc_bullet`
only records cuts. Skills are a deliberate selection every time, so `doc_skill`
records inclusions.

**The record** — what you generated and where it went.

| Table | Holds |
| --- | --- |
| `version` | One row per distinct state of a document, with its `digest`, its `created_at`, and the whole Typst `source`. |
| `send` | One row per time a version went to someone: recipient, org, date, channel. |

## Five decisions worth knowing

**Dates are stored twice.** CV dates are prose — "Autumn 2025", "Expected June
2027", "2018 – 2019". Storing them as `DATE` loses the wording and gains
nothing. So `date_display` prints verbatim, and `start_ym`/`end_ym` are
sortable `YYYY-MM` keys used *only* for offering the library in a sensible
order. They are never printed.

**`section.style` decides which template function runs.** It's what makes
generation mechanical instead of a judgment call:

| `style` | Renders as | Reads from |
| --- | --- | --- |
| `entries` | `#entry(...)[- bullets]`, or `#item(note: ...)[...]` with no bullets | `doc_entry` |
| `itemized` | `#line-item(date: ...)[one line]` | `doc_entry` |
| `skills` | `#skill("Category")[comma-separated names]` | `doc_skill` |
| `skill-lines` | `#skill-line(detail: [native])[English]`, one per line | `doc_skill` |
| `references` | `#reference([Name], lines: (...))` | `doc_reference` |
| `profile` | bare prose from `profile.summary` | `profile` |

`entries` and `itemized` read the *same rows*. Switching a heading between them
turns a described section into a listed one without retyping anything: the note
and the bullets sit untouched in the library while `itemized` prints only the
date, title, organisation, and location. It shows less; it does not store less.

Both skills styles read the same ticked pool, so `section.category` can take one
slice of it — which is what lets "Languages" and "Technical Skills" be two
headings over one selection instead of two copies of it. `category IS NULL`
prints everything ticked.

**Bullets are a pool.** To reword one for a particular application, add another
row — each document chooses which it prints. Nothing overwrites your original
phrasing, and the alternative stays one click away.

**An entry in no document is normal, not broken.** It's in the library, ready
to be pulled into whatever you write next.

**A version is a state, not a click.** Generating renders the document, hashes
it, and compares that digest to the newest version. Unchanged gives you back the
version it already is; changed opens a new one. So the list stays a list of real
changes, and sending one PDF to four search committees is four `send` rows
against the single version they actually shared — which is the question you ask
a year later.

The digest covers the *unstamped* render. The version number is written into the
file afterwards, so it can't be part of what decides whether the file changed.

## Querying it

Six views do the assembly, each scoped to a document and ordered so the output
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

-- Everything that has gone out, newest first
SELECT sent_on, recipient, org, document, version FROM v_sent
 ORDER BY sent_on DESC;

-- Which version does this person have? — the one to reread before an interview
SELECT v.number, v.created_at FROM send s JOIN version v ON v.id = s.version_id
 WHERE s.recipient LIKE '%Robbins%';

-- Generated but never sent anywhere
SELECT number, created_at FROM version
 WHERE id NOT IN (SELECT version_id FROM send);
```

## Scripts

| Script | What it does |
| --- | --- |
| `starter.sql` | The blank CV a first run loads. Not a script — a seed. |
| `dump_seed.py` | Writes `seed.sql` from `cv.db`. Deterministic, so the diff shows only what you edited. Holds back `version` and `send`. |
| `migrate_to_single_document.py` | One-off: multi-variant → single document with include flags. |
| `migrate_to_documents.py` | One-off: that → this library-and-documents schema. |
| `migrate_add_references_and_versions.py` | One-off: adds references, versions, sends, and the three new section styles. |

All three migrations have already run. They're kept as the record of what
happened to the data, and each leaves a `cv.db.pre-*` backup beside the
database.

## Seeding it from existing documents

If you transcribe an existing CV out of a PDF, **proofread before generating
anything from it.** Extracted text garbles ligatures, dashes, and diacritics,
so check names and titles against the originals.
