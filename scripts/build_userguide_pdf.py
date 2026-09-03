#!/usr/bin/env python3
# Regenerate doc/Using_OpenEMS_Python_with_IHP_SG13G2_v3.pdf from the Markdown source at
# doc/userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md. The Markdown is the
# source of truth - edit that, then run this script to refresh the PDF. Run after every edit
# to the guide, from the repo root: python scripts/build_userguide_pdf.py
#
# Requires pandoc (https://pandoc.org/) on PATH, and the 'typst' Python package
# (pip install typst) as the PDF-rendering engine - a self-contained, pure-wheel engine that
# needs no separate LaTeX or GTK/Pango install, unlike pandoc's other --pdf-engine options.
#
# The guide's own "## Contents" section and internal [text](#anchor) links use GitHub's
# Markdown anchor format, for correct rendering/navigation on GitHub itself. typst's own
# auto-generated heading labels don't reliably match those hand-picked anchor slugs, so this
# script strips both (the manual TOC block, and internal links down to their plain text) from
# a throwaway copy before handing it to pandoc/typst, and lets typst auto-generate its own
# table of contents and figure numbering instead.
#
# Relative links to other files in the repo (e.g. ../XML_stackup_format.md, ../../README.md)
# are correct on GitHub and correct for pandoc run from the source file's own directory, but
# once the built .pdf is saved into doc/ - one directory above the source .md - those same
# relative paths no longer point at the right file on disk. So those are rewritten to absolute
# GitHub URLs here, same as build_pypi_readme.py already does for README.md's own doc/ links.

import os
import re
import subprocess

import typst

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_MD = os.path.join(REPO_ROOT, 'doc', 'userguide_md_format', 'Using_OpenEMS_Python_with_IHP_SG13G2_v3.md')
DST_PDF = os.path.join(REPO_ROOT, 'doc', 'Using_OpenEMS_Python_with_IHP_SG13G2_v3.pdf')

GITHUB_BLOB_BASE = 'https://github.com/VolkerMuehlhaus/gds2openEMS/blob/main/'
# SRC_MD lives in doc/userguide_md_format/, so one level up ('../') lands in doc/,
# and two levels up ('../../') lands at the repo root.
UPDIR_TO_REPO_PATH = {1: 'doc/', 2: ''}


def rewrite_relative_links(text):
    def replace(match):
        label, updirs, path = match.group(1), match.group(2), match.group(3)
        depth = len(updirs) // 3  # each '../' is 3 characters
        return f'[{label}]({GITHUB_BLOB_BASE}{UPDIR_TO_REPO_PATH[depth]}{path})'

    return re.sub(r'\[([^\]]+)\]\(((?:\.\./)+)([^)]+)\)', replace, text)


def strip_github_only_markup(text):
    text = re.sub(r'## Contents\n.*?\n(?=## )', '', text, flags=re.DOTALL)
    text = rewrite_relative_links(text)
    text = re.sub(r'\[([^\]]+)\]\(#[^)]+\)', r'\1', text)
    return text


def main():
    with open(SRC_MD, encoding='utf-8') as f:
        text = f.read()
    text = strip_github_only_markup(text)

    src_dir = os.path.dirname(SRC_MD)
    tmp_md = os.path.join(src_dir, '_tmp_build.md')
    tmp_typ = os.path.join(src_dir, '_tmp_build.typ')

    try:
        with open(tmp_md, 'w', encoding='utf-8') as f:
            f.write(text)

        subprocess.run(['pandoc', os.path.basename(tmp_md), '-o', os.path.basename(tmp_typ),
                         '--standalone', '--toc'], cwd=src_dir, check=True)
        typst.compile(tmp_typ, output=DST_PDF)
    finally:
        for p in (tmp_md, tmp_typ):
            if os.path.exists(p):
                os.remove(p)

    print(f'Wrote {DST_PDF}')


if __name__ == '__main__':
    main()
