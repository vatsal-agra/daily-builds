"""A tiny content-addressed file store built on top of the DHT.

A file is split into fixed-size chunks, each keyed by its own SHA-256 hash
("chunk:<hex>"), and a JSON manifest listing those hashes (plus the whole
file's SHA-256) is itself stored under a key derived from the manifest's
own content ("manifest:<hex>") -- a BitTorrent-magnet-link-style scheme:
whoever wants the file only needs that one manifest key, out of band, and
everything else is discovered through the DHT.

Two independent hashes are at work for two different reasons: the DHT
*key* for each chunk/manifest is `sha1_int()` of its raw key bytes (the
160-bit space the routing table itself is built on), while the *integrity*
check on retrieval is SHA-256 over the actual chunk/file bytes -- a
different, stronger hash, chosen deliberately so "which bucket does this
land in" and "did the bytes I got back match the bytes I put in" are
verified independently rather than reusing one hash for both jobs.

All of this is driven by the same discrete-event callback style as the
rest of the engine: `put_file`/`get_file` chain chunk-by-chunk (`fetch_next`
calls itself from within the previous chunk's completion callback) rather
than issuing them all "concurrently", which keeps the control flow easy to
reason about and keeps a multi-chunk transfer deterministic under the
simulator. For the chunk counts a demo-scale file produces, sequential
transfer costs a few extra lookup rounds of simulated latency -- a real
tradeoff, not a hidden one.
"""
from __future__ import annotations

import hashlib
import json

DEFAULT_CHUNK_SIZE = 4096


def chunk_bytes(data: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[bytes]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not data:
        return []
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


def build_manifest(filename: str, data: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    chunks = chunk_bytes(data, chunk_size)
    return {
        "filename": filename,
        "size": len(data),
        "chunk_size": chunk_size,
        "chunk_hashes": [hashlib.sha256(c).hexdigest() for c in chunks],
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def manifest_raw_key(manifest: dict) -> bytes:
    """The manifest's own content-addressed key: hash the manifest's
    canonical JSON (sorted keys, so the same manifest always hashes the
    same way regardless of dict insertion order)."""
    canonical = json.dumps(manifest, sort_keys=True).encode("utf-8")
    return b"manifest:" + hashlib.sha256(canonical).hexdigest().encode("ascii")


def chunk_raw_key(chunk_hash_hex: str) -> bytes:
    return b"chunk:" + chunk_hash_hex.encode("ascii")


def put_file(node, filename: str, data: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE, ttl=None, on_complete=None):
    """Store `data` under `filename` through `node`. Chunks are stored one
    at a time, then the manifest; `on_complete(manifest_key_bytes,
    manifest, all_chunks_replicated)` fires once everything has been
    attempted. Returns the manifest's raw key bytes immediately (the
    "magnet hash" -- deterministic from content, known before storage
    finishes)."""
    from .dht import DEFAULT_TTL

    ttl = DEFAULT_TTL if ttl is None else ttl
    manifest = build_manifest(filename, data, chunk_size)
    chunks = chunk_bytes(data, chunk_size)
    m_key = manifest_raw_key(manifest)

    def store_next(i: int, all_ok: bool):
        if i >= len(chunks):
            def manifest_done(ok_count, total):
                if on_complete:
                    on_complete(m_key, manifest, all_ok and ok_count > 0)

            node.put(m_key, json.dumps(manifest).encode("utf-8"), ttl=ttl, on_complete=manifest_done)
            return
        raw_key = chunk_raw_key(manifest["chunk_hashes"][i])
        node.put(
            raw_key,
            chunks[i],
            ttl=ttl,
            on_complete=lambda ok_count, total, i=i, all_ok=all_ok: store_next(i + 1, all_ok and ok_count > 0),
        )

    if chunks:
        store_next(0, True)
    else:
        # an empty file still gets a real manifest (zero chunks, sha256 of
        # b"") so retrieval and integrity-checking work uniformly
        node.put(
            m_key,
            json.dumps(manifest).encode("utf-8"),
            ttl=ttl,
            on_complete=lambda ok_count, total: on_complete(m_key, manifest, ok_count > 0) if on_complete else None,
        )
    return m_key


def get_file(node, manifest_key_bytes: bytes, on_complete):
    """Retrieve a file through `node` given a manifest key produced by
    `put_file` (typically on a *different* node than the one that stored
    it). `on_complete(data_or_None, ok, error_or_None, manifest_or_None)`.
    """

    def on_manifest(manifest_json):
        if manifest_json is None:
            on_complete(None, False, "manifest not found in DHT", None)
            return
        try:
            manifest = json.loads(manifest_json)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            on_complete(None, False, f"corrupt manifest: {exc}", None)
            return

        chunk_hashes = manifest.get("chunk_hashes", [])
        if not chunk_hashes:
            data = b""
            if hashlib.sha256(data).hexdigest() != manifest.get("sha256"):
                on_complete(None, False, "empty-file integrity check failed", manifest)
            else:
                on_complete(data, True, None, manifest)
            return

        collected: list[bytes | None] = [None] * len(chunk_hashes)

        def fetch_next(i: int):
            if i >= len(chunk_hashes):
                data = b"".join(collected)  # type: ignore[arg-type]
                actual = hashlib.sha256(data).hexdigest()
                expected = manifest.get("sha256")
                if actual != expected:
                    on_complete(None, False, f"file integrity check failed: expected {expected}, got {actual}", manifest)
                else:
                    on_complete(data, True, None, manifest)
                return
            raw_key = chunk_raw_key(chunk_hashes[i])

            def chunk_cb(value):
                if value is None:
                    on_complete(None, False, f"chunk {i} ({chunk_hashes[i][:12]}...) not found in DHT", manifest)
                    return
                actual = hashlib.sha256(value).hexdigest()
                if actual != chunk_hashes[i]:
                    on_complete(None, False, f"chunk {i} hash mismatch (bit rot or a lying peer)", manifest)
                    return
                collected[i] = value
                fetch_next(i + 1)

            node.get(raw_key, chunk_cb)

        fetch_next(0)

    node.get(manifest_key_bytes, on_manifest)
