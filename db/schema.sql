-- ============================================================================
--  cv_db — schema
-- ----------------------------------------------------------------------------
--  SQLite. One file, no server, ships with macOS and Python.
--
--  THE CENTRAL IDEA: a CV is not a document, it's a *query*. The tables below
--  hold your experience once; a `variant` is a saved selection and ordering of
--  that experience under a set of headings. The full CV and a targeted resume
--  are two variants over the same rows.
--
--  THE SECOND IDEA: positions, education, projects, and publications all
--  render identically — a bold title line, an italic date/location line, an
--  optional note line, and bullets. So they are ONE table (`entry`) with a
--  `kind` column, mirroring the `entry()` function in cv-template.typ. That
--  keeps real foreign keys everywhere and lets one query render a document.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------------- person --
-- Effectively a singleton, but keyed so a variant can point at it.

CREATE TABLE profile (
  id          INTEGER PRIMARY KEY,
  full_name   TEXT NOT NULL,          -- the name at the top: "Ada Lovelace"
  legal_name  TEXT,                   -- shown in the subtitle line, if used
  pronouns    TEXT,
  summary     TEXT                    -- the Profile paragraph
);

-- Email, phone, city, and links. Ordered, so the header line is reproducible.
CREATE TABLE contact (
  id         INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('email','phone','city','link')),
  value      TEXT NOT NULL,           -- the mailto:/https:/ target, or raw text
  display    TEXT,                    -- what's printed, if different from value
  sort_order INTEGER NOT NULL DEFAULT 0
);

-- ------------------------------------------------------------------ entries --
--  Every resume line-item, regardless of type.
--
--  DATES: CV dates are prose ("Autumn 2025", "Expected June 2027", "2018 –
--  2019"), so storing them as DATE loses the wording and gains nothing. Keep
--  BOTH: `date_display` is printed verbatim; `start_ym`/`end_ym` are sortable
--  'YYYY-MM' keys used only for reverse-chronological ordering.

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

-- Bullets are a POOL per entry, not a fixed list. A variant picks from the
-- pool (see variant_bullet), so a reworded bullet for a targeted resume is
-- just another row here — the original stays untouched.
CREATE TABLE bullet (
  id         INTEGER PRIMARY KEY,
  entry_id   INTEGER NOT NULL REFERENCES entry(id) ON DELETE CASCADE,
  text       TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX bullet_entry ON bullet(entry_id, sort_order);

-- ------------------------------------------------------------------- skills --

CREATE TABLE skill (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  category   TEXT NOT NULL,           -- the bold label in the Skills section
  detail     TEXT,                    -- e.g. "A2 Levantine" for a language
  sort_order INTEGER NOT NULL DEFAULT 0
);

-- The many-to-many you asked about. Because positions, projects, and
-- publications are all `entry` rows, ONE join table covers every correlation:
-- which skills a position exercised, which a project used.
CREATE TABLE entry_skill (
  entry_id INTEGER NOT NULL REFERENCES entry(id)  ON DELETE CASCADE,
  skill_id INTEGER NOT NULL REFERENCES skill(id)  ON DELETE CASCADE,
  PRIMARY KEY (entry_id, skill_id)
);

-- ------------------------------------------------------------------ variants --
--  One row per document you actually produce.

CREATE TABLE variant (
  id         INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  slug       TEXT NOT NULL UNIQUE,    -- 'full-cv', 'short-resume'
  title      TEXT NOT NULL,
  density    REAL NOT NULL DEFAULT 1.0,  -- feeds cv-template.typ
  paper      TEXT NOT NULL DEFAULT 'us-letter',
  notes      TEXT
);

-- Headings belong to the VARIANT, not the data — that's what lets the Field
-- Museum sit under "Research Experience" in one document and "Work
-- Experience" in another.
CREATE TABLE section (
  id         INTEGER PRIMARY KEY,
  variant_id INTEGER NOT NULL REFERENCES variant(id) ON DELETE CASCADE,
  heading    TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (variant_id, heading)
);

-- Which entries appear in which document, under which heading, in what order.
CREATE TABLE variant_entry (
  variant_id INTEGER NOT NULL REFERENCES variant(id) ON DELETE CASCADE,
  entry_id   INTEGER NOT NULL REFERENCES entry(id)   ON DELETE CASCADE,
  section_id INTEGER NOT NULL REFERENCES section(id) ON DELETE CASCADE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (variant_id, entry_id)
);

-- OPTIONAL per-variant bullet selection.
-- Rule: if a variant has NO rows here for a given entry, that entry renders
-- ALL of its bullets in their natural order. Add rows only when a document
-- needs a subset or a different order. Keeps seeds short.
CREATE TABLE variant_bullet (
  variant_id INTEGER NOT NULL REFERENCES variant(id) ON DELETE CASCADE,
  bullet_id  INTEGER NOT NULL REFERENCES bullet(id)  ON DELETE CASCADE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (variant_id, bullet_id)
);

-- Which skills a variant shows. A federal-facing resume may want a "Data
-- practice" category where the full CV wants "Organizational".
CREATE TABLE variant_skill (
  variant_id INTEGER NOT NULL REFERENCES variant(id) ON DELETE CASCADE,
  skill_id   INTEGER NOT NULL REFERENCES skill(id)   ON DELETE CASCADE,
  PRIMARY KEY (variant_id, skill_id)
);

-- ----------------------------------------------------------------- rendering --
--  One view per document shape. Ordering is fully determined here, so the
--  generated Typst is byte-identical run to run given the same rows.

CREATE VIEW v_entry AS
SELECT
  v.slug           AS variant,
  s.sort_order     AS section_order,
  s.heading        AS heading,
  ve.sort_order    AS entry_order,
  e.id             AS entry_id,
  e.kind, e.org, e.title, e.note, e.location,
  e.date_display, e.url, e.summary
FROM variant_entry ve
JOIN variant v ON v.id = ve.variant_id
JOIN section s ON s.id = ve.section_id
JOIN entry   e ON e.id = ve.entry_id;

-- Applies the "no rows means all bullets" fallback described above.
CREATE VIEW v_bullet AS
SELECT
  v.slug AS variant,
  b.entry_id,
  b.id   AS bullet_id,
  b.text,
  COALESCE(vb.sort_order, b.sort_order) AS sort_order
FROM bullet b
JOIN entry e   ON e.id = b.entry_id
JOIN variant v ON 1 = 1
LEFT JOIN variant_bullet vb
       ON vb.bullet_id = b.id AND vb.variant_id = v.id
WHERE vb.bullet_id IS NOT NULL
   OR NOT EXISTS (
        SELECT 1 FROM variant_bullet x
        JOIN bullet b2 ON b2.id = x.bullet_id
        WHERE x.variant_id = v.id AND b2.entry_id = b.entry_id
      );
