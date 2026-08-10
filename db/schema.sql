-- ============================================================================
--  cv_db — schema
-- ----------------------------------------------------------------------------
--  SQLite. One file, no server, ships with macOS and Python.
--
--  THE FIRST IDEA: one library, many documents. Everything you have ever done
--  lives once in `entry`, `bullet`, and `skill` — that half of the schema has
--  no idea any document exists. A `document` is a saved arrangement over that
--  library: its own headings, its own selection, its own order. The full CV
--  and a targeted resume are two documents over the same rows, and neither
--  owns the experience.
--
--  So the same teaching assistantship sits under "Teaching" in one document
--  and "Work Experience" in another, with one copy of the bullets. Fix a typo
--  once and every document has it.
--
--  A new document starts EMPTY: no headings, nothing selected. You add the
--  headings you want and pull in the experience that belongs under them.
--
--  THE SECOND IDEA: positions, education, projects, and publications all
--  render from the same handful of fields — a bold title line, an italic
--  date/location line, an optional note line, and bullets. So they are ONE
--  table (`entry`) with a `kind` column, mirroring the `entry()` function in
--  cv-template.typ.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ======================================================== THE LIBRARY ========
--  Your experience. Nothing here refers to a document.

CREATE TABLE profile (
  id          INTEGER PRIMARY KEY,
  full_name   TEXT NOT NULL,          -- the name at the top
  legal_name  TEXT,                   -- shown in the subtitle line, if used
  pronouns    TEXT,
  summary     TEXT                    -- the Profile paragraph
);

-- Email, phone, city, and links. Ordered, so the header line is reproducible.
CREATE TABLE contact (
  id         INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('email','phone','city','link')),
  value      TEXT NOT NULL,           -- the mailto:/https: target, or raw text
  display    TEXT,                    -- what's printed, if different from value
  sort_order INTEGER NOT NULL DEFAULT 0
);

--  DATES: CV dates are prose ("Autumn 2025", "Expected June 2027"), so storing
--  them as DATE loses the wording and gains nothing. Keep BOTH: `date_display`
--  is printed verbatim; `start_ym`/`end_ym` are sortable 'YYYY-MM' keys used
--  only for offering entries in a sensible order.
CREATE TABLE entry (
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL
                 CHECK (kind IN ('position','education','project','publication')),
  org          TEXT,                  -- employer, school, venue, publication
  title        TEXT,                  -- job title, degree, project or piece name
  note         TEXT,                  -- department, advisor, supervisor, stack
  location     TEXT,
  date_display TEXT,                  -- printed verbatim, e.g. "Sept. 2025 – June 2026"
  start_ym     TEXT,                  -- 'YYYY-MM' or 'YYYY', for sorting only
  end_ym       TEXT,                  -- NULL when ongoing
  is_current   INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0,1)),
  url          TEXT,
  summary      TEXT                   -- prose blurb, for entries without bullets
);

CREATE INDEX entry_kind_start ON entry(kind, start_ym DESC);

