-- ============================================================================
--  cv_db — seed data
--  Transcribed from 2026_Moon_Younes_CV.pdf and Moon_Younes_Resume_ACE_USFWS.pdf.
--  PROOFREAD: text pulled from a PDF garbles ligatures, dashes, and diacritics.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------------ profile --

INSERT INTO profile (id, full_name, legal_name, pronouns, summary) VALUES
(1, 'Moon Younes', 'Savannah Moon Goldstein', 'All pronouns',
 'Researcher and organizer with eight years of leadership across non-profit administration, transnational advocacy, public health, and cultural heritage policy. Currently a Master of Divinity candidate at the University of Chicago.');

INSERT INTO contact (profile_id, kind, value, display, sort_order) VALUES
(1, 'email', 'mailto:moony@uchicago.edu', 'moony@uchicago.edu', 1),
(1, 'phone', '(404) 444-5996',            NULL,                 2),
(1, 'city',  'Chicago, IL',               NULL,                 3);

-- ------------------------------------------------------------- positions ----
--  start_ym / end_ym are for SORTING ONLY. date_display is what prints.

INSERT INTO entry (id, kind, org, title, note, location, date_display, start_ym, end_ym, is_current) VALUES
(1, 'position', 'Field Museum of Natural History', 'Provenance Research Intern',
   'Repatriation and Anthropology Department; supervisor: Dr. Helen Robbins',
   'Chicago, IL', 'Sept. 2025 – June 2026', '2025-09', '2026-06', 0),

(2, 'position', 'University of Chicago Divinity School', 'Research Assistant, Scholasticide Project',
   'Advisor: Prof. Alireza Doostdar',
   'Chicago, IL', 'Sept. 2024 – Present', '2024-09', NULL, 1),

(3, 'position', 'Marty Center for the Public Understanding of Religion', 'Public Religion Fellow',
   'Advisor: Prof. Emily Crews',
   'Chicago, IL', 'July – Sept. 2025', '2025-07', '2025-09', 0),

(4, 'position', 'University of Illinois at Chicago', 'Research Assistant',
   'Advisor: Prof. Brenda Parker, Human Geography and Urban Planning',
   'Chicago, IL', 'Aug. 2020 – May 2022', '2020-08', '2022-05', 0),

(5, 'position', 'University of Chicago', 'Teaching Assistant, ARTH 10100: Introduction to Art',
   'Prof. Niall Atkinson, Department of Art History',
   'Chicago, IL', 'Autumn 2025', '2025-09', '2025-12', 0),

(6, 'position', 'Believers Bail Out', 'Field Placement Volunteer',
   NULL, 'Chicago, IL', 'Sept. 2025 – Present', '2025-09', NULL, 1),

(7, 'position', 'Palestinian Assembly for Liberation', 'National Chapter Coordinator and Communications Lead',
   NULL, NULL, '2023 – 2025', '2023-01', '2025-01', 0),

(8, 'position', 'Jisoor Collective', 'Co-Founder and Organizer',
   NULL, 'Chicago South Suburbs, IL', 'May 2022 – Present', '2022-05', NULL, 1),

(9, 'position', 'Al Nahda Center', 'Grant Writer and Volunteer Organizer',
   NULL, NULL, '2022 – 2024', '2022-01', '2024-01', 0),

(10, 'position', 'Young Invincibles', 'Midwest Campus Outreach Fellow',
   NULL, NULL, 'Sept. 2018 – June 2019', '2018-09', '2019-06', 0),

(11, 'position', 'Love and Belonging', 'Founder and Educator',
   NULL, 'Atlanta, GA', '2017 – 2019', '2017-01', '2019-01', 0),

(12, 'position', 'Roosevelt Network, UIC Chapter', 'Board Member',
   NULL, NULL, '2018 – 2019', '2018-01', '2019-01', 0),

(13, 'position', 'UIC Graduate Employees Organization (GEO Local 6297) and UIC United Faculty', 'Volunteer Organizer',
   NULL, NULL, '2018 – 2019', '2018-01', '2019-01', 0),

