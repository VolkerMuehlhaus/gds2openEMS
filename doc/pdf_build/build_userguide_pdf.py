"""Build the PDF user's guide from the Markdown user's guide.

The Markdown file in ../userguide_md_format/ is the only source. This script converts it
with pandoc to Typst and compiles it with Typst, using userguide_template.typ for the
layout (title page, table of contents, numbered figures, headers and footers).

Usage:
    pip install -r requirements.txt
    python build_userguide_pdf.py                 # finds ../userguide_md_format/*.md
    python build_userguide_pdf.py guide.md -o guide.pdf

The Markdown file is not changed. Its header (title, author, "Document version:" line)
and the hand-written "## Contents" section are replaced by the generated title page and
table of contents in the PDF.

This script and the template are identical in gds2palace_ihp_sg13g2 and
openems_ihp_sg13g2 (gds2openEMS). Keep both copies in sync.
"""

__version__ = "1.0.0"

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "userguide_template.typ"
FONTS = HERE / "fonts"

# pandoc reader: CommonMark like GitHub, plus the pandoc extensions the guides use
PANDOC_FROM = ("commonmark_x+implicit_figures+gfm_auto_identifiers"
               "+tex_math_dollars+footnotes+pipe_tables")


def find_pandoc():
    """Prefer the pandoc binary from pypandoc_binary (same version everywhere), then PATH."""
    exe = None
    try:
        import pypandoc
        bundled = Path(pypandoc.__file__).parent / "files"
        exe = next((str(bundled / n) for n in ("pandoc.exe", "pandoc") if (bundled / n).is_file()), None)
    except ImportError:
        pass
    exe = exe or shutil.which("pandoc")
    if not exe:
        sys.exit("pandoc not found: pip install -r requirements.txt")
    version = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.split("\n")[0]
    m = re.search(r"(\d+)\.(\d+)", version)
    if not m or (int(m.group(1)), int(m.group(2))) < (3, 8):
        sys.exit(f"{exe}: {version}, but pandoc 3.8 or newer is needed: pip install -U pypandoc_binary")
    return exe, version


def split_header(md):
    """Return (metadata dict, body) from the user's guide Markdown.

    Expected header, as used by both user's guides:
        # <title>[:] User's Guide
        <author>, <email>
        ---
        Document version: <version>
        ## Contents
        ... hand-written links ...
        ## <first chapter>
    """
    lines = md.splitlines()
    meta = {"title": "", "subtitle": "", "author": "", "email": "", "version": ""}
    i = 0
    while i < len(lines) and not lines[i].startswith("## "):
        line = lines[i].strip()
        if line.startswith("# ") and not meta["title"]:
            title = line[2:].strip()
            m = re.match(r"(.*?)[:\s]*\b(User[’']s Guide)$", title)
            meta["title"], meta["subtitle"] = (m.group(1), m.group(2)) if m else (title, "")
        elif line.lower().startswith("document version:"):
            meta["version"] = line.split(":", 1)[1].strip()
        elif "@" in line and not meta["author"]:
            name, _, email = line.partition(",")
            meta["author"], meta["email"] = name.strip(), email.strip()
        i += 1
    if i < len(lines) and lines[i].strip().lower() == "## contents":
        i += 1
        while i < len(lines) and not lines[i].startswith("## "):
            i += 1
    if not meta["title"]:
        sys.exit("no '# <title>' line found before the first chapter")
    return meta, "\n".join(lines[i:]) + "\n"