-- Bullets are a POOL per entry. Reword one for a particular application by
-- adding another row; each document chooses which it prints.
CREATE TABLE bullet (
  id         INTEGER PRIMARY KEY,
  entry_id   INTEGER NOT NULL REFERENCES entry(id) ON DELETE CASCADE,
  text       TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX bullet_entry ON bullet(entry_id, sort_order);

CREATE TABLE skill (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  category   TEXT NOT NULL,           -- the bold label printed by #skill()
  detail     TEXT,                    -- e.g. "A2 Levantine" for a language
  sort_order INTEGER NOT NULL DEFAULT 0
);

-- Which position exercised which skill. Never printed — it is how you find the
-- experience that backs a skill when a posting asks you to evidence one.
CREATE TABLE entry_skill (
  entry_id INTEGER NOT NULL REFERENCES entry(id)  ON DELETE CASCADE,
  skill_id INTEGER NOT NULL REFERENCES skill(id)  ON DELETE CASCADE,
  PRIMARY KEY (entry_id, skill_id)
);

--  Professional references. Printed as a stack of lines under a bold name, in
--  the column order below — title, institution, department, address, email,
--  phone. `address` may hold newlines; each becomes its own printed line.
--
--  `relation` is never printed. It is the reminder of who this person is to
--  you, so a list of eight referees stays legible a year from now.
CREATE TABLE reference (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,           -- "Dr. Helen Robbins"
  title      TEXT,                    -- "Repatriation Director"
  org        TEXT,                    -- "Field Museum of Natural History"
  department TEXT,
  address    TEXT,                    -- one line per newline
  email      TEXT,
  phone      TEXT,
  relation   TEXT,                    -- not printed: how you know them
  sort_order INTEGER NOT NULL DEFAULT 0
);

-- ====================================================== THE DOCUMENTS =======
--  One row per CV or resume you keep. Deleting one removes its arrangement
--  and touches no experience.

CREATE TABLE document (
  id      INTEGER PRIMARY KEY,
  slug    TEXT NOT NULL UNIQUE,       -- 'full-cv', 'ace-usfws'
  title   TEXT NOT NULL,
  density REAL NOT NULL DEFAULT 1.0,  -- 0.8 dense · 1.0 default · 1.15 airy
  paper   TEXT NOT NULL DEFAULT 'us-letter',
  notes   TEXT                        -- what this one is for
);

--  Headings belong to the DOCUMENT. That is what lets one entry sit under
--  "Teaching" in the CV and "Work Experience" in a resume.
--
--  `style` says which cv-template.typ function renders the block:
--    'entries'     → #entry(...)[- bullets], or #item(note: ...) without bullets
--    'itemized'    → #line-item(date: ...)[one line, no bullets]
--    'skills'      → #skill("Category")[comma-separated names]
--    'skill-lines' → #skill-line("English", detail: "native proficiency")
--    'references'  → #reference("Name", lines: (...))
--    'profile'     → bare prose from profile.summary
--
--  'entries' and 'itemized' read the same rows — the difference is only how
--  much of each row prints. Switching a heading between them is how you turn
--  a described section into a listed one without retyping anything.
CREATE TABLE section (
  id          INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  heading     TEXT NOT NULL,
  style       TEXT NOT NULL DEFAULT 'entries'
                CHECK (style IN ('entries','itemized','skills','skill-lines',
                                 'references','profile')),
  -- Skills sections only. NULL prints every skill ticked for the document;
  -- naming a category prints just that one, which is what lets "Languages"
  -- and "Technical Skills" be two headings over the same ticked pool instead
  -- of two copies of it.
  category    TEXT,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  include     INTEGER NOT NULL DEFAULT 1 CHECK (include IN (0,1)),
  UNIQUE (document_id, heading)
);

-- Which experience appears in which document, under which heading, in what
-- order. An entry with no row here simply isn't in that document.
CREATE TABLE doc_entry (
  document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  entry_id    INTEGER NOT NULL REFERENCES entry(id)    ON DELETE CASCADE,
  section_id  INTEGER NOT NULL REFERENCES section(id)  ON DELETE CASCADE,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  include     INTEGER NOT NULL DEFAULT 1 CHECK (include IN (0,1)),
  PRIMARY KEY (document_id, entry_id)
);

CREATE INDEX doc_entry_section ON doc_entry(section_id, sort_order);

-- Bullet suppression, per document. A bullet with NO row here PRINTS — so
-- pulling an entry into a document brings all of its bullets, and rows appear
-- only where you have cut one.
CREATE TABLE doc_bullet (
  document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  bullet_id   INTEGER NOT NULL REFERENCES bullet(id)   ON DELETE CASCADE,
  include     INTEGER NOT NULL DEFAULT 0 CHECK (include IN (0,1)),
  PRIMARY KEY (document_id, bullet_id)
);

-- Which skills a document prints. Unlike bullets this is opt-in: a new
-- document starts with none.
CREATE TABLE doc_skill (
  document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  skill_id    INTEGER NOT NULL REFERENCES skill(id)    ON DELETE CASCADE,
  PRIMARY KEY (document_id, skill_id)
);

-- Which referees a document names. Opt-in, like skills — most applications
-- want a different three.
CREATE TABLE doc_reference (
  document_id  INTEGER NOT NULL REFERENCES document(id)  ON DELETE CASCADE,
  reference_id INTEGER NOT NULL REFERENCES reference(id) ON DELETE CASCADE,
  PRIMARY KEY (document_id, reference_id)
);

-- ======================================================== THE VERSIONS =======
--  What you actually sent, and to whom.
--
--  A version is a DISTINCT STATE of a document, not a press of the button.
--  Generating records the rendered Typst and its sha256; if that digest
--  matches the newest version, you get that version back rather than a second
--  row saying the same thing. So the list stays a list of real changes, and
--  sending the same PDF to four search committees is four `send` rows against
--  one version — which is the question you actually ask later.
--
--  `source` is the whole rendered document, stamped with its own version
--  number — byte-for-byte the file that was written. A few kilobytes of text,
--  and keeping it means an old version can be recompiled exactly, long after
--  the rows it came from have been reworded.
--
--  `digest` hashes the UNSTAMPED render, not `source`. Otherwise the version
--  number would be part of what is being compared and no two versions could
--  ever match.

CREATE TABLE version (
  id          INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  number      INTEGER NOT NULL,        -- 1, 2, 3… within this document
  created_at  TEXT NOT NULL,           -- UTC, 'YYYY-MM-DDTHH:MM:SSZ'
  digest      TEXT NOT NULL,           -- sha256 of `source`
  source      TEXT NOT NULL,           -- the exact Typst this version rendered to
  notes       TEXT,                    -- "trimmed to two pages for the Getty"
  UNIQUE (document_id, number)
);

CREATE INDEX version_document ON version(document_id, number DESC);

-- One row per time this version went somewhere.
CREATE TABLE send (
  id         INTEGER PRIMARY KEY,
  version_id INTEGER NOT NULL REFERENCES version(id) ON DELETE CASCADE,
  recipient  TEXT NOT NULL,            -- person, committee, or posting
  org        TEXT,
  sent_on    TEXT,                     -- 'YYYY-MM-DD'
  channel    TEXT,                     -- email · portal · post · in person
  notes      TEXT
);

CREATE INDEX send_version ON send(version_id, sent_on, id);

-- ====================================================== THE STAGING AREA =====
--  Where an uploaded document lands, and what the parser made of it.
--
--  THE RULE: extraction PROPOSES, a human PROMOTES. Nothing in the library
--  above was ever guessed at, and that is the property the whole document
--  model rests on — so a parser writes here, never there. `extraction.entry_id`
--  is set on acceptance and is the only thread back.
--
--  `char_start`/`char_end` index `source.text`, so every proposal can show the
--  reviewer the exact words it came from. That is not decoration: `unparsed`
--  holds every span NO proposal claimed, and between them the two tables
--  account for every character of the file. A parser obliged to place all of
--  its input can only fail visibly, which is the whole reason to prefer rules
--  here — text quietly ignored is indistinguishable from text that was absent.

CREATE TABLE source (
  id          INTEGER PRIMARY KEY,
  filename    TEXT NOT NULL,
  kind        TEXT NOT NULL,          -- typst · latex · docx · pdf · markdown · html · text
  sha256      TEXT NOT NULL,          -- of the original bytes, not of `text`
  text        TEXT NOT NULL,          -- canonical text; every offset indexes THIS
  coverage    REAL,                   -- fraction of non-whitespace chars claimed
  parser      TEXT NOT NULL,          -- which version of `ingest` read it
  imported_at TEXT NOT NULL,          -- UTC, 'YYYY-MM-DDTHH:MM:SSZ'
  -- The same file read by the same parser is the same answer, so re-importing
  -- is a no-op. Read by a NEWER parser it is a second row — which is what
  -- makes an improved rule diffable against the rows it used to produce.
  UNIQUE (sha256, parser)
);

CREATE TABLE extraction (
  id          INTEGER PRIMARY KEY,
  source_id   INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  target      TEXT NOT NULL
                CHECK (target IN ('entry','bullet','skill','reference',
                                  'profile','contact')),
  payload     TEXT NOT NULL,          -- JSON: column → value, for `target`
  parent_id   INTEGER REFERENCES extraction(id) ON DELETE CASCADE,  -- bullet → entry
  char_start  INTEGER NOT NULL,
  char_end    INTEGER NOT NULL,
  page        INTEGER,                -- PDFs only
  quote       TEXT NOT NULL,          -- the source text, verbatim
  rule        TEXT NOT NULL,          -- which rule produced this, e.g. 'latex.cventry'
  confidence  REAL NOT NULL DEFAULT 1.0,
  status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','accepted','rejected','merged')),
  entry_id    INTEGER REFERENCES entry(id) ON DELETE SET NULL
);

CREATE INDEX extraction_source ON extraction(source_id, char_start, id);
CREATE INDEX extraction_status ON extraction(status, source_id, id);

-- Text the parser read and could not place. Not an error log — a worklist.
CREATE TABLE unparsed (
  id         INTEGER PRIMARY KEY,
  source_id  INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  char_start INTEGER NOT NULL,
  char_end   INTEGER NOT NULL,
  text       TEXT NOT NULL
);

CREATE INDEX unparsed_source ON unparsed(source_id, char_start);

-- ---------------------------------------------------------------- rendering --
--  One document, in print order. Every ORDER BY ends in a unique column, so
--  the generated Typst is byte-identical run to run given the same rows.

CREATE VIEW v_section AS
SELECT s.document_id, d.slug AS document, s.id AS section_id,
       s.heading, s.style, s.sort_order
FROM section s JOIN document d ON d.id = s.document_id
WHERE s.include = 1;

CREATE VIEW v_entry AS
SELECT
  d.id AS document_id, d.slug AS document,
  s.sort_order AS section_order, s.heading, s.id AS section_id,
  de.sort_order AS entry_order, e.id AS entry_id,
  e.kind, e.org, e.title, e.note, e.location, e.date_display, e.url, e.summary
FROM doc_entry de
JOIN document d ON d.id = de.document_id
JOIN section  s ON s.id = de.section_id
JOIN entry    e ON e.id = de.entry_id
WHERE de.include = 1 AND s.include = 1 AND s.style = 'entries';

CREATE VIEW v_bullet AS
SELECT de.document_id, b.entry_id, b.id AS bullet_id, b.text, b.sort_order
FROM doc_entry de
JOIN bullet b ON b.entry_id = de.entry_id
LEFT JOIN doc_bullet db
       ON db.document_id = de.document_id AND db.bullet_id = b.id
WHERE de.include = 1 AND COALESCE(db.include, 1) = 1;

CREATE VIEW v_skill AS
SELECT ds.document_id, s.category, s.name, s.detail, s.sort_order
FROM doc_skill ds JOIN skill s ON s.id = ds.skill_id;

CREATE VIEW v_reference AS
SELECT dr.document_id, r.id AS reference_id, r.name, r.title, r.org,
       r.department, r.address, r.email, r.phone, r.sort_order
FROM doc_reference dr JOIN reference r ON r.id = dr.reference_id;

-- The review queue: what is waiting on a human, worst-first. Low confidence
-- sorts to the top because that is where attention is worth spending — a
-- `latex.cventry` proposal was read off a documented signature and needs a
-- glance; a `segment.entry` one was inferred from a date and needs a decision.
CREATE VIEW v_pending AS
SELECT x.id, s.filename, s.kind AS source_kind, x.target, x.rule,
       x.confidence, x.page, x.quote, x.payload, x.parent_id
FROM extraction x JOIN source s ON s.id = x.source_id
WHERE x.status = 'pending'
ORDER BY x.confidence, s.id, x.char_start, x.id;

-- Where each version went. One row per send; a version with no sends does not
-- appear, which is the point — this is the "what has actually gone out" view.
CREATE VIEW v_sent AS
SELECT d.slug AS document, v.number AS version, v.created_at,
       s.sent_on, s.recipient, s.org, s.channel, s.notes
FROM send s
JOIN version  v ON v.id = s.version_id
JOIN document d ON d.id = v.document_id;