(14, 'position', 'Urban Prairie Waldorf School', 'Kindergarten Assistant',
   NULL, 'Chicago, IL', 'Nov. 2022', '2022-11', '2022-11', 0),

(15, 'position', 'Georgia Department of Public Health', 'Intern to Director Michelle Allen',
   NULL, 'Atlanta, GA', 'Feb. – March 2018', '2018-02', '2018-03', 0),

-- These two appear only on the ACE/USFWS resume.
(16, 'position', 'Institute for the Study of Ancient Cultures, University of Chicago',
   'Proofreader, The Assyrian Dictionary of the Oriental Institute (CAD)',
   NULL, 'Chicago, IL', 'July 2026 – Present', '2026-07', NULL, 1),

(17, 'position', 'Nixie Solutions LLC', 'Data Architecture and Engineering Intern',
   NULL, NULL, 'June 2026 – Present', '2026-06', NULL, 1);

-- ------------------------------------------------------------- education ----

INSERT INTO entry (id, kind, org, title, note, location, date_display, start_ym, end_ym, is_current) VALUES
(30, 'education', 'University of Chicago', 'Master of Divinity',
   'Concentrations in psychological anthropology and museum ethics',
   'Chicago, IL', 'Expected June 2027', '2024-09', '2027-06', 1),

(31, 'education', 'University of Illinois at Chicago', 'B.A. Public Policy, Minor in Anthropology',
   NULL, 'Chicago, IL', 'May 2022', '2018-09', '2022-05', 0);

-- -------------------------------------------------------------- projects ----

INSERT INTO entry (id, kind, org, title, note, date_display, start_ym, end_ym, is_current, summary) VALUES
(40, 'project', NULL, 'white-lotus', 'Rust; available on GitHub',
   'In progress', '2026-01', NULL, 1,
   'Distributed-systems components in Rust, implementing the HyParView peer-sampling membership protocol with Plumtree epidemic broadcast integration from scratch.');

-- ---------------------------------------------------------- publications ----

INSERT INTO entry (id, kind, org, title, date_display, start_ym, end_ym, is_current) VALUES
(50, 'publication', 'Qur''anic Ethics Seminar, University of Chicago Divinity School',
   '"An Islamic Grammar of Preservation: Waqf, Euro-Secular Heritage, and the Museification of Hagia Sophia."',
   'December 2025', '2025-12', '2025-12', 0),

(51, 'publication', 'Pastoral care case study on ikhlas, drawing on al-Ghazali and Héloïse d''Argenteuil',
   '"Knowing and Unknowing: Two Modes of Interior Misalignment in Religious Leadership."',
   'March 2026', '2026-03', '2026-03', 0),

(52, 'publication', 'Final paper on jumu''ah prayer, RELP 30500',
   '"Spaces of Speech, Acts of Worship, and the Slow Work of Guidance in Islam."',
   'December 2025', '2025-12', '2025-12', 0),

(53, 'publication', 'Scholasticide in Palestine (blog), University of Chicago',
   'Scholasticide Project publications: "STEM Education Under Blockade" (April 23, 2026), "Yaqeen Hammad: The Maker of Good" (June 27, 2025), and "Starvation Is a Weapon" (August 29, 2025).',
   '2025 – 2026', '2026-04', '2026-04', 0),

(54, 'publication', 'Women, Gender, and Sexuality in the MENA Conference, UIC',
   'Panelist, "Feminism and Palestinian Activism in the U.S."',
   'March 2022', '2022-03', '2022-03', 0);

-- ----------------------------------------------------------------- bullets --

