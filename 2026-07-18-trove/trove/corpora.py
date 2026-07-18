"""A purpose-built corpus loader for Trove's own demo: this repository's
history of past daily builds. `build_index` (in index.py) is fully
generic and recursive, which is the right default for indexing an
arbitrary directory — but pointed at this repo's root it would also
sweep up every past project's test fixtures, DIMACS files, RFC test
vectors, and so on. This loader instead indexes exactly the documents
that describe the projects: each dated folder's top-level README.md, and
each per-project entry inside the shared LEDGER.md."""

import os
import re

from .index import InvertedIndex, split_markdown_sections

DATED_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def build_repo_history_index(repo_root):
    repo_root = os.path.abspath(repo_root)
    index = InvertedIndex()

    for name in sorted(os.listdir(repo_root)):
        full = os.path.join(repo_root, name)
        if not os.path.isdir(full) or not DATED_FOLDER_RE.match(name):
            continue
        readme = os.path.join(full, "README.md")
        if not os.path.isfile(readme):
            continue
        with open(readme, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if text.strip():
            index.add_document(name, text, path=f"{name}/README.md", title=name)

    ledger = os.path.join(repo_root, "LEDGER.md")
    if os.path.isfile(ledger):
        with open(ledger, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        for title, body in split_markdown_sections(text):
            if not title or not body.strip():
                continue
            index.add_document(f"LEDGER.md#{title}", body, path="LEDGER.md", title=title)

    index.finalize()
    return index
