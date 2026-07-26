"""Persistent inverted index: term -> postings (doc id, term freq, positions).

Two-stage build:
  1. "forward" analysis per document (cached by mtime, so unchanged files are
     never re-read or re-tokenized on incremental reindex).
  2. "inversion" of the forward index into a term dictionary (terms.json) plus
     a compact binary postings file (postings.bin) using varint-encoded,
     delta-compressed doc ids and positions -- the same shape real inverted
     indices (Lucene, etc.) use on disk.
"""
import json
import os

from .analyzer import analyze

INDEX_DIRNAME = ".glean"
DOCS_FILE = "docs.json"
FORWARD_FILE = "forward.json"
TERMS_FILE = "terms.json"
POSTINGS_FILE = "postings.bin"


def _write_varint(out, n):
    if n < 0:
        raise ValueError(f"varint cannot encode negative value: {n}")
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return


def _read_varint(buf, offset):
    result = 0
    shift = 0
    while True:
        byte = buf[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, offset
        shift += 7


class Index:
    """A loaded, queryable index. Postings are decoded lazily, per term."""

    def __init__(self, index_dir):
        self.index_dir = index_dir
        docs_path = os.path.join(index_dir, DOCS_FILE)
        terms_path = os.path.join(index_dir, TERMS_FILE)
        postings_path = os.path.join(index_dir, POSTINGS_FILE)
        if not os.path.isfile(docs_path):
            raise FileNotFoundError(
                f"no index found at {index_dir!r} -- run `glean index <dir>` first"
            )
        with open(docs_path, "r", encoding="utf-8") as f:
            doc_data = json.load(f)
        self.docs = {int(k): v for k, v in doc_data["docs"].items()}
        self.root = doc_data.get("root", "")
        with open(terms_path, "r", encoding="utf-8") as f:
            self.terms = json.load(f)  # term -> {"offset", "length", "df"}
        with open(postings_path, "rb") as f:
            self._postings_blob = f.read()

        self.doc_count = len(self.docs)
        self.avg_doc_length = (
            sum(d["length"] for d in self.docs.values()) / self.doc_count
            if self.doc_count
            else 0.0
        )

    def vocabulary(self):
        return list(self.terms.keys())

    def document_frequency(self, term):
        entry = self.terms.get(term)
        return entry["df"] if entry else 0

    def postings(self, term):
        """Return [(doc_id, term_freq, [positions...]), ...] for a term."""
        entry = self.terms.get(term)
        if entry is None:
            return []
        offset, length = entry["offset"], entry["length"]
        buf = self._postings_blob
        end = offset + length
        pos = offset
        result = []
        doc_id = 0
        while pos < end:
            delta_doc, pos = _read_varint(buf, pos)
            doc_id += delta_doc
            tf, pos = _read_varint(buf, pos)
            positions = []
            token_pos = 0
            for _ in range(tf):
                delta_pos, pos = _read_varint(buf, pos)
                token_pos += delta_pos
                positions.append(token_pos)
            result.append((doc_id, tf, positions))
        return result

    def doc(self, doc_id):
        return self.docs.get(doc_id)


class IndexWriter:
    """Crawls a directory, analyzes documents, and builds/updates an index."""

    def __init__(self, root, index_dir=None, extensions=(".md", ".txt")):
        self.root = os.path.abspath(root)
        self.index_dir = index_dir or os.path.join(self.root, INDEX_DIRNAME)
        self.extensions = tuple(extensions)

    def build(self, crawl_results):
        """crawl_results: iterable of (relpath, text, mtime). Returns stats dict."""
        os.makedirs(self.index_dir, exist_ok=True)
        forward_path = os.path.join(self.index_dir, FORWARD_FILE)
        docs_path = os.path.join(self.index_dir, DOCS_FILE)

        old_forward = {}
        old_docs = {}
        old_path_to_id = {}
        if os.path.isfile(forward_path) and os.path.isfile(docs_path):
            with open(forward_path, "r", encoding="utf-8") as f:
                old_forward = json.load(f)
            with open(docs_path, "r", encoding="utf-8") as f:
                doc_data = json.load(f)
                old_docs = doc_data.get("docs", {})
                old_path_to_id = doc_data.get("path_to_id", {})

        new_forward = {}
        new_docs = {}
        new_path_to_id = {}
        next_id = 0
        stats = {"reused": 0, "reanalyzed": 0, "removed": 0, "total": 0}
        seen_paths = set()

        for relpath, text, mtime in crawl_results:
            seen_paths.add(relpath)
            existing_id = old_path_to_id.get(relpath)
            doc_id = next_id
            next_id += 1
            if (
                existing_id is not None
                and str(existing_id) in old_docs
                and old_docs[str(existing_id)]["mtime"] == mtime
                and str(existing_id) in old_forward
            ):
                entry = old_forward[str(existing_id)]
                doc_meta = old_docs[str(existing_id)]
                new_forward[str(doc_id)] = entry
                new_docs[str(doc_id)] = {**doc_meta, "path": relpath}
                stats["reused"] += 1
            else:
                terms = analyze(text)
                title = _extract_title(text, relpath)
                length = len(terms)
                new_forward[str(doc_id)] = terms
                new_docs[str(doc_id)] = {
                    "path": relpath,
                    "title": title,
                    "length": length,
                    "mtime": mtime,
                }
                stats["reanalyzed"] += 1
            new_path_to_id[relpath] = doc_id

        stats["removed"] = len(old_path_to_id) - len(
            set(old_path_to_id) & seen_paths
        )
        stats["total"] = len(new_docs)

        with open(forward_path, "w", encoding="utf-8") as f:
            json.dump(new_forward, f)
        with open(docs_path, "w", encoding="utf-8") as f:
            json.dump(
                {"root": self.root, "docs": new_docs, "path_to_id": new_path_to_id},
                f,
            )

        self._invert(new_forward)
        return stats

    def _invert(self, forward):
        """Build term dictionary + binary postings from the forward index."""
        term_postings = {}  # term -> list of (doc_id, [positions])
        for doc_id_str, term_list in forward.items():
            doc_id = int(doc_id_str)
            per_doc = {}
            for term, pos, _raw in term_list:
                per_doc.setdefault(term, []).append(pos)
            for term, positions in per_doc.items():
                term_postings.setdefault(term, []).append((doc_id, sorted(positions)))

        blob = bytearray()
        terms_meta = {}
        for term in sorted(term_postings):
            entries = sorted(term_postings[term], key=lambda e: e[0])
            offset = len(blob)
            prev_doc = 0
            for doc_id, positions in entries:
                _write_varint(blob, doc_id - prev_doc)
                prev_doc = doc_id
                _write_varint(blob, len(positions))
                prev_pos = 0
                for p in positions:
                    _write_varint(blob, p - prev_pos)
                    prev_pos = p
            terms_meta[term] = {
                "offset": offset,
                "length": len(blob) - offset,
                "df": len(entries),
            }

        with open(os.path.join(self.index_dir, TERMS_FILE), "w", encoding="utf-8") as f:
            json.dump(terms_meta, f)
        with open(os.path.join(self.index_dir, POSTINGS_FILE), "wb") as f:
            f.write(bytes(blob))


def _extract_title(text, fallback):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
        if stripped:
            return stripped[:80]
    return fallback