INSERT INTO bullet (entry_id, sort_order, text) VALUES
-- 1 Field Museum
(1, 1, 'Conduct provenance investigations on individual objects and full acquisition catalogues, analyzing trade routes, import and export records, and antiquities law across multiple regions and historical periods, including navigating both physical and digital archives.'),
(1, 2, 'Support active NAGPRA cases in collaboration with Hopi and Pekuakamiulnuatsh (Innu) communities, including drafting and organizing appendices for repatriation proposals submitted to internal review committees and federal authorities.'),
(1, 3, 'Maintain confidential documentation regarding affiliated Tribal Nations and descendant communities within the EMu collections management system; produce Crystal Reports and structured object lists to identify repatriation-eligible objects and ancestors and flag materials for review.'),
(1, 4, 'Designed a custom PDF converter and integrated an AI-assisted workflow for transcription and translation of mixed French and English handwritten archival documents from Edward Ayre and other substantial accession files, reducing manual processing time on key case files for the Egypt and Nubia exhibit.'),
-- 1 Field Museum — ACE/USFWS rewrites, same entry, different pool members
(1, 11, 'Performed structured data entry across full acquisition catalogues, reconciling object records against archival source documents and correcting incomplete, inconsistent, and legacy-format entries related to active repatriation cases.'),
(1, 12, 'Drafted documentation appendices for repatriation proposals submitted to internal review committees and federal authorities under NAGPRA, requiring strict adherence to prescribed templates and federal reporting requirements.'),
(1, 13, 'Built an automated document-conversion and AI-assisted transcription workflow for mixed French and English handwritten archival material, reducing manual processing time on high-priority record sets, with 82% overall accuracy.'),

-- 2 Scholasticide Project
(2, 1, 'Conduct qualitative interviews with professors, students, and educational workers in Gaza documenting academic life under siege.'),
(2, 2, 'Author short-form public-facing articles synthesizing topics introduced in our interviews and providing historical context.'),
(2, 3, 'Build and maintain a comprehensive historical timeline of scholasticide in Gaza, integrating testimony, news reporting, and scholarly analysis.'),
(2, 4, 'Manage editorial workflow, source verification, and archival coordination for the project''s public platform; contribute to website design and organization in WordPress.'),
(2, 11, 'Perform structured qualitative coding of interview transcripts in Dedoose against a defined codebook for a forthcoming publication; coordinate recruitment and onboarding of Arabic–English translators for transcript preparation.'),

-- 3 Marty Center
(3, 1, 'Designed a long-term framework for digitizing the archives of small, immigrant, and minority religious institutions in Chicago, including workflow planning and metadata structure design.'),
(3, 2, 'Compiled and curated an annotated research library and bibliography to inform the project''s preservation strategy.'),

-- 4 UIC RA
(4, 1, 'Supported research on feminist models of affordable housing and their intersections with mental health, disability justice, and domestic violence prevention, with focus on POC and trans housing-insecure populations.'),
(4, 2, 'Conducted literature reviews, prepared conference presentations, and copyedited academic publications.'),

-- 5 Teaching
(5, 1, 'Led weekly discussion sections for a foundational undergraduate survey course; developed and delivered original lesson plans on visual analysis, the anthropology of art history, and contextual interpretation.'),
(5, 2, 'Held extensive office hours providing individualized writing support, conceptual clarification, and academic guidance.'),
(5, 3, 'Completed all grading for my discussion section across every assignment and exam on schedule, and proctored exams and quizzes.'),

-- 6 Believers Bail Out
(6, 1, 'Provide post-release support and court accompaniment for incarcerated Muslims; serve as liaison between defense attorneys, family members, and BBO staff to coordinate emergency funding disbursement.'),
(6, 2, 'Cleaned and standardized four years of intake and participant engagement data (2018–present) across four organizational spreadsheets using Python (pandas, NumPy, matplotlib) in Jupyter Notebooks; produced a report identifying data gaps and authored a follow-up recommendations report on best practices for ongoing data collection.'),
(6, 3, 'Co-facilitate a weekly online interfaith Seerah study group; developing a community education curriculum on Islam and abolition.'),

