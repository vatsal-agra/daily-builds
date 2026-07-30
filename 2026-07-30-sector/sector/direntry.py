"""Directory entries: the 32-byte 8.3 "short" entry every FAT reader
understands, and Microsoft's VFAT long-file-name (LFN) extension, which
hides a long name inside a run of entries an 8.3-only reader sees as
harmless (attribute 0x0F, which old readers treat as an unrecognized
volume-label-ish entry and skip).
"""
import struct
import datetime

ENTRY_SIZE = 32

ATTR_READ_ONLY = 0x01
ATTR_HIDDEN = 0x02
ATTR_SYSTEM = 0x04
ATTR_VOLUME_ID = 0x08
ATTR_DIRECTORY = 0x10
ATTR_ARCHIVE = 0x20
ATTR_LONG_NAME = ATTR_READ_ONLY | ATTR_HIDDEN | ATTR_SYSTEM | ATTR_VOLUME_ID

DELETED_MARK = 0xE5
END_MARK = 0x00
KANJI_E5_ESCAPE = 0x05  # first byte 0x05 means "the real first char is 0xE5"

VALID_SHORT_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'()-@^_`{}~")

_SHORT_STRUCT = struct.Struct("<8s3sBBBHHHHHHHI")
assert _SHORT_STRUCT.size == 32


class DirEntryError(ValueError):
    pass


# ---------------------------------------------------------------- dates ----

