# cv_db

SQLite. One file, no server, ships with macOS and Python — and your data is
genuinely relational, so a document store would just make you hand-maintain
the joins.

```sh
sqlite3 cv.db < schema.sql
```

`cv.db` is not in the repo — it holds your CV, so it stays local. Create it
from `schema.sql` and fill it through the entry form (`python3 server.py`).

## The two ideas the schema is built on

**A CV is a query, not a document.** Your experience lives in the tables once.
A `variant` is a saved selection and ordering of it. A full CV and a one-page resume are two variants over the same rows —
which is already how you work, you just do it by hand right now.

**Positions, education, projects, and publications are one table.** They all
render the same way: bold title line, italic date/location line, optional note
line, bullets. So they're `entry` rows distinguished by `kind`, mirroring the
`entry()` function in `cv-template.typ`. Real foreign keys everywhere, and one
query renders a document.

## Tables

| Table | Holds |
| --- | --- |
| `profile`, `contact` | Your name, legal name, pronouns, email/phone/city. |
| `entry` | Every line-item. `kind` = position / education / project / publication. |
| `bullet` | A **pool** of bullets per entry, not a fixed list. |
| `skill`, `entry_skill` | Skills, and which experience evidences them. |
| `variant` | One row per document you actually produce. |
| `section` | Headings — owned by the variant, not the data. |
| `variant_entry` | Which entries appear where, under which heading, in what order. |
| `variant_bullet` | Which bullets a variant uses, when it differs. |
| `variant_skill` | Which skills a document shows. |

## Three decisions worth knowing

**Dates are stored twice.** CV dates are prose — "Autumn 2025", "Expected June
2027", "2018 – 2019". Storing them as `DATE` loses the wording and gains
nothing. So `date_display` prints verbatim, and `start_ym`/`end_ym` are
sortable `YYYY-MM` keys used *only* for reverse-chronological ordering.

**Headings belong to the variant.** That's what lets one employer sit under
"Research Experience" in the CV and "Work Experience" in the resume, without
duplicating the entry.

**Bullets are a pool.** A resume usually doesn't subset the CV's bullets, it
rewrites them — the same work described for a different reader. So both
wordings are rows against the same entry, and `variant_bullet` picks. The
original is never overwritten.

> Fallback rule: if a variant has **no** `variant_bullet` rows for an entry,
> that entry renders **all** its bullets in natural order. Add rows only when a
> document needs a subset or a reorder. Keeps the seed short.

## Querying it

Two views do the assembly. `v_entry` gives a document in order; `v_bullet`
applies the fallback rule above.

```sql
-- One variant, in render order
SELECT heading, org, title, date_display
FROM v_entry WHERE variant = 'short-resume'
ORDER BY section_order, entry_order;

-- Skills to experience, in both directions
SELECT e.org, e.date_display FROM entry_skill es
  JOIN entry e ON e.id = es.entry_id
  JOIN skill s ON s.id = es.skill_id
 WHERE s.name = 'Python' ORDER BY e.start_ym DESC;

SELECT s.category, s.name FROM entry_skill es
  JOIN skill s ON s.id = es.skill_id
 WHERE es.entry_id = 1 ORDER BY s.category, s.sort_order;

-- Gap check: experience with no skills attached yet
SELECT id, org, title FROM entry
 WHERE kind = 'position'
   AND id NOT IN (SELECT entry_id FROM entry_skill);
```

## Seeding it from existing documents

If you transcribe an existing CV out of a PDF, **proofread before generating
anything from it.** Extracted text garbles ligatures, dashes, and diacritics,
so check names and titles against the originals.

Not yet wired to `cv.typ` — the generator that turns a variant into Typst is
the next step.
