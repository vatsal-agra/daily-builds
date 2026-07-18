"""The inverted index: documents in, postings lists out. Persisted as JSON
so `trove build` and `trove search` are separate, independent steps."""

import json
import os
import re
from collections import defaultdict

from .tokenizer import tokenize

HEADER_SPLIT_RE = re.compile(r"^##\s+(.*)$", re.MULTILINE)


class InvertedIndex:
    def __init__(self):
        # term -> {doc_id: [position, position, ...]}
        self.postings = {}
        # doc_id -> number of (stemmed, non-stopword) tokens in the doc
        self.doc_lengths = {}
        # doc_id -> {"title":, "path":, "text":}
        self.doc_meta = {}
        # stemmed term -> a representative raw surface form, for
        # human-friendly display of fuzzy corrections and suggestions
        self.term_surface = {}
        self.N = 0
        self.avg_doc_length = 0.0

    # -- building ---------------------------------------------------
    def add_document(self, doc_id, text, path=None, title=None):
        if doc_id in self.doc_meta:
            raise ValueError(f"duplicate doc_id: {doc_id}")
        tokens = tokenize(text)
        self.doc_lengths[doc_id] = len(tokens)
        self.doc_meta[doc_id] = {
            "path": path or doc_id,
            "title": title or doc_id,
            "text": text,
        }
        term_positions = defaultdict(list)
        for pos, tok in enumerate(tokens):
            term_positions[tok.term].append(pos)
            self.term_surface.setdefault(tok.term, tok.raw.lower())
        for term, positions in term_positions.items():
            self.postings.setdefault(term, {})[doc_id] = positions

    def finalize(self):
        self.N = len(self.doc_meta)
        total = sum(self.doc_lengths.values())
        self.avg_doc_length = (total / self.N) if self.N else 0.0

    # -- reading ------------------------------------------------------
    def doc_freq(self, term):
        return len(self.postings.get(term, {}))

    def postings_for(self, term):
        return self.postings.get(term, {})

    def all_doc_ids(self):
        return set(self.doc_meta.keys())

    def vocabulary(self):
        return list(self.postings.keys())

    # -- persistence ----------------------------------------------------
    def save(self, path):
        data = {
            "postings": self.postings,
            "doc_lengths": self.doc_lengths,
            "doc_meta": self.doc_meta,
            "term_surface": self.term_surface,
            "N": self.N,
            "avg_doc_length": self.avg_doc_length,
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        idx = cls()
        idx.postings = data["postings"]
        idx.doc_lengths = data["doc_lengths"]
        idx.doc_meta = data["doc_meta"]
        idx.term_surface = data.get("term_surface", {})
        idx.N = data["N"]
        idx.avg_doc_length = data["avg_doc_length"]
        return idx


def split_markdown_sections(text):
    """Split a markdown file on '## ' headers into (title, body) sections.
    If there are no such headers, the whole file is a single section whose
    title is the first '# ' heading, or None."""
    matches = list(HEADER_SPLIT_RE.finditer(text))
    if not matches:
        first_h1 = re.search(r"^#\s+(.*)$", text, re.MULTILINE)
        title = first_h1.group(1).strip() if first_h1 else None
        return [(title, text)]

    sections = []
    lead = text[: matches[0].start()].strip()
    if lead:
        first_h1 = re.search(r"^#\s+(.*)$", lead, re.MULTILINE)
        sections.append((first_h1.group(1).strip() if first_h1 else None, lead))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(1).strip()
        body = text[start:end]
        sections.append((title, body))
    return sections


DEFAULT_EXTENSIONS = (".md", ".txt")
DEFAULT_EXCLUDE_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv"})


def iter_corpus_files(root, extensions=DEFAULT_EXTENSIONS, exclude_dirs=DEFAULT_EXCLUDE_DIRS):
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for name in filenames:
            if name.lower().endswith(extensions):
                yield os.path.join(dirpath, name)


def build_index(root, extensions=DEFAULT_EXTENSIONS, split_headers=True):
    """Walk `root` for text/markdown files and build an inverted index.

    Markdown files containing '## ' section headers are split so each
    section becomes its own searchable document (e.g. LEDGER.md, which is
    one file holding 30+ distinct project write-ups) — this is a generic
    rule based on document structure, not specific to any one corpus.
    """
    index = InvertedIndex()
    root = os.path.abspath(root)
    for filepath in sorted(iter_corpus_files(root, extensions)):
        rel = os.path.relpath(filepath, root)
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if not text.strip():
            continue

        if split_headers and filepath.lower().endswith(".md"):
            sections = split_markdown_sections(text)
        else:
            sections = [(None, text)]

        multi = len(sections) > 1
        for i, (title, body) in enumerate(sections):
            if not body.strip():
                continue
            doc_id = f"{rel}#{title}" if multi and title else (f"{rel}#{i}" if multi else rel)
            display_title = title or rel
            index.add_document(doc_id, body, path=rel, title=display_title)

    index.finalize()
    return index