-- 7 Palestinian Assembly for Liberation
(7, 1, 'Directed national communications strategy across Instagram, Facebook, Twitter, and TikTok; authored and edited the monthly national newsletter for several thousand subscribers.'),
(7, 2, 'Managed bank accounts, coordinated fundraising, and documented expenditures for the national accounting team; supported legal affiliates with research memos and fundraising documentation.'),
(7, 3, 'Oversaw internal communications between regional chapters and national leadership across time zones; led national recruitment and advised chapters on internal strategy and mediation.'),
(7, 4, 'Coordinated with international and domestic coalition partners, including the production of comprehensive reports for international legal cases addressing humanitarian violations in Palestine.'),

-- 8 Jisoor Collective
(8, 1, 'Co-founded a community-led project focused on self-determination, digital security, and grassroots infrastructure.'),
(8, 2, 'Led programming including cybersecurity trainings, street medic courses, mental health workshops, and youth engagement events.'),
(8, 3, 'Collected and archived oral histories of displacement of the Palestinian diaspora in Chicago.'),

-- 9 Al Nahda Center
(9, 1, 'Wrote and managed federal grant application cycles for the Salwa Food Pantry; reviewed annual budgets, interpreted tax returns and financial statements, and advised on budget presentation for funders.'),
(9, 2, 'Rebuilt organizational documentation systems and established long-term reporting relationships with federal and private funders.'),
(9, 3, 'Managed federal grant compliance and reporting.'),

-- 10 Young Invincibles
(10, 1, 'Lobbied at the Illinois State Capitol and coordinated student testimony in support of the Mental Health Early Action on Campus Act (HB2152, signed August 2019).'),
(10, 2, 'Registered 3,000+ students to vote at UIC over a five-month period, in coalition with Chicago Votes and Power to the Polls.'),
(10, 3, 'Delivered presentations on higher education access and mental health advocacy across the Chicagoland area.'),

-- 11 Love and Belonging
(11, 1, 'Founded a grassroots sexual health and gender education initiative in collaboration with Planned Parenthood Southeast.'),
(11, 2, 'Developed and taught the first comprehensive sexual education program at Academe of the Oaks High School in Atlanta.'),

-- 12 Roosevelt Network
(12, 1, 'Co-authored policy materials supporting the Illinois Mental Health Early Action on Campus Act.'),
(12, 2, 'Supported anti-gentrification and labor organizing campaigns on campus.'),

-- 13 GEO
(13, 1, 'Organized undergraduate solidarity actions during GEO''s three-week strike (March 19 – April 5, 2019), including walkouts and support pickets.'),
(13, 2, 'Conducted contract research identifying leverage points for the bargaining team; the GEO settlement secured wage increases, fee relief, and stronger appointment transparency provisions.'),

-- 15 Georgia DPH
(15, 1, 'MSM STD outreach research and report writing and editing for internal publication.'),

-- 16 ISAC proofreading
(16, 1, 'Identify and document recurring error classes across complete sections to support consistency standards across the proofreading team and inform downstream correction passes.'),
(16, 2, 'Review and submit completed sections through the project''s editorial portal on a defined production schedule.'),

-- 17 Nixie Solutions
(17, 1, 'Trained in network architecture, covering the chronology and evolution of internet protocols, distributed-systems design patterns, and failure modes; apply the material directly to independent project white-lotus.'),
(17, 2, 'Draft service contracts and design invoicing and client documentation systems.'),

-- 30 MDiv
(30, 1, 'Thesis in progress: "Restitution and the State: Repatriation, Repentance, and the Limits of State-Led Repair." Advised by Prof. Alireza Doostdar.'),
(30, 2, 'Comparative study of NAGPRA and the 1952 Luxembourg Agreement, drawing on Maimonidean teshuvah, Islamic tawba, and theorists of state-formation.'),

-- 31 BA
(31, 1, 'Senior thesis: "Let Them Return Home: Creating Culturally Conscious NAGPRA Reform Prioritizing Indigenous Sovereignty and Spiritual Belief." Advised by Dr. Vincent LaMotta.');

-- ------------------------------------------------------------------ skills --

