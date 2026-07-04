"""Custom pack-file format: loose objects -> one pack + copy/insert delta
compression against a same-type anchor object, with an independent
round-trip verification pass before any loose object is deleted.

Layout (`objects/pack/pack-<id>.pack`):
    b"GRFTPACK" + version:u32be + count:u32be
    per entry: sha1(20) + type_code(1) + is_delta(1) [+ base_sha1(20)]
               + payload_len:u32be + zlib(payload)
`objects/pack/pack-<id>.idx` is a side text index: "<sha1_hex> <offset>\n".
"""
import hashlib
import os
import struct
import zlib

from . import objecthash

MAGIC = b"GRFTPACK"
TYPE_CODES = {"blob": 0, "tree": 1, "commit": 2}
TYPE_NAMES = {v: k for k, v in TYPE_CODES.items()}


def _pack_dir(gitdir):
    return os.path.join(gitdir, "objects", "pack")


# --------------------------------------------------------- delta encoding --

def _write_varint(out, n):
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def _read_varint(data, pos):
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _encode_delta_ops(ops):
    out = bytearray()
    for op in ops:
        if op[0] == "copy":
            out.append(1)
            _write_varint(out, op[1])
            _write_varint(out, op[2])
        else:
            out.append(2)
            _write_varint(out, len(op[1]))
            out += op[1]
    return bytes(out)


def _decode_delta_ops(data):
    ops = []
    pos = 0
    n = len(data)
    while pos < n:
        code = data[pos]
        pos += 1
        if code == 1:
            off, pos = _read_varint(data, pos)
            length, pos = _read_varint(data, pos)
            ops.append(("copy", off, length))
        else:
            length, pos = _read_varint(data, pos)
            ops.append(("insert", bytes(data[pos:pos + length])))
            pos += length
    return ops


def make_delta(base, target, chunk=16, min_match=16):
    """Greedy hash-chain copy/insert delta of `target` against `base`."""
    index = {}
    for i in range(0, max(0, len(base) - chunk + 1)):
        index.setdefault(base[i:i + chunk], []).append(i)

    ops = []
    literal = bytearray()
    i, n = 0, len(target)
    while i < n:
        candidates = index.get(target[i:i + chunk]) if i + chunk <= n else None
        best_len, best_off = 0, None
        if candidates:
            for off in candidates:
                length = chunk
                while (
                    off + length < len(base)
                    and i + length < n
                    and base[off + length] == target[i + length]
                ):
                    length += 1
                if length > best_len:
                    best_len, best_off = length, off
        if best_off is not None and best_len >= min_match:
            if literal:
                ops.append(("insert", bytes(literal)))
                literal = bytearray()
            ops.append(("copy", best_off, best_len))
            i += best_len
        else:
            literal.append(target[i])
            i += 1
    if literal:
        ops.append(("insert", bytes(literal)))
    return ops


def apply_delta(base, ops):
    out = bytearray()
    for op in ops:
        if op[0] == "copy":
            _, off, length = op
            out += base[off:off + length]
        else:
            out += op[1]
    return bytes(out)


# ------------------------------------------------------------------ pack --

def _iter_loose_objects(objects_dir):
    for sub in sorted(os.listdir(objects_dir)):
        if sub == "pack":
            continue
        subdir = os.path.join(objects_dir, sub)
        if not os.path.isdir(subdir):
            continue
        for fname in sorted(os.listdir(subdir)):
            yield sub + fname, os.path.join(subdir, fname)