def compress_images(body, md_dir, tmp_dir, min_size, quality):
    """Typst embeds PNGs losslessly, so large screenshots make a huge PDF. Use JPEG copies
    (in tmp_dir, the originals are not changed) for opaque images above min_size bytes."""
    from PIL import Image
    saved = 0

    def repl(m):
        nonlocal saved
        src = (md_dir / m.group(2)).resolve()
        if not src.is_file() or src.stat().st_size < min_size:
            return m.group(0)
        with Image.open(src) as im:
            if im.convert("RGBA").getextrema()[3][0] < 255:
                return m.group(0)  # real transparency: keep PNG
            dst = tmp_dir / (src.stem + ".jpg")
            tmp_dir.mkdir(exist_ok=True)
            im.convert("RGB").save(dst, "JPEG", quality=quality, optimize=True)
        if dst.stat().st_size >= src.stat().st_size:
            return m.group(0)
        saved += src.stat().st_size - dst.stat().st_size
        return m.group(1) + dst.relative_to(md_dir).as_posix() + m.group(3)

    body = re.sub(r"(!\[[^\]]*\]\()(?:\./)?([^)\s]+)(\))", repl, body)
    return body, saved


def typst_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("markdown", nargs="?", help="user's guide .md (default: ../userguide_md_format/*.md)")
    ap.add_argument("-o", "--output", help="output PDF (default: ../<markdown name>.pdf)")
    ap.add_argument("--jpeg-quality", type=int, default=88,
                    help="JPEG quality for large images in the PDF (default 88)")
    ap.add_argument("--no-image-compression", action="store_true",
                    help="embed all images unchanged (lossless, much larger PDF)")
    ap.add_argument("--keep-typ", action="store_true", help="keep the intermediate .typ file for debugging")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    if args.markdown:
        md_path = Path(args.markdown).resolve()
    else:
        found = sorted((HERE.parent / "userguide_md_format").glob("*.md"))
        if len(found) != 1:
            sys.exit(f"expected exactly one .md in ../userguide_md_format, found {len(found)}")
        md_path = found[0]
    out_path = Path(args.output).resolve() if args.output else HERE.parent / (md_path.stem + ".pdf")

    sys.stdout.reconfigure(encoding="utf-8")
    meta, body = split_header(md_path.read_text(encoding="utf-8"))
    print(f"input:    {md_path}")
    print(f"output:   {out_path}")
    for k, v in meta.items():
        print(f"{k + ':':9} {v}")
    print(f"images:   {'unchanged' if args.no_image_compression else f'JPEG quality {args.jpeg_quality} above 150 kB'}")

    tmp_dir = md_path.parent / "_pdf_images"
    if not args.no_image_compression:
        body, saved = compress_images(body, md_path.parent, tmp_dir, 150_000, args.jpeg_quality)
        print(f"          {saved / 1e6:.1f} MB saved by JPEG")

    # pandoc: Markdown body -> Typst body (## chapters become level-1 headings)
    pandoc, pandoc_version = find_pandoc()
    import typst
    print(f"tools:    {pandoc_version}, typst-py {getattr(typst, '__version__', '?')}")
    res = subprocess.run(
        [pandoc, "-f", PANDOC_FROM, "-t", "typst", "--shift-heading-level-by=-1",
         "--syntax-highlighting=idiomatic", "--wrap=none"],
        input=body, capture_output=True, text=True, encoding="utf-8")
    if res.returncode:
        sys.exit("pandoc failed:\n" + res.stderr)
    if res.stderr.strip():
        print(res.stderr.strip())

    header = "\n".join(f"#let doc-{k} = {typst_string(v)}" for k, v in meta.items())
    template = TEMPLATE.read_text(encoding="utf-8")
    typ_source = template.replace("// @@METADATA@@", header).replace("// @@BODY@@", res.stdout)

    # compile next to the .md, so that relative image paths resolve
    typ_path = md_path.with_name("_" + md_path.stem + ".typ")
    typ_path.write_text(typ_source, encoding="utf-8")
    try:
        typst.compile(str(typ_path), output=str(out_path), root=str(md_path.parent),
                      font_paths=[str(FONTS)], ignore_system_fonts=True)
    except Exception as e:  # typst reports source errors as exceptions with location info
        sys.exit(f"typst failed (intermediate file kept: {typ_path}):\n{e}")
    if not args.keep_typ:
        typ_path.unlink()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"written:  {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