INSERT INTO skill (id, name, category, detail, sort_order) VALUES
-- research and writing
(1,  'Provenance and archival research',        'Research and writing', NULL, 1),
(2,  'Qualitative and quantitative data analysis','Research and writing', NULL, 2),
(3,  'Oral history interviewing',               'Research and writing', NULL, 3),
(4,  'Grant writing',                           'Research and writing', NULL, 4),
(5,  'Federal grant documentation',             'Research and writing', NULL, 5),
(6,  'Source verification',                     'Research and writing', NULL, 6),
(7,  'Public-facing reports',                   'Research and writing', NULL, 7),
(8,  'Annotated bibliographies',                'Research and writing', NULL, 8),
-- technical
(20, 'EMu collections management',              'Technical', NULL, 1),
(21, 'Crystal Reports',                         'Technical', NULL, 2),
(22, 'Python',                                  'Technical', 'pandas, NumPy, matplotlib, Jupyter', 3),
(23, 'Dedoose',                                 'Technical', NULL, 4),
(24, 'Rust',                                    'Technical', NULL, 5),
(25, 'Git',                                     'Technical', NULL, 6),
(26, 'PostgreSQL',                              'Technical', NULL, 7),
(27, 'WordPress',                               'Technical', NULL, 8),
(28, 'Adobe Creative Suite',                    'Technical', NULL, 9),
(29, 'Microsoft and Google Suites',             'Technical', NULL, 10),
(30, 'Mailchimp',                               'Technical', NULL, 11),
-- data practice (used by the federal-facing resume)
(40, 'Data cleaning and standardization',       'Data practice', NULL, 1),
(41, 'Structured data entry to template',       'Data practice', NULL, 2),
(42, 'Metadata structure design',               'Data practice', NULL, 3),
(43, 'Database querying and reporting',         'Data practice', NULL, 4),
(44, 'Technical proofreading',                  'Data practice', NULL, 5),
(45, 'Federal documentation standards',         'Data practice', NULL, 6),
-- organizational
(60, 'Budget review and reporting',             'Organizational', NULL, 1),
(61, 'Coalition-building',                      'Organizational', NULL, 2),
(62, 'Workshop facilitation',                   'Organizational', NULL, 3),
(63, 'Strategic communications',                'Organizational', NULL, 4),
(64, 'Conflict resolution',                     'Organizational', NULL, 5),
(65, 'Community consultation',                  'Organizational', NULL, 6),
-- languages
(80, 'English',                                 'Languages', 'native',        1),
(81, 'Arabic',                                  'Languages', 'A2 Levantine',  2),
(82, 'German',                                  'Languages', 'A1',            3),
(83, 'Spanish',                                 'Languages', 'A1',            4);

-- --------------------------------------------------- skill <-> entry links --
--  This is the correlation you asked for: which experience demonstrates which
--  skill. Query it in both directions — "what did I use Python for?" and
--  "what skills does the Field Museum role evidence?"

INSERT INTO entry_skill (entry_id, skill_id) VALUES
-- Field Museum
(1,1),(1,6),(1,20),(1,21),(1,40),(1,41),(1,45),
-- Scholasticide Project
(2,2),(2,3),(2,6),(2,7),(2,23),(2,27),
-- Marty Center
(3,1),(3,8),(3,42),
-- UIC RA
(4,2),(4,8),
-- Teaching
(5,7),
-- Believers Bail Out
(6,2),(6,22),(6,40),(6,43),(6,65),
-- Palestinian Assembly for Liberation
(7,60),(7,61),(7,63),(7,64),(7,30),(7,28),
-- Jisoor Collective
(8,3),(8,62),(8,65),
-- Al Nahda Center
(9,4),(9,5),(9,60),(9,45),
-- Young Invincibles
(10,61),(10,63),
-- Love and Belonging
(11,62),
-- Roosevelt Network
(12,61),
-- GEO
(13,61),(13,64),
-- Georgia DPH
(15,7),
-- ISAC proofreading
(16,44),(16,6),
-- Nixie Solutions
(17,24),(17,26),
-- white-lotus
(40,24),(40,25);

