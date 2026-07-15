"""Positional inverted index with a real on-disk binary format.

On disk, the source of truth is the per-document token stream (term id +
character span + stopword flag) plus a vocabulary table; postings, document
lengths and averages are all rebuilt from that on load, so `build` -> `load`
is a genuine reconstruction, not a pickle dump.
"""

import struct
from dataclasses import dataclass, field

from . import tokenizer

MAGIC = b"GLN1"


@dataclass
class Document:
    doc_id: int
    title: str
    path: str
    text: str
    tokens: list = field(default_factory=list)   # stemmed terms, in order
    spans: list = field(default_factory=list)     # (start, end) char offsets, parallel to tokens
    stopword_flags: list = field(default_factory=list)  # bool, parallel to tokens

    @property
    def length(self):
        return len(self.tokens)


class IndexError_(Exception):
    pass


class InvertedIndex:
    def __init__(self):
        self.documents = {}          # doc_id -> Document
        self.postings = {}           # term -> {doc_id: [positions]}
        self._next_doc_id = 1
        self._total_length = 0

    @property
    def doc_count(self):
        return len(self.documents)

    @property
    def avg_doc_length(self):
        if not self.documents:
            return 0.0
        return self._total_length / len(self.documents)

    @property
    def vocabulary(self):
        return sorted(self.postings.keys())

    def add_document(self, title, text, path=None):
        """Analyze `title` + `text` together (so titles are searchable too)
        and add the result to the index. Returns the new doc_id."""
        combined = f"{title}. {text}" if title else text
        analyzed = tokenizer.analyze(combined)
        doc_id = self._next_doc_id
        self._next_doc_id += 1
        doc = Document(
            doc_id=doc_id,
            title=title,
            path=path or "",
            text=combined,
            tokens=[t.term for t in analyzed],
            spans=[(t.start, t.end) for t in analyzed],
            stopword_flags=[t.is_stopword for t in analyzed],
        )
        self._ingest(doc)
        return doc_id

    def _ingest(self, doc):
        self.documents[doc.doc_id] = doc
        self._total_length += doc.length
        for position, term in enumerate(doc.tokens):
            bucket = self.postings.setdefault(term, {})
            bucket.setdefault(doc.doc_id, []).append(position)

    def remove_document(self, doc_id):
        doc = self.documents.pop(doc_id, None)
        if doc is None:
            raise KeyError(f"no such document: {doc_id}")
        self._total_length -= doc.length
        for term in set(doc.tokens):
            bucket = self.postings.get(term)
            if bucket is not None:
                bucket.pop(doc_id, None)
                if not bucket:
                    del self.postings[term]

    def phrase_positions(self, doc_id, stems):
        """True if `stems` occur as a contiguous, in-order phrase in doc_id."""
        if not stems:
            return False
        first = self.postings.get(stems[0], {}).get(doc_id)
        if not first:
            return False
        for start in first:
            ok = True
            for offset, term in enumerate(stems[1:], start=1):
                positions = self.postings.get(term, {}).get(doc_id)
                if not positions or (start + offset) not in positions:
                    ok = False
                    break
            if ok:
                return True
        return False

    def min_distance(self, doc_id, term_a, term_b):
        """Smallest |pos_a - pos_b| between any occurrence of term_a and term_b
        in doc_id, or None if either term is absent from the document."""
        pa = self.postings.get(term_a, {}).get(doc_id)
        pb = self.postings.get(term_b, {}).get(doc_id)
        if not pa or not pb:
            return None
        i = j = 0
        best = None
        while i < len(pa) and j < len(pb):
            d = abs(pa[i] - pb[j])
            if best is None or d < best:
                best = d
            if pa[i] < pb[j]:
                i += 1
            else:
                j += 1
        return best

    # ---- persistence ----------------------------------------------------

    def save(self, path):
        with open(path, "wb") as f:
            f.write(MAGIC)
            vocab = self.vocabulary
            term_to_id = {t: i for i, t in enumerate(vocab)}
            f.write(struct.pack(">I", len(vocab)))
            for term in vocab:
                encoded = term.encode("utf-8")
                f.write(struct.pack(">H", len(encoded)))
                f.write(encoded)

            doc_ids = sorted(self.documents.keys())
            f.write(struct.pack(">I", len(doc_ids)))
            for doc_id in doc_ids:
                doc = self.documents[doc_id]
                f.write(struct.pack(">I", doc.doc_id))
                _write_str(f, doc.title)
                _write_str(f, doc.path)
                _write_str(f, doc.text)
                f.write(struct.pack(">I", len(doc.tokens)))
                for term, (start, end), is_stop in zip(doc.tokens, doc.spans, doc.stopword_flags):
                    f.write(struct.pack(">IIIB", term_to_id[term], start, end, 1 if is_stop else 0))

    @classmethod
    def load(cls, path):
        index = cls()
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != MAGIC:
                raise IndexError_(f"not a Glean index file: {path!r}")
            (vocab_size,) = struct.unpack(">I", f.read(4))
            vocab = []
            for _ in range(vocab_size):
                (length,) = struct.unpack(">H", f.read(2))
                vocab.append(f.read(length).decode("utf-8"))

            (num_docs,) = struct.unpack(">I", f.read(4))
            max_doc_id = 0
            for _ in range(num_docs):
                (doc_id,) = struct.unpack(">I", f.read(4))
                title = _read_str(f)
                path_ = _read_str(f)
                text = _read_str(f)
                (num_tokens,) = struct.unpack(">I", f.read(4))
                tokens, spans, flags = [], [], []
                for _t in range(num_tokens):
                    term_id, start, end, is_stop = struct.unpack(">IIIB", f.read(13))
                    tokens.append(vocab[term_id])
                    spans.append((start, end))
                    flags.append(bool(is_stop))
                doc = Document(doc_id, title, path_, text, tokens, spans, flags)
                index._ingest(doc)
                max_doc_id = max(max_doc_id, doc_id)
        index._next_doc_id = max_doc_id + 1
        return index


def _write_str(f, s):
    encoded = s.encode("utf-8")
    f.write(struct.pack(">I", len(encoded)))
    f.write(encoded)


def _read_str(f):
    (length,) = struct.unpack(">I", f.read(4))
    return f.read(length).decode("utf-8")