def pack_repository(repo):
    objects_dir = repo.objects_dir
    loose = []
    for sha1, path in _iter_loose_objects(objects_dir):
        obj_type, content = repo.read_object(sha1)
        loose.append((sha1, obj_type, content, path))

    if not loose:
        return {"object_count": 0, "loose_bytes": 0, "pack_bytes": 0, "ratio": 1.0}

    loose_bytes = sum(os.path.getsize(p) for _, _, _, p in loose)

    by_type = {}
    for sha1, obj_type, content, _ in loose:
        by_type.setdefault(obj_type, []).append((sha1, content))

    entries = []  # (sha1, obj_type, is_delta, base_sha1_or_None, payload_bytes)
    for obj_type, items in by_type.items():
        items.sort(key=lambda it: -len(it[1]))
        anchor_sha, anchor_content = items[0]
        entries.append((anchor_sha, obj_type, False, None, anchor_content))
        for sha1, content in items[1:]:
            ops = make_delta(anchor_content, content)
            encoded = _encode_delta_ops(ops)
            if len(encoded) < len(content):
                entries.append((sha1, obj_type, True, anchor_sha, encoded))
            else:
                entries.append((sha1, obj_type, False, None, content))

    pack_dir = _pack_dir(repo.gitdir)
    os.makedirs(pack_dir, exist_ok=True)
    name_seed = "".join(sorted(e[0] for e in entries)).encode()
    pack_id = hashlib.sha1(name_seed).hexdigest()
    pack_path = os.path.join(pack_dir, f"pack-{pack_id}.pack")
    idx_path = os.path.join(pack_dir, f"pack-{pack_id}.idx")

    idx_lines = []
    with open(pack_path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack(">II", 1, len(entries)))
        for sha1, obj_type, is_delta, base_sha1, payload in entries:
            offset = f.tell()
            idx_lines.append(f"{sha1} {offset}")
            f.write(bytes.fromhex(sha1))
            f.write(bytes([TYPE_CODES[obj_type]]))
            f.write(bytes([1 if is_delta else 0]))
            if is_delta:
                f.write(bytes.fromhex(base_sha1))
            compressed = zlib.compress(payload, level=6)
            f.write(struct.pack(">I", len(compressed)))
            f.write(compressed)
    with open(idx_path, "w") as f:
        f.write("\n".join(idx_lines) + "\n")

    # Verify every packed object round-trips before touching loose storage.
    for sha1, obj_type, content, _ in loose:
        hit = find_object(repo.gitdir, sha1)
        if hit is None or hit != (obj_type, content):
            os.remove(pack_path)
            os.remove(idx_path)
            raise objecthash.ObjectError(f"pack round-trip verification failed for {sha1}")

    for _, _, _, path in loose:
        os.remove(path)
    for sub in list(os.listdir(objects_dir)):
        subdir = os.path.join(objects_dir, sub)
        if sub != "pack" and os.path.isdir(subdir) and not os.listdir(subdir):
            os.rmdir(subdir)

    pack_bytes = os.path.getsize(pack_path) + os.path.getsize(idx_path)
    ratio = loose_bytes / pack_bytes if pack_bytes else 1.0
    return {
        "object_count": len(entries),
        "loose_bytes": loose_bytes,
        "pack_bytes": pack_bytes,
        "ratio": ratio,
    }


# -------------------------------------------------------------- read side --

def _iter_idx_files(gitdir):
    pack_dir = _pack_dir(gitdir)
    if not os.path.isdir(pack_dir):
        return
    for fname in sorted(os.listdir(pack_dir)):
        if fname.endswith(".idx"):
            pack_path = os.path.join(pack_dir, fname[:-4] + ".pack")
            yield pack_path, os.path.join(pack_dir, fname)


def _load_idx(idx_path):
    mapping = {}
    with open(idx_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sha1, offset = line.split(" ")
            mapping[sha1] = int(offset)
    return mapping


def _read_entry_at(pack_path, offset):
    with open(pack_path, "rb") as f:
        f.seek(offset)
        f.read(20)  # sha1, already known by caller
        type_code = f.read(1)[0]
        is_delta = f.read(1)[0] == 1
        base_sha1 = f.read(20).hex() if is_delta else None
        (plen,) = struct.unpack(">I", f.read(4))
        compressed = f.read(plen)
    payload = zlib.decompress(compressed)
    return TYPE_NAMES[type_code], is_delta, base_sha1, payload


def find_object(gitdir, sha1):
    for pack_path, idx_path in _iter_idx_files(gitdir):
        mapping = _load_idx(idx_path)
        if sha1 not in mapping:
            continue
        obj_type, is_delta, base_sha1, payload = _read_entry_at(pack_path, mapping[sha1])
        if not is_delta:
            return obj_type, payload
        base_type, base_is_delta, _, base_payload = _read_entry_at(pack_path, mapping[base_sha1])
        assert not base_is_delta, "delta chains are not supported (anchors are always raw)"
        ops = _decode_delta_ops(payload)
        return obj_type, apply_delta(base_payload, ops)
    return None


def matching_prefixes(gitdir, prefix):
    result = set()
    for _, idx_path in _iter_idx_files(gitdir):
        for sha1 in _load_idx(idx_path):
            if sha1.startswith(prefix):
                result.add(sha1)
    return result
