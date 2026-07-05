"""In-memory inverted index: term -> postings (doc_id, tf, positions)."""

from dataclasses import dataclass, field

from sift.analyzer import analyze


@dataclass
class Document:
    doc_id: int
    path: str
    title: str
    length: int  # number of indexed (non-stopword) tokens


@dataclass
class Posting:
    doc_id: int
    tf: int
    positions: list = field(default_factory=list)


class InvertedIndex:
    """term -> {doc_id -> Posting}, plus corpus-level statistics needed for
    BM25 (doc_count, avg_doc_length) and document metadata."""

    def __init__(self):
        self.postings = {}  # term -> dict[doc_id, Posting]
        self.documents = {}  # doc_id -> Document
        self.doc_count = 0
        self.total_length = 0

    @property
    def avg_doc_length(self):
        if self.doc_count == 0:
            return 0.0
        return self.total_length / self.doc_count

    def doc_freq(self, term):
        return len(self.postings.get(term, {}))

    def term_freq(self, term, doc_id):
        entry = self.postings.get(term, {}).get(doc_id)
        return entry.tf if entry else 0

    def vocabulary(self):
        return sorted(self.postings.keys())

    def add_document(self, path, title, text):
        doc_id = self.doc_count
        tokens = analyze(text)
        term_positions = {}
        indexed_count = 0
        for tok in tokens:
            if tok.term is None:
                continue
            indexed_count += 1
            term_positions.setdefault(tok.term, []).append(tok.position)

        for term, positions in term_positions.items():
            bucket = self.postings.setdefault(term, {})
            bucket[doc_id] = Posting(doc_id=doc_id, tf=len(positions), positions=positions)

        self.documents[doc_id] = Document(
            doc_id=doc_id, path=path, title=title, length=indexed_count
        )
        self.doc_count += 1
        self.total_length += indexed_count
        return doc_id


def build_index_from_dir(corpus_dir):
    """Build an InvertedIndex from every .txt/.md file in a directory
    (non-recursive), using the first line of each file as its title."""
    import os

    index = InvertedIndex()
    filenames = sorted(
        f for f in os.listdir(corpus_dir) if f.endswith((".txt", ".md"))
    )
    for filename in filenames:
        path = os.path.join(corpus_dir, filename)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        title = filename
        for line in text.splitlines():
            stripped = line.lstrip("#").strip()
            if stripped:
                title = stripped
                break
        index.add_document(path=path, title=title, text=text)
    return index