def encode_datetime(dt):
    date = ((max(1980, dt.year) - 1980) & 0x7F) << 9 | (dt.month & 0xF) << 5 | (dt.day & 0x1F)
    time = (dt.hour & 0x1F) << 11 | (dt.minute & 0x3F) << 5 | ((dt.second // 2) & 0x1F)
    return date, time


def decode_datetime(date, time):
    year = 1980 + ((date >> 9) & 0x7F)
    month = (date >> 5) & 0xF
    day = date & 0x1F
    hour = (time >> 11) & 0x1F
    minute = (time >> 5) & 0x3F
    second = (time & 0x1F) * 2
    try:
        return datetime.datetime(year, max(1, month), max(1, day), hour, minute, min(second, 59))
    except ValueError:
        return datetime.datetime(1980, 1, 1)


# ------------------------------------------------------------ short name ---

def _split_base_ext(name):
    if name in (".", ".."):
        return name, ""
    if "." in name.strip("."):
        base, _, ext = name.rpartition(".")
    else:
        base, ext = name, ""
    return base, ext


def _sanitize(s, maxlen):
    out = []
    lossy = len(s) > maxlen
    for ch in s.upper():
        if ch == " ":
            lossy = True
            continue
        if ch in VALID_SHORT_CHARS:
            out.append(ch)
        else:
            out.append("_")
            lossy = True
    return "".join(out)[:maxlen], lossy


def generate_short_name(long_name, existing_pairs):
    """Return (name8, ext3, needs_lfn) — name8/ext3 are space-padded 8 and 3
    char strings ready to encode; needs_lfn is True if `long_name` can't be
    losslessly represented by the short name alone (or collided with one
    that could). `existing_pairs` is the set of (name8, ext3) already used
    in the same directory, used to pick a non-colliding ~N numeric tail."""
    if long_name in (".", ".."):
        return long_name.ljust(8), "   ", False

    base_raw, ext_raw = _split_base_ext(long_name)
    base_san, base_lossy = _sanitize(base_raw, 8)
    ext_san, ext_lossy = _sanitize(ext_raw, 3)
    multi_dot = long_name.strip(".").count(".") > 1
    has_lower = any(c.islower() for c in long_name)
    trimmed_matches = long_name == long_name.strip() and long_name == long_name.rstrip(".")
    exact_fit = (
        not base_lossy and not ext_lossy and not multi_dot and not has_lower
        and trimmed_matches and len(base_raw) <= 8 and len(ext_raw) <= 3
    )
    if not base_san:
        base_san = "_"

    if exact_fit:
        key = (base_san.ljust(8), ext_san.ljust(3))
        if key not in existing_pairs:
            return key[0], key[1], False
    # Needs a numeric tail (either because it never fit, or the exact name collided).
    tail = 1
    while True:
        suffix = f"~{tail}"
        base_trimmed = base_san[: 8 - len(suffix)] + suffix
        key = (base_trimmed.ljust(8), ext_san.ljust(3))
        if key not in existing_pairs:
            return key[0], key[1], True
        tail += 1
        if tail > 9_999_999:
            raise DirEntryError("short-name numeric-tail namespace exhausted in this directory")


def short_name_checksum(name11_bytes):
    csum = 0
    for b in name11_bytes:
        csum = (((csum & 1) << 7) | (csum >> 1)) + b
        csum &= 0xFF
    return csum


def short_display_name(name8, ext3):
    if name8 == ".":
        return "."
    if name8 == "..":
        return ".."
    n = name8.rstrip()
    if n and ord(n[0]) == KANJI_E5_ESCAPE:
        n = chr(DELETED_MARK) + n[1:]
    e = ext3.rstrip()
    return f"{n}.{e}" if e else n


# --------------------------------------------------------- short pack/up ---

def pack_short_entry(name8, ext3, attr, first_cluster, size, ctime=None, wtime=None, ntres=0):
    ctime = ctime or datetime.datetime.now()
    wtime = wtime or ctime
    cdate_v, ctime_v = encode_datetime(ctime)
    wdate_v, wtime_v = encode_datetime(wtime)
    raw_name = name8.encode("ascii")
    if raw_name[0] == DELETED_MARK:
        raw_name = bytes([KANJI_E5_ESCAPE]) + raw_name[1:]
    return _SHORT_STRUCT.pack(
        raw_name, ext3.encode("ascii"), attr, ntres, 0,
        ctime_v, cdate_v, cdate_v,
        (first_cluster >> 16) & 0xFFFF,
        wtime_v, wdate_v,
        first_cluster & 0xFFFF,
        size,
    )


def unpack_short_entry(raw):
    (name, ext, attr, ntres, ctt, ct, cd, lad, clhi, wt, wd, cllo, size) = _SHORT_STRUCT.unpack(raw)
    name_s = name.decode("ascii", "replace")
    ext_s = ext.decode("ascii", "replace")
    first_cluster = (clhi << 16) | cllo
    return {
        "name8": name_s,
        "ext3": ext_s,
        "attr": attr,
        "first_cluster": first_cluster,
        "size": size,
        "ctime": decode_datetime(cd, ct),
        "wtime": decode_datetime(wd, wt),
        "is_dir": bool(attr & ATTR_DIRECTORY),
        "is_volume_id": bool(attr & ATTR_VOLUME_ID) and not (attr & ATTR_DIRECTORY),
    }


# ------------------------------------------------------------- LFN pack ----

def pack_lfn_entries(long_name, checksum):
    """Return the run of 32-byte LFN entries for `long_name`, in the order
    they belong in the directory (highest sequence number first, immediately
    preceding the short entry they describe)."""
    utf16 = long_name.encode("utf-16-le")
    units = [utf16[i:i + 2] for i in range(0, len(utf16), 2)]
    units.append(b"\x00\x00")
    n_entries = -(-len(units) // 13)
    while len(units) < n_entries * 13:
        units.append(b"\xff\xff")

    entries = []
    for i in range(n_entries):
        seq = i + 1
        chunk = units[i * 13:(i + 1) * 13]
        name1 = b"".join(chunk[0:5])
        name2 = b"".join(chunk[5:11])
        name3 = b"".join(chunk[11:13])
        ord_byte = seq | (0x40 if i == n_entries - 1 else 0x00)
        entry = (
            bytes([ord_byte]) + name1
            + bytes([ATTR_LONG_NAME, 0x00, checksum])
            + name2 + b"\x00\x00" + name3
        )
        assert len(entry) == 32
        entries.append(entry)
    entries.reverse()
    return entries


def unpack_lfn_entry(raw):
    ord_byte = raw[0]
    is_last = bool(ord_byte & 0x40)
    seq = ord_byte & 0x1F
    checksum = raw[13]
    chars = raw[1:11] + raw[14:26] + raw[28:32]
    return {"seq": seq, "is_last": is_last, "checksum": checksum, "chars_raw": chars}


def decode_lfn_chars(entries_in_seq_order):
    """entries_in_seq_order: list of unpacked LFN dicts sorted seq=1..n."""
    raw = b"".join(e["chars_raw"] for e in entries_in_seq_order)
    text = raw.decode("utf-16-le", errors="replace")
    nul = text.find("\x00")
    if nul != -1:
        text = text[:nul]
    else:
        text = text.rstrip("￿")
    return text
