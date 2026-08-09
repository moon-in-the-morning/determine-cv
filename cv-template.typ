// ============================================================================
//  ATS-friendly CV template — Garamond, left-aligned metadata
// ----------------------------------------------------------------------------
//  Design constraints this template deliberately respects:
//    - Single column, no text boxes, no tables-as-layout, no sidebars.
//      Parsers read top-to-bottom, left-to-right; anything else scrambles.
//    - No grids anywhere. Dates and locations sit on their own left-aligned
//      line, so the extracted text is literally the text you see.
//    - Real, selectable text only. No icons carrying meaning, no images.
//    - Conventional section names (EXPERIENCE, EDUCATION, SKILLS...).
//    - Pure black on white for contrast; hierarchy comes from weight,
//      size, and space rather than color.
// ============================================================================

// ---------------------------------------------------------------- style knobs
// Edit these to restyle the whole document.

#let ink = rgb("#000000") // body text
#let ink-soft = rgb("#2b2b2b") // dates, locations, secondary detail
#let rule-ink = rgb("#000000") // section underlines
#let rule-weight = 0.9pt

// Adobe Garamond Pro (Regular / Italic / Bold / Bold Italic all installed).
// If you ever compile this on a machine without it, add "EB Garamond" to the
// front of the list and install that instead — it's free and near-identical.
#let cv-font = ("Adobe Garamond Pro", "Times New Roman")

// Garamond has a small x-height and sets smaller than a sans at the same
// nominal size, so 11pt here reads like ~10pt Helvetica.
// Garamond kerns pairs like "Tr", "Te", "Tw" by emitting them as separate
// text runs in the PDF. Some extractors then read "Tribal" as "T ribal" and
// "Technical" as "T echnical" -- a silently missed keyword. Turning kerning
// off makes every word extract whole, at the cost of a little tightness in
// those pairs. Set to `true` if you'd rather have the tighter typography.
#let use-kerning = false

#let base-size = 11pt
#let name-size = 21pt
#let section-size = 11.5pt
#let entry-size = 11pt

// THE KNOB YOU ACTUALLY WANT when you're two lines over a page boundary.
// Scales every vertical gap and the line spacing at once, so the page gets
// tighter or airier without any single element looking off.
//   1.00  default -- roomy
//   0.90  snug, still comfortable
//   0.80  dense; about as far as you should go
//   1.15  airy, for a short CV that needs to fill the page
#let density = 1.0

#let section-gap = 14pt * density // space above each section heading
#let entry-gap = 13pt * density // space above each job / school / project
#let leading = 0.65em * density // space between lines within a paragraph
#let para-gap = 0.8em * density // space between paragraphs
#let bullet-gap = 0.75em * density // space between bullets in a list

// Separator between date and location on the metadata line.
#let meta-sep = "  ·  "

// ------------------------------------------------------------------ document

