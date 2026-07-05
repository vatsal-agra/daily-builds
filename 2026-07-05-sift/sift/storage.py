"""A custom on-disk binary index format: a mini Lucene segment file.

Layout:
  magic "SIFT1" (5 bytes)
  doc_count (varint)
  total_length (varint)
  for each doc in id order: path (varint-len utf8), title (varint-len utf8),
    length (varint)
  vocab_size (varint)
  for each term (sorted): term (varint-len utf8), doc_freq (varint),
    then doc_freq postings, each: delta_doc_id (varint), tf (varint),
    num_positions (varint), then delta-encoded positions (varint each,
    first is absolute, rest are deltas from the previous position).

Postings are delta-encoded against the previous doc_id/position the same
way real inverted-index formats compress monotonically increasing ID lists.
"""

import struct

from sift.index import InvertedIndex, Document, Posting

MAGIC = b"SIFT1"


def _write_varint(buf, value):
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            buf.append(byte | 0x80)
        else:
            buf.append(byte)
            return


def _read_varint(data, offset):
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, offset
        shift += 7


def _write_str(buf, s):
    encoded = s.encode("utf-8")
    _write_varint(buf, len(encoded))
    buf.extend(encoded)


def _read_str(data, offset):
    length, offset = _read_varint(data, offset)
    s = data[offset : offset + length].decode("utf-8")
    return s, offset + length


def save_index(index, path):
    buf = bytearray()
    buf.extend(MAGIC)
    _write_varint(buf, index.doc_count)
    _write_varint(buf, index.total_length)

    for doc_id in range(index.doc_count):
        doc = index.documents[doc_id]
        _write_str(buf, doc.path)
        _write_str(buf, doc.title)
        _write_varint(buf, doc.length)

    terms = index.vocabulary()
    _write_varint(buf, len(terms))
    for term in terms:
        bucket = index.postings[term]
        doc_ids = sorted(bucket.keys())
        _write_str(buf, term)
        _write_varint(buf, len(doc_ids))
        prev_doc_id = 0
        for doc_id in doc_ids:
            posting = bucket[doc_id]
            _write_varint(buf, doc_id - prev_doc_id)
            prev_doc_id = doc_id
            _write_varint(buf, posting.tf)
            _write_varint(buf, len(posting.positions))
            prev_pos = 0
            for pos in posting.positions:
                _write_varint(buf, pos - prev_pos)
                prev_pos = pos

    with open(path, "wb") as fh:
        fh.write(bytes(buf))


def load_index(path):
    with open(path, "rb") as fh:
        data = fh.read()

    if data[:5] != MAGIC:
        raise ValueError(f"not a Sift index file (bad magic): {path}")

    offset = 5
    doc_count, offset = _read_varint(data, offset)
    total_length, offset = _read_varint(data, offset)

    index = InvertedIndex()
    index.doc_count = doc_count
    index.total_length = total_length

    for doc_id in range(doc_count):
        path_str, offset = _read_str(data, offset)
        title, offset = _read_str(data, offset)
        length, offset = _read_varint(data, offset)
        index.documents[doc_id] = Document(
            doc_id=doc_id, path=path_str, title=title, length=length
        )

    vocab_size, offset = _read_varint(data, offset)
    for _ in range(vocab_size):
        term, offset = _read_str(data, offset)
        df, offset = _read_varint(data, offset)
        bucket = {}
        doc_id = 0
        for _ in range(df):
            delta_doc_id, offset = _read_varint(data, offset)
            doc_id += delta_doc_id
            tf, offset = _read_varint(data, offset)
            num_positions, offset = _read_varint(data, offset)
            positions = []
            pos = 0
            for _ in range(num_positions):
                delta_pos, offset = _read_varint(data, offset)
                pos += delta_pos
                positions.append(pos)
            bucket[doc_id] = Posting(doc_id=doc_id, tf=tf, positions=positions)
        index.postings[term] = bucket

    return index
