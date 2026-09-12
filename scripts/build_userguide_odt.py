#!/usr/bin/env python3
# Regenerate doc/Using_OpenEMS_Python_with_IHP_SG13G2_v3.odt from the Markdown source at
# doc/userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md. The Markdown stays the
# source of truth - edit that, then run this script if you want an .odt to finish/export
# yourself in LibreOffice Writer. Run from the repo root: python scripts/build_userguide_odt.py
#
# Requires pandoc (https://pandoc.org/) on PATH. Pandoc writes ODT natively, so unlike
# build_userguide_pdf.py this needs no separate PDF-rendering engine.
#
# The guide's own "## Contents" section and internal [text](#anchor) links use GitHub's
# Markdown anchor format, for correct rendering/navigation on GitHub itself. Those anchors
# don't mean anything in an ODT, so this script strips both (the manual TOC block, and internal
# links down to their plain text) from a throwaway copy before handing it to pandoc, and lets
# pandoc/LibreOffice generate their own table of contents instead.
#
# Relative links to other files in the repo (e.g. ../XML_stackup_format.md, ../../README.md)
# are correct on GitHub and correct for pandoc run from the source file's own directory, but
# once the built .odt is saved into doc/ - one directory above the source .md - those same
# relative paths no longer point at the right file on disk. LibreOffice then shows them as
# broken or misleadingly "local" links. So those are rewritten to absolute GitHub URLs here,
# same as build_pypi_readme.py already does for README.md's own doc/ links.

import os
import re
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_MD = os.path.join(REPO_ROOT, 'doc', 'userguide_md_format', 'Using_OpenEMS_Python_with_IHP_SG13G2_v3.md')
DST_ODT = os.path.join(REPO_ROOT, 'doc', 'Using_OpenEMS_Python_with_IHP_SG13G2_v3.odt')

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

    try:
        with open(tmp_md, 'w', encoding='utf-8') as f:
            f.write(text)

        subprocess.run(['pandoc', os.path.basename(tmp_md), '-o', DST_ODT,
                         '--standalone', '--toc'], cwd=src_dir, check=True)
    finally:
        if os.path.exists(tmp_md):
            os.remove(tmp_md)

    print(f'Wrote {DST_ODT}')


if __name__ == '__main__':
    main()