// Root wrapper. Put this at the top of your CV file as a show rule:
//   #show: cv.with(name: "...", contacts: (...))
#let cv(
  name: "",
  // Lines under the name, in order. Each is an array joined with `separator`.
  // Rendered italic if `italic-lines` includes its index.
  subtitle: none, // e.g. "Legal name: ... • All pronouns" (italic)
  contacts: (), // e.g. (email, phone, city)
  separator: "  •  ",
  header-align: center, // `left` if you'd rather the header hug the margin
  paper: "us-letter", // "a4" if you're applying outside the US
  margin: 0.85in,
  font: cv-font,
  size: base-size,
  body,
) = {
  set document(title: name + " - Curriculum Vitae", author: name)
  set page(paper: paper, margin: margin)

  set text(
    font: font,
    size: size,
    fill: ink,
    lang: "en",
    // Hyphenation splits keywords across lines, which can break exact-match
    // keyword scanning. Off by default.
    hyphenate: false,
    kerning: use-kerning,
  )

  // Ragged right: justification opens rivers of space at this measure and
  // adds nothing a parser can use.
  set par(justify: false, leading: leading, spacing: para-gap)

  // Bullet lists: a plain round bullet extracts as a clean list item.
  set list(marker: [•], indent: 0pt, body-indent: 8pt, spacing: bullet-gap)
  show list: set par(leading: leading)

  // Links stay black and unadorned so they read as text, not decoration.
  show link: set text(fill: ink)

  // Typst turns " and ' into typographic quotes. Modern parsers handle these
  // fine. Uncomment if you hit an unusually old system that mangles them.
  // set smartquote(enabled: false)

  // ---- header ----
  block(width: 100%, below: 0pt)[
    #align(header-align)[
      #text(size: name-size, weight: "bold", tracking: 0.04em, upper(name))

      #if subtitle != none {
        v(3pt * density)
        text(size: 10pt, style: "italic", fill: ink-soft, subtitle)
      }

      #if contacts.len() > 0 {
        v(2.5pt * density)
        text(size: 10.5pt, fill: ink, contacts.join(separator))
      }
    ]
  ]

  body
}

// ------------------------------------------------------------------ sections

// A section heading: uppercase, letter-spaced, underlined full width.
#let section(title) = block(
  width: 100%,
  above: section-gap,
  below: 9pt * density,
  breakable: false,
)[
  #text(size: section-size, weight: "bold", tracking: 0.06em, upper(title))
  #v(2.5pt)
  #line(length: 100%, stroke: rule-weight + rule-ink)
]

// ------------------------------------------------------------------- entries

// One position / degree / project. Three stacked left-aligned lines:
//
//   Organization — Role                          <- bold
//   Sept. 2025 – June 2026 · Chicago, IL         <- italic, secondary
//   Department; supervisor: Dr. A. Reyes           <- italic, optional
//   • bullets
//
// Nothing is right-aligned and there is no grid, so the extracted text runs
// in exactly this order. Every argument is optional; omitted lines collapse.
#let entry(
  org: none,
  role: none,
  dates: none,
  location: none,
  note: none, // advisor, department, supervisor, subtitle
  body,
) = block(width: 100%, above: entry-gap, below: 0pt, breakable: true)[
  // --- line 1: organization — role ---
  #{
    let head = if org != none and role != none {
      [#org #sym.dash.em #role]
    } else if org != none { org } else { role }

    if head != none {
      block(below: 0pt, text(size: entry-size, weight: "bold", head))
    }
  }

  // --- line 2: dates · location ---
  #{
    let meta = ((dates, location).filter(x => x != none))
    if meta.len() > 0 {
      block(above: 4pt * density, below: 0pt, text(
        size: 10pt,
        style: "italic",
        fill: ink-soft,
        meta.join(meta-sep),
      ))
    }
  }

  // --- line 3: advisor / department / other qualifier ---
  #if note != none {
    block(
      above: 3pt * density,
      below: 0pt,
      text(size: 10pt, style: "italic", fill: ink-soft, note),
    )
  }

  #if body != none {
    block(above: 7pt * density, below: 0pt, body)
  }
]

// -------------------------------------------------------------------- skills

// One skill row: bold category, then a comma-separated list.
// Kept as running text (not a grid of chips) so every term extracts.
#let skill(category, items) = block(width: 100%, above: 8pt * density, below: 0pt)[
  #text(weight: "bold", category)#text[: ]#items
]

// --------------------------------------------------------- publications etc.

// A citation-style line for publications, talks, or short project blurbs.
// `note` becomes a left-aligned italic second line, same as in `entry`.
#let item(body, note: none) = block(width: 100%, above: 11pt * density, below: 0pt)[
  #block(below: 0pt, body)
  #if note != none {
    block(
      above: 3pt * density,
      below: 0pt,
      text(size: 10pt, style: "italic", fill: ink-soft, note),
    )
  }
]
