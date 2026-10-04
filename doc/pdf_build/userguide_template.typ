// Typst layout for the PDF user's guide, filled in by build_userguide_pdf.py.
// Identical in gds2palace_ihp_sg13g2 and openems_ihp_sg13g2 (gds2openEMS): keep both in sync.

// @@METADATA@@

#let accent = rgb("#0b4f8a")
#let muted  = rgb("#5a6470")
#let rule   = rgb("#d0d5db")
#let codebg = rgb("#f4f6f8")

// used by pandoc's Typst output
#let horizontalrule = line(length: 100%, stroke: 0.5pt + muted)
#show terms.item: it => block(breakable: false)[
  #text(weight: "bold")[#it.term]
  #block(inset: (left: 1.5em, top: -0.4em))[#it.description]
]

#set document(title: doc-title, author: doc-author)
#set text(font: "Source Sans 3", size: 10.5pt, lang: "en")
#set par(justify: true, leading: 0.62em, spacing: 0.95em)
#set page(
  paper: "a4",
  margin: (x: 22mm, top: 24mm, bottom: 22mm),
  header: context {
    if counter(page).get().first() > 2 [
      #set text(8.5pt, fill: muted)
      #doc-title #h(1fr) Document version #doc-version
      #v(-0.6em) #line(length: 100%, stroke: 0.4pt + muted)
    ]
  },
  footer: context {
    if counter(page).get().first() > 1 [
      #set text(8.5pt, fill: muted)
      #h(1fr) #counter(page).display() #h(1fr)
    ]
  },
)

// headings: numbered, accent colour, kept together with the following paragraph
#set heading(numbering: "1.1")
#show heading: set text(fill: accent, weight: "semibold")
#show heading: set block(sticky: true)
#show heading.where(level: 1): it => {
  v(1.4em)
  block(below: 0.9em, {
    set text(17pt)
    it
    v(-0.5em)
    line(length: 100%, stroke: 1pt + accent)
  })
}
#show heading.where(level: 2): set text(13pt)
#show heading.where(level: 2): set block(above: 1.5em, below: 0.8em)
#show heading.where(level: 3): set text(11pt)
#show heading.where(level: 4): set text(10.5pt)
#show heading.where(level: 4): set heading(numbering: none)

#show link: set text(fill: accent)

// code: DejaVu Sans Mono is built into Typst
#show raw: set text(font: "DejaVu Sans Mono", size: 8.6pt)
#show raw.where(block: true): it => block(
  width: 100%, fill: codebg, inset: (x: 9pt, y: 7pt), radius: 3pt,
  stroke: (left: 2.5pt + accent.lighten(40%)), it,
)

// figures and tables
#set figure(gap: 0.7em)
#show figure: set block(breakable: false, above: 1.2em, below: 1.4em)
#show figure.caption: it => text(9pt, fill: muted)[
  #text(weight: "semibold")[#it.supplement #context it.counter.display(it.numbering)]: #it.body
]
#show image: it => box(stroke: 0.4pt + rule, it)
#set table(inset: (x: 7pt, y: 5pt), stroke: (x, y) => (
  top: if y == 0 { 1pt + accent } else if y == 1 { 0.6pt + accent } else { 0.3pt + rule },
  bottom: 1pt + accent,
))
#show table.cell: set align(left)
#show table.cell.where(y: 0): set text(weight: "semibold")
#show table: set text(9.5pt)
#show table: set par(justify: false)

// ---------- title page ----------
#page(header: none, footer: none, margin: (x: 25mm, y: 30mm))[
  #v(1fr)
  #text(11pt, fill: muted, tracking: 0.08em)[IHP SG13G2 · OPEN SOURCE RFIC EM WORKFLOW]
  #v(0.6em)
  #line(length: 100%, stroke: 2pt + accent)
  #v(0.8em)
  #par(justify: false, leading: 0.45em, text(30pt, weight: "bold", fill: accent, doc-title))
  #if doc-subtitle != "" {
    v(0.3em)
    text(16pt, fill: muted, doc-subtitle)
  }
  #v(2fr)
  #text(12pt, doc-author) \
  #if doc-email != "" { link("mailto:" + doc-email, text(10.5pt, doc-email)) } \
  #v(0.3em)
  #text(10.5pt, fill: muted)[Document version #doc-version]
]

// ---------- table of contents ----------
#page(header: none)[
  #show outline.entry.where(level: 1): it => { v(0.5em); strong(it) }
  #outline(title: text(fill: accent)[Contents], depth: 2, indent: auto)
]

// @@BODY@@
