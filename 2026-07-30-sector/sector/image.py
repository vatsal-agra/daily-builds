"""The high-level FAT16 filesystem image: everything CLI commands (and the
inspector) call through. Owns one in-memory `bytearray` that IS the disk
image byte-for-byte; every operation mutates that array directly at the
exact offsets a real FAT16 driver would, then `save()` just writes it out.
"""
import datetime
import os

from . import bpb as bpb_mod
from .bpb import BPB
from .fat import Fat
from .direntry import (
    ATTR_DIRECTORY, ATTR_ARCHIVE, ATTR_VOLUME_ID, DELETED_MARK,
    generate_short_name, short_name_checksum, pack_lfn_entries,
    unpack_lfn_entry, unpack_short_entry, pack_short_entry, short_display_name,
    decode_lfn_chars, DirEntryError,
)

ILLEGAL_NAME_CHARS = set('\\/:*?"<>|')


def needed_clusters(size, cluster_size):
    if size <= 0:
        return 0
    return -(-size // cluster_size)


class FatImage:
    """A FAT16 volume, held entirely in memory as `self.data`."""

    def __init__(self):
        self.bpb = None
        self.data = None
        self.fat = None

    # ----------------------------------------------------------- create ---

    @classmethod
    def mkfs(cls, size_bytes, volume_label="SECTOR", bytes_per_sector=512,
             oem_name="SECTOR16", volume_id=None):
        if bytes_per_sector not in (512,):
            raise ValueError("only 512-byte sectors are supported")
        if size_bytes % bytes_per_sector != 0:
            raise ValueError(f"image size {size_bytes} is not a multiple of sector size {bytes_per_sector}")
        total_sectors = size_bytes // bytes_per_sector
        reserved = 1
        num_fats = 2
        root_entries = 512
        spc, fat_size = bpb_mod.choose_sectors_per_cluster(
            total_sectors, bytes_per_sector, reserved, num_fats, root_entries)

        volume_id = volume_id if volume_id is not None else int.from_bytes(os.urandom(4), "little")
        bpb = BPB(
            oem_name=oem_name, bytes_per_sector=bytes_per_sector,
            sectors_per_cluster=spc, reserved_sector_count=reserved,
            num_fats=num_fats, root_entry_count=root_entries,
            total_sectors=total_sectors, media=0xF8, fat_size=fat_size,
            sectors_per_track=32, num_heads=64, hidden_sectors=0,
            drive_number=0x80, volume_id=volume_id,
            volume_label=volume_label, fs_type="FAT16   ",
        )
        bpb.validate_is_fat16()

        img = cls()
        img.bpb = bpb
        img.data = bytearray(size_bytes)
        img.data[0:bytes_per_sector] = bpb.pack()
        img.fat = Fat.new(bpb.count_of_clusters, bpb.media)
        img._flush_fat()

        # A volume-label entry (ATTR_VOLUME_ID) in slot 0 of the root
        # directory mirroring the BPB label — real mkfs.vfat writes one, and
        # fsck.vfat treats a labelled BPB with no matching root entry as
        # inconsistent (and silently strips it) without one.
        now = datetime.datetime.now()
        label11 = volume_label.upper().ljust(11)[:11]
        vol_entry = pack_short_entry(label11[:8], label11[8:11], ATTR_VOLUME_ID, 0, 0, ctime=now, wtime=now)
        root_start = bpb.root_dir_start * bpb.bytes_per_sector
        img.data[root_start:root_start + 32] = vol_entry
        return img

    # ------------------------------------------------------------- I/O ----

    @classmethod
    def open(cls, path_or_bytes):
        if isinstance(path_or_bytes, (bytes, bytearray)):
            data = bytearray(path_or_bytes)
        else:
            with open(path_or_bytes, "rb") as f:
                data = bytearray(f.read())
        bpb = BPB.unpack(bytes(data[0:512]))
        img = cls()
        img.bpb = bpb
        img.data = data
        fat_off = bpb.fat_region_start * bpb.bytes_per_sector
        fat_bytes = bytes(data[fat_off:fat_off + bpb.fat_size * bpb.bytes_per_sector])
        img.fat = Fat.from_bytes(fat_bytes, bpb.count_of_clusters)
        return img

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.data)

    def to_bytes(self):
        return bytes(self.data)

    def _flush_fat(self):
        fat_bytes = self.fat.to_bytes(self.bpb.fat_size * self.bpb.bytes_per_sector)
        for i in range(self.bpb.num_fats):
            off = (self.bpb.fat_region_start + i * self.bpb.fat_size) * self.bpb.bytes_per_sector
            self.data[off:off + len(fat_bytes)] = fat_bytes

    # --------------------------------------------------- raw dir regions --

    def _read_dir_raw(self, dir_ref):
        if dir_ref == "ROOT":
            start = self.bpb.root_dir_start * self.bpb.bytes_per_sector
            length = self.bpb.root_dir_bytes
            return bytes(self.data[start:start + length])
        buf = bytearray()
        for c in self.fat.chain(dir_ref):
            off = self.bpb.cluster_to_offset(c)
            buf += self.data[off:off + self.bpb.cluster_size]
        return bytes(buf)

    def _write_dir_raw(self, dir_ref, raw):
        if dir_ref == "ROOT":
            start = self.bpb.root_dir_start * self.bpb.bytes_per_sector
            length = self.bpb.root_dir_bytes
            if len(raw) != length:
                raise AssertionError("root directory region size changed")
            self.data[start:start + length] = raw
            return
        chain = self.fat.chain(dir_ref)
        expected = len(chain) * self.bpb.cluster_size
        if len(raw) != expected:
            raise AssertionError("subdirectory raw size does not match its cluster chain")
        for i, c in enumerate(chain):
            off = self.bpb.cluster_to_offset(c)
            self.data[off:off + self.bpb.cluster_size] = raw[i * self.bpb.cluster_size:(i + 1) * self.bpb.cluster_size]

    # ------------------------------------------------------ dir parsing ---

    def _parse_dir_entries(self, raw):
        n = len(raw) // 32
        entries = []
        pending = []  # list of (slot_index, unpacked_lfn_dict), encounter order
        idx = 0
        while idx < n:
            slot = raw[idx * 32:(idx + 1) * 32]
            first = slot[0]
            if first == 0x00:
                break
            if first == DELETED_MARK:
                pending = []
                idx += 1
                continue
            attr = slot[11]
            if attr == 0x0F:
                pending.append((idx, unpack_lfn_entry(slot)))
                idx += 1
                continue
            short = unpack_short_entry(slot)
            long_name = None
            start_slot = idx
            if pending:
                ordered = sorted(pending, key=lambda t: t[1]["seq"])
                seqs = [e["seq"] for _, e in ordered]
                csum = short_name_checksum(slot[0:11])
                contiguous = pending[-1][0] == idx - 1 and (idx - pending[0][0]) == len(pending)
                valid = (
                    contiguous
                    and seqs == list(range(1, len(seqs) + 1))
                    and ordered[-1][1]["is_last"]
                    and all(e["checksum"] == csum for _, e in pending)
                )
                if valid:
                    long_name = decode_lfn_chars([e for _, e in ordered])
                    start_slot = pending[0][0]
            pending = []
            if short["is_volume_id"]:
                idx += 1
                continue
            entries.append({
                "short": short,
                "long_name": long_name,
                "display_name": long_name or short_display_name(short["name8"], short["ext3"]),
                "start_slot": start_slot,
                "end_slot": idx,
            })
            idx += 1
        return entries

    @staticmethod
    def _find_free_run(raw, k):
        n = len(raw) // 32
        run_start, run_len = None, 0
        for i in range(n):
            b = raw[i * 32]
            if b == 0x00:
                if i + k <= n:
                    return i
                return None
            if b == DELETED_MARK:
                if run_start is None:
                    run_start = i
                run_len += 1
                if run_len == k:
                    return run_start
            else:
                run_start, run_len = None, 0
        return None

    def _alloc_slots(self, dir_ref, k):
        raw = bytearray(self._read_dir_raw(dir_ref))
        pos = self._find_free_run(raw, k)
        if pos is not None:
            return raw, pos
        if dir_ref == "ROOT":
            raise DirEntryError(
                f"root directory is full ({self.bpb.root_entry_count} entries max) — "
                f"cannot add {k} more slots"
            )
        needed_bytes = k * 32
        n_new = -(-needed_bytes // self.bpb.cluster_size)
        self.fat.extend(dir_ref, n_new)
        self._flush_fat()
        raw = raw + bytearray(n_new * self.bpb.cluster_size)
        pos = self._find_free_run(raw, k)
        if pos is None:
            raise DirEntryError("internal error: directory growth failed to yield free slots")
        return raw, pos

    # ------------------------------------------------------ path lookup ---

    @staticmethod
    def _split_components(path):
        return [p for p in path.strip("/").split("/") if p not in ("", ".")]

    def _find_in_dir(self, dir_ref, name):
        name_l = name.lower()
        for e in self._parse_dir_entries(self._read_dir_raw(dir_ref)):
            if e["display_name"].lower() == name_l:
                return e
        return None

    def _resolve_dir_ref(self, path):
        dir_ref = "ROOT"
        for name in self._split_components(path):
            entry = self._find_in_dir(dir_ref, name)
            if entry is None:
                raise FileNotFoundError(path)
            if not entry["short"]["is_dir"]:
                raise NotADirectoryError(f"{name!r} in {path!r} is not a directory")
            c = entry["short"]["first_cluster"]
            dir_ref = "ROOT" if c == 0 else c
        return dir_ref

    def _split_path(self, path):
        parts = self._split_components(path)
        if not parts:
            raise ValueError("path must name a file or directory, not the root")
        parent = self._resolve_dir_ref("/".join(parts[:-1]))
        return parent, parts[-1]

    @staticmethod
    def _validate_name(name):
        if not name or name in (".", ".."):
            raise DirEntryError(f"invalid name: {name!r}")
        if len(name) > 255:
            raise DirEntryError("name longer than 255 characters")
        for ch in name:
            if ord(ch) < 0x20 or ch in ILLEGAL_NAME_CHARS:
                raise DirEntryError(f"illegal character {ch!r} in name {name!r}")
        if name != name.strip():
            raise DirEntryError(f"name may not have leading/trailing whitespace: {name!r}")

    # --------------------------------------------------------- creation ---

    def _create_entry(self, parent_ref, name, attr, data, is_dir, now=None):
        self._validate_name(name)
        if self._find_in_dir(parent_ref, name) is not None:
            raise FileExistsError(name)
        now = now or datetime.datetime.now()

        existing_pairs = {
            (e["short"]["name8"], e["short"]["ext3"])
            for e in self._parse_dir_entries(self._read_dir_raw(parent_ref))
        }
        name8, ext3, needs_lfn = generate_short_name(name, existing_pairs)
        lfn_entries = []
        if needs_lfn:
            csum = short_name_checksum((name8 + ext3).encode("ascii"))
            lfn_entries = pack_lfn_entries(name, csum)

        # Reserve the directory slot(s) *before* allocating any data/subdir
        # cluster. If the parent directory has no room (the fixed-size root,
        # in particular, cannot grow), this raises before a single data
        # cluster is touched — otherwise a failed root-full write would leak
        # an allocated-but-unreferenced cluster that only `fsck` would catch.
        raw, pos = self._alloc_slots(parent_ref, len(lfn_entries) + 1)

        first_cluster = 0
        size = 0
        if is_dir:
            first_cluster = self.fat.allocate(1)[0]
            self._flush_fat()
            self._init_dir_cluster(first_cluster, parent_ref, now)
        elif data:
            size = len(data)
            n_clusters = needed_clusters(size, self.bpb.cluster_size)
            first_cluster = self.fat.allocate(n_clusters)[0]
            self._flush_fat()
            self._write_cluster_chain(first_cluster, data)

        short_bytes = pack_short_entry(name8, ext3, attr, first_cluster, size, ctime=now, wtime=now)
        for i, e in enumerate(lfn_entries):
            raw[(pos + i) * 32:(pos + i + 1) * 32] = e
        raw[(pos + len(lfn_entries)) * 32:(pos + len(lfn_entries) + 1) * 32] = short_bytes
        self._write_dir_raw(parent_ref, bytes(raw))

    def _init_dir_cluster(self, cluster, parent_ref, now):
        buf = bytearray(self.bpb.cluster_size)
        parent_cluster = 0 if parent_ref == "ROOT" else parent_ref
        buf[0:32] = pack_short_entry(".".ljust(8), "   ", ATTR_DIRECTORY, cluster, 0, ctime=now, wtime=now)
        buf[32:64] = pack_short_entry("..".ljust(8), "   ", ATTR_DIRECTORY, parent_cluster, 0, ctime=now, wtime=now)
        off = self.bpb.cluster_to_offset(cluster)
        self.data[off:off + self.bpb.cluster_size] = buf

    def _write_cluster_chain(self, first_cluster, data):
        cs = self.bpb.cluster_size
        chain = self.fat.chain(first_cluster)
        for i, c in enumerate(chain):
            off = self.bpb.cluster_to_offset(c)
            chunk = data[i * cs:(i + 1) * cs]
            if len(chunk) < cs:
                chunk = chunk + bytes(cs - len(chunk))
            self.data[off:off + cs] = chunk

    # ------------------------------------------------------------- API ----

    def mkdir(self, path):
        parent_ref, name = self._split_path(path)
        self._create_entry(parent_ref, name, ATTR_DIRECTORY, None, is_dir=True)

    def write_file(self, path, data, now=None):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes")
        parent_ref, name = self._split_path(path)
        existing = self._find_in_dir(parent_ref, name)
        now = now or datetime.datetime.now()
        if existing is not None:
            if existing["short"]["is_dir"]:
                raise IsADirectoryError(path)
            # Allocate (and write) the *new* chain before freeing the old
            # one: if allocate() raises (disk full), the old chain — and
            # the directory entry that still points at it — is untouched,
            # so the file keeps its previous contents instead of losing
            # them to a failed overwrite.
            old_first_cluster = existing["short"]["first_cluster"]
            first_cluster = 0
            if data:
                n_clusters = needed_clusters(len(data), self.bpb.cluster_size)
                first_cluster = self.fat.allocate(n_clusters)[0]
                self._write_cluster_chain(first_cluster, data)
            self.fat.free_chain(old_first_cluster)
            self._flush_fat()
            raw = bytearray(self._read_dir_raw(parent_ref))
            slot = pack_short_entry(
                existing["short"]["name8"], existing["short"]["ext3"], existing["short"]["attr"],
                first_cluster, len(data), ctime=existing["short"]["ctime"], wtime=now,
            )
            raw[existing["end_slot"] * 32:(existing["end_slot"] + 1) * 32] = slot
            self._write_dir_raw(parent_ref, bytes(raw))
            return
        self._create_entry(parent_ref, name, ATTR_ARCHIVE, bytes(data), is_dir=False, now=now)

    def read_file(self, path):
        parent_ref, name = self._split_path(path)
        entry = self._find_in_dir(parent_ref, name)
        if entry is None:
            raise FileNotFoundError(path)
        if entry["short"]["is_dir"]:
            raise IsADirectoryError(path)
        size = entry["short"]["size"]
        first_cluster = entry["short"]["first_cluster"]
        if size == 0 or first_cluster == 0:
            return b""
        cs = self.bpb.cluster_size
        buf = bytearray()
        for c in self.fat.chain(first_cluster):
            off = self.bpb.cluster_to_offset(c)
            buf += self.data[off:off + cs]
        return bytes(buf[:size])

    def unlink(self, path):
        """Delete a file, or an empty directory, freeing its whole cluster
        chain back to the FAT and marking its directory slot(s) deleted."""
        parent_ref, name = self._split_path(path)
        entry = self._find_in_dir(parent_ref, name)
        if entry is None:
            raise FileNotFoundError(path)
        s = entry["short"]
        if s["is_dir"]:
            sub_ref = "ROOT" if s["first_cluster"] == 0 else s["first_cluster"]
            children = [
                e for e in self._parse_dir_entries(self._read_dir_raw(sub_ref))
                if e["short"]["name8"].rstrip() not in (".", "..")
            ]
            if children:
                raise OSError(f"directory not empty: {path}")
        if s["first_cluster"]:
            self.fat.free_chain(s["first_cluster"])
            self._flush_fat()
        raw = bytearray(self._read_dir_raw(parent_ref))
        for slot in range(entry["start_slot"], entry["end_slot"] + 1):
            raw[slot * 32] = DELETED_MARK
        self._write_dir_raw(parent_ref, bytes(raw))

    def cluster_owners(self):
        """Map every currently-allocated data cluster number to the path of
        the file/directory that owns it — used by the HTML inspector's
        allocation map."""
        owners = {}

        def walk(dir_ref, prefix):
            for e in self._parse_dir_entries(self._read_dir_raw(dir_ref)):
                sn = e["short"]["name8"].rstrip()
                if sn in (".", ".."):
                    continue
                s = e["short"]
                full = prefix + "/" + e["display_name"]
                if s["first_cluster"]:
                    try:
                        chain = self.fat.chain(s["first_cluster"])
                    except ValueError:
                        chain = []
                    for c in chain:
                        owners[c] = full
                    if s["is_dir"]:
                        child_ref = "ROOT" if s["first_cluster"] == 0 else s["first_cluster"]
                        walk(child_ref, full)

        walk("ROOT", "")
        return owners

    def list_dir(self, path="/"):
        parts = self._split_components(path)
        dir_ref = self._resolve_dir_ref(path) if parts else "ROOT"
        out = []
        for e in self._parse_dir_entries(self._read_dir_raw(dir_ref)):
            sn = e["short"]["name8"].rstrip()
            if sn in (".", ".."):
                continue
            out.append(e)
        return out

    def stat(self, path):
        parts = self._split_components(path)
        if not parts:
            return {
                "name": "/", "is_dir": True, "size": 0,
                "first_cluster": 0, "ctime": None, "wtime": None,
            }
        parent_ref, name = self._split_path(path)
        entry = self._find_in_dir(parent_ref, name)
        if entry is None:
            raise FileNotFoundError(path)
        s = entry["short"]
        return {
            "name": entry["display_name"], "is_dir": s["is_dir"], "size": s["size"],
            "first_cluster": s["first_cluster"], "ctime": s["ctime"], "wtime": s["wtime"],
            "short_name": short_display_name(s["name8"], s["ext3"]),
        }

    def tree(self, path="/"):
        parts = self._split_components(path)
        dir_ref = self._resolve_dir_ref(path) if parts else "ROOT"
        return self._tree_recurse(dir_ref)

    def _tree_recurse(self, dir_ref):
        out = []
        for e in self._parse_dir_entries(self._read_dir_raw(dir_ref)):
            sn = e["short"]["name8"].rstrip()
            if sn in (".", ".."):
                continue
            s = e["short"]
            node = {"name": e["display_name"], "is_dir": s["is_dir"], "size": s["size"],
                    "first_cluster": s["first_cluster"]}
            if s["is_dir"]:
                child_ref = "ROOT" if s["first_cluster"] == 0 else s["first_cluster"]
                node["children"] = self._tree_recurse(child_ref)
            out.append(node)
        return out

    def info(self):
        b = self.bpb
        return {
            "volume_label": b.volume_label,
            "bytes_per_sector": b.bytes_per_sector,
            "sectors_per_cluster": b.sectors_per_cluster,
            "cluster_size": b.cluster_size,
            "total_sectors": b.total_sectors,
            "total_bytes": b.total_sectors * b.bytes_per_sector,
            "reserved_sectors": b.reserved_sector_count,
            "num_fats": b.num_fats,
            "fat_size_sectors": b.fat_size,
            "root_entry_count": b.root_entry_count,
            "root_dir_start_sector": b.root_dir_start,
            "data_region_start_sector": b.data_region_start,
            "count_of_clusters": b.count_of_clusters,
            "free_clusters": self.fat.count_free(),
            "free_bytes": self.fat.count_free() * b.cluster_size,
            "media": b.media,
            "volume_id": b.volume_id,
        }