-- ---------------------------------------------------------------- variants --

INSERT INTO variant (id, profile_id, slug, title, density, paper, notes) VALUES
(1, 1, 'full-cv',   'Full academic CV',            1.0, 'us-letter',
    'Everything, reverse-chronological. Runs about four pages.'),
(2, 1, 'ace-usfws', 'ACE / USFWS targeted resume', 0.9, 'us-letter',
    'Federal, data-and-documentation framing. Two pages. Uses the reworded Field Museum and Scholasticide bullets.');

-- Headings live on the variant, which is how the same role sits under
-- "Research Experience" in one document and "Work Experience" in the other.
INSERT INTO section (id, variant_id, heading, sort_order) VALUES
-- full CV
(1, 1, 'Research Experience',                   1),
(2, 1, 'Teaching',                              2),
(3, 1, 'Non-Profit Leadership and Organizing',  3),
(4, 1, 'Education',                             4),
(5, 1, 'Writing and Presentations',             5),
(6, 1, 'Additional Experience',                 6),
-- targeted resume
(10, 2, 'Work Experience',                      1),
(11, 2, 'Research and Editorial Experience',    2),
(12, 2, 'Education',                            3),
(13, 2, 'Projects and Publications',            4),
(14, 2, 'Additional Experience',                5);

INSERT INTO variant_entry (variant_id, entry_id, section_id, sort_order) VALUES
-- ---- full CV ----
(1,  1, 1, 1), (1,  2, 1, 2), (1,  3, 1, 3), (1,  4, 1, 4),
(1,  5, 2, 1),
(1,  6, 3, 1), (1,  7, 3, 2), (1,  8, 3, 3), (1,  9, 3, 4),
(1, 10, 3, 5), (1, 11, 3, 6), (1, 12, 3, 7), (1, 13, 3, 8),
(1, 30, 4, 1), (1, 31, 4, 2),
(1, 50, 5, 1), (1, 51, 5, 2), (1, 52, 5, 3), (1, 53, 5, 4), (1, 54, 5, 5),
(1, 14, 6, 1), (1, 15, 6, 2),
-- ---- targeted resume: same rows, different headings and order ----
(2, 16, 10, 1), (2,  1, 10, 2), (2,  6, 10, 3), (2, 17, 10, 4),
(2,  2, 11, 1), (2,  3, 11, 2), (2,  4, 11, 3),
(2, 30, 12, 1), (2, 31, 12, 2),
(2, 40, 13, 1), (2, 53, 13, 2),
(2,  5, 14, 1);

-- Bullet selection. Only needed where a variant departs from "all bullets in
-- natural order" — here, the two entries the resume rewrites.
INSERT INTO variant_bullet (variant_id, bullet_id, sort_order)
SELECT 2, id, sort_order FROM bullet WHERE entry_id = 1 AND sort_order >= 11;
INSERT INTO variant_bullet (variant_id, bullet_id, sort_order)
SELECT 2, id, sort_order FROM bullet WHERE entry_id = 2 AND sort_order IN (11, 4);
-- The full CV uses the original wording for those same two entries.
INSERT INTO variant_bullet (variant_id, bullet_id, sort_order)
SELECT 1, id, sort_order FROM bullet WHERE entry_id = 1 AND sort_order <= 4;
INSERT INTO variant_bullet (variant_id, bullet_id, sort_order)
SELECT 1, id, sort_order FROM bullet WHERE entry_id = 2 AND sort_order <= 4;

-- Which skill categories each document shows.
INSERT INTO variant_skill (variant_id, skill_id)
SELECT 1, id FROM skill
 WHERE category IN ('Research and writing','Technical','Organizational','Languages');
INSERT INTO variant_skill (variant_id, skill_id)
SELECT 2, id FROM skill
 WHERE category IN ('Technical','Data practice','Languages');
