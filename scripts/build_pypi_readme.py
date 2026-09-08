#!/usr/bin/env python3
# Build a short PyPI package-page README instead of dumping the full,
# screenshot-heavy repo README.md into the long_description: title + intro
# (reused verbatim from README.md) + install line + a link to GitHub for full
# docs + the last few dated entries from doc/CHANGES.md, so PyPI visitors can
# see what actually changed without digging through the whole README. Writes
# README_pypi.md at repo root, which pyproject.toml's readme= key points at.
# Regenerate before every build.

import os
import re
import tomllib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_BASE = "https://raw.githubusercontent.com/VolkerMuehlhaus/gds2openEMS/main/"
REPO_URL = "https://github.com/VolkerMuehlhaus/gds2openEMS"

def rewrite_relative_links(text):
    def replace(match):
        prefix, path = match.group(1), match.group(2)
        return f"{prefix}({RAW_BASE}{path})"

    return re.sub(r'(!?\[[^\]]*\])\(\./([^)]+)\)', replace, text)

def extract_intro(readme_text):
    # title is the first line, intro is everything up to (not including) the
    # next heading line - already a good one-paragraph description, reused
    # verbatim instead of hand-writing a separate PyPI blurb that could drift
    lines = readme_text.splitlines()
    title = lines[0]
    body = []
    for line in lines[1:]:
        if line.startswith('#'):
            break
        body.append(line)
    return title, '\n'.join(body).strip()

def extract_recent_changes(n=3, heading_level=2):
    # doc/CHANGES.md starts with a "# Change list" title, then dated entries
    # as "## <date>" headings - split on those and drop the leading title chunk
    with open(os.path.join(REPO_ROOT, 'doc', 'CHANGES.md'), 'r', encoding='utf-8') as f:
        text = f.read()

    marker = '#' * heading_level + ' '
    chunks = re.split(rf'\n(?={re.escape(marker)})', text)
    entries = [c.strip() for c in chunks if c.strip().startswith(marker)]
    return '\n\n'.join(entries[:n])

def package_requirements_note():
    # README.md's "System requirements" section describes the whole repo/workflow
    # (including example scripts), which needs more than the installed package
    # itself does. Append an accurate note derived straight from pyproject.toml's
    # dependencies, so the PyPI page can't drift from what pip actually installs.
    with open(os.path.join(REPO_ROOT, 'pyproject.toml'), 'rb') as f:
        project = tomllib.load(f)['project']

    deps = '\n'.join(f'- {d}' for d in project['dependencies'])
    return (
        f"\n\n---\n\n**Note:** the `{project['name']}` PyPI package itself only requires:\n\n"
        f"{deps}\n\n"
        "(Other Python modules mentioned above are only needed to run the example/model "
        "scripts in this repository, not to use the installed package.)\n"
    )

def main():
    src_path = os.path.join(REPO_ROOT, 'README.md')
    dst_path = os.path.join(REPO_ROOT, 'README_pypi.md')

    with open(src_path, 'r', encoding='utf-8') as f:
        readme_text = f.read()

    with open(os.path.join(REPO_ROOT, 'pyproject.toml'), 'rb') as f:
        project_name = tomllib.load(f)['project']['name']

    title, intro = extract_intro(readme_text)
    recent_changes = extract_recent_changes(n=3)
    changelog_url = f"{REPO_URL}/blob/main/doc/CHANGES.md"

    parts = [
        title,
        rewrite_relative_links(intro),
        f'## Install\n\n    pip install {project_name}',
        f'**Full documentation, installation guide, and usage walkthrough:**\n{REPO_URL}',
        '## Recent changes',
        rewrite_relative_links(recent_changes),
        f'Full history: [CHANGES.md]({changelog_url})',
    ]
    text = '\n\n'.join(parts)
    text += package_requirements_note()

    with open(dst_path, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f'Wrote {dst_path}')

if __name__ == '__main__':
    main()
