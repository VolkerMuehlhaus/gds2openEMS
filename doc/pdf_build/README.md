# Building the PDF user's guide

The user's guide is written in Markdown: [`../userguide_md_format/`](../userguide_md_format/). That file is the only source. The PDF in [`../`](../) is generated from it, so don't edit the PDF by hand.

## Build

```bash
pip install -r requirements.txt     # pandoc (pypandoc_binary), typst, pillow
python build_userguide_pdf.py
```

This writes `../<name of the .md file>.pdf`, replacing the previous PDF. Run it again after every change to the Markdown, and commit the `.md` and the `.pdf` together.

How it works: pandoc converts the Markdown to [Typst](https://typst.app), and Typst compiles it to PDF using the layout in `userguide_template.typ` (title page, table of contents, numbered figures, page headers and footers). Run `python build_userguide_pdf.py --help` for the options.

The build doesn't change the Markdown file or its images:
- The header of the `.md` (title, author, `Document version:` line) becomes the title page. The hand-written `## Contents` section, which is useful on GitHub, is replaced by a generated table of contents.
- Images larger than 150 kB are embedded as JPEG (quality 88), because Typst embeds PNG files without compression, which would triple the PDF size. Use `--no-image-compression` to embed all images unchanged.
- The fonts are in `fonts/` (Source Sans 3, SIL Open Font License), so the PDF looks the same on every machine. The code font, DejaVu Sans Mono, is built into Typst.

## Writing Markdown that gives a good PDF

- **Figures:** an image on its own line with alt text becomes a numbered figure, and the alt text is its caption: `![Mesh of the SiO2 volume](./images/mesh.png)`. Without alt text, the image has no number and no caption.
- **Links:** use `<https://...>` or `[text](https://...)`. Links to headings in the same file (`[settings](#settings)`) work in the PDF too. A link to a heading that doesn't exist stops the build with an error, so the build also checks these links.
- **Footnotes:** `text[^name]`, and somewhere below, `[^name]: footnote text`.
- **Code:** fenced code blocks, with a language for syntax highlighting (```` ```python ````).
- **Tables:** pipe tables (`| a | b |`).
- Don't use HTML tags like `<u>` or `<sup>`: they are dropped in the PDF.

## Keep in sync

`build_userguide_pdf.py`, `userguide_template.typ`, `requirements.txt`, this README and the fonts are identical in [gds2palace_ihp_sg13g2](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2/tree/main/doc/pdf_build) and [gds2openEMS](https://github.com/VolkerMuehlhaus/gds2openEMS/tree/main/doc/pdf_build). Copy a change to the other repository.
