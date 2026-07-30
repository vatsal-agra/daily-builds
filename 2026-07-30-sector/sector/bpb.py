"""FAT16 boot sector / BIOS Parameter Block: pack, unpack, and the
Microsoft-specified geometry math (FAT size, cluster count, FAT12/16/32
boundary check) used both by mkfs and by anyone opening an existing image.

Layout and field names follow Microsoft's "FAT: General Overview of On-Disk
Format" (fatgen103), the document real formatters (mkfs.vfat) and checkers
(fsck.vfat) implement.
"""
import struct

SECTOR_SIZE_DEFAULT = 512
BOOT_SIGNATURE = 0xAA55
EXT_BOOT_SIGNATURE = 0x29

# FAT16 is only valid for cluster counts in this half-open range; below it
# the volume is FAT12, at/above it the volume must be FAT32 instead.
FAT16_MIN_CLUSTERS = 4085
FAT16_MAX_CLUSTERS = 65525

# <3s = jump instruction, <8s = OEM name, then the BPB fields themselves.
_STRUCT = struct.Struct(
    "<3s8s"     # jmp_boot, oem_name
    "H"         # bytes_per_sector
    "B"         # sectors_per_cluster
    "H"         # reserved_sector_count
    "B"         # num_fats
    "H"         # root_entry_count
    "H"         # total_sectors_16
    "B"         # media
    "H"         # fat_size_16
    "H"         # sectors_per_track
    "H"         # num_heads
    "I"         # hidden_sectors
    "I"         # total_sectors_32
    "B"         # drive_number
    "B"         # reserved1
    "B"         # boot_signature
    "I"         # volume_id
    "11s"       # volume_label
    "8s"        # fs_type
)
assert _STRUCT.size == 62


class BPBError(ValueError):
    """The bytes at sector 0 are not a BPB this toolkit understands."""


class BPB:
    """A parsed BIOS Parameter Block plus the geometry derived from it."""

    __slots__ = (
        "oem_name", "bytes_per_sector", "sectors_per_cluster",
        "reserved_sector_count", "num_fats", "root_entry_count",
        "total_sectors", "media", "fat_size", "sectors_per_track",
        "num_heads", "hidden_sectors", "drive_number", "volume_id",
        "volume_label", "fs_type",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw[k])

    # ---- derived geometry ------------------------------------------------

    @property
    def root_dir_sectors(self):
        return -(-(self.root_entry_count * 32) // self.bytes_per_sector)

    @property
    def fat_region_start(self):
        return self.reserved_sector_count

    @property
    def root_dir_start(self):
        return self.fat_region_start + self.num_fats * self.fat_size

    @property
    def root_dir_bytes(self):
        return self.root_entry_count * 32

    @property
    def data_region_start(self):
        return self.root_dir_start + self.root_dir_sectors

    @property
    def data_sectors(self):
        return self.total_sectors - self.data_region_start

    @property
    def count_of_clusters(self):
        return self.data_sectors // self.sectors_per_cluster

    @property
    def cluster_size(self):
        return self.sectors_per_cluster * self.bytes_per_sector

    def cluster_to_offset(self, cluster):
        """Byte offset of the start of a data cluster (cluster numbers start at 2)."""
        if cluster < 2:
            raise ValueError(f"cluster {cluster} is reserved, not a data cluster")
        return (self.data_region_start + (cluster - 2) * self.sectors_per_cluster) * self.bytes_per_sector

    def validate_is_fat16(self):
        n = self.count_of_clusters
        if not (FAT16_MIN_CLUSTERS <= n < FAT16_MAX_CLUSTERS):
            raise BPBError(
                f"{n} data clusters is outside the FAT16 range "
                f"[{FAT16_MIN_CLUSTERS}, {FAT16_MAX_CLUSTERS}); this geometry "
                f"would be FAT12 (too small) or FAT32 (too large), not FAT16"
            )

    # ---- (de)serialization -------------------------------------------------

    def pack(self):
        boot_code = bytearray(448)  # 62 (BPB) + 448 (boot code) + 2 (sig) = 512
        header = _STRUCT.pack(
            b"\xeb\x3c\x90",
            self.oem_name.ljust(8)[:8].encode("ascii"),
            self.bytes_per_sector,
            self.sectors_per_cluster,
            self.reserved_sector_count,
            self.num_fats,
            self.root_entry_count,
            self.total_sectors if self.total_sectors < 0x10000 else 0,
            self.media,
            self.fat_size,
            self.sectors_per_track,
            self.num_heads,
            self.hidden_sectors,
            self.total_sectors if self.total_sectors >= 0x10000 else 0,
            self.drive_number,
            0,
            EXT_BOOT_SIGNATURE,
            self.volume_id,
            self.volume_label.ljust(11)[:11].encode("ascii"),
            self.fs_type.ljust(8)[:8].encode("ascii"),
        )
        sector = bytes(header) + bytes(boot_code)
        sector += struct.pack("<H", BOOT_SIGNATURE)
        assert len(sector) == self.bytes_per_sector or self.bytes_per_sector > 512
        if self.bytes_per_sector > 512:
            sector += bytes(self.bytes_per_sector - 512)
        return sector

    @classmethod
    def unpack(cls, sector_bytes):
        if len(sector_bytes) < 512:
            raise BPBError("boot sector shorter than 512 bytes")
        sig = struct.unpack_from("<H", sector_bytes, 510)[0]
        if sig != BOOT_SIGNATURE:
            raise BPBError(f"missing 0x55AA boot signature (got 0x{sig:04x})")
        fields = _STRUCT.unpack(sector_bytes[:62])
        (jmp, oem, bps, spc, rsc, nfats, rec, ts16, media, fsz16,
         spt, nheads, hidden, ts32, drive, _res1, bootsig, volid,
         vollabel, fstype) = fields
        if bps == 0 or bps % 512 != 0:
            raise BPBError(f"implausible bytes_per_sector={bps}")
        if spc == 0 or (spc & (spc - 1)) != 0:
            raise BPBError(f"sectors_per_cluster must be a power of two, got {spc}")
        total_sectors = ts32 if ts16 == 0 else ts16
        if fsz16 == 0:
            raise BPBError("fat_size_16 is 0 — this looks like a FAT32 BPB, not FAT16")
        return cls(
            oem_name=oem.decode("ascii", "replace").rstrip(),
            bytes_per_sector=bps,
            sectors_per_cluster=spc,
            reserved_sector_count=rsc,
            num_fats=nfats,
            root_entry_count=rec,
            total_sectors=total_sectors,
            media=media,
            fat_size=fsz16,
            sectors_per_track=spt,
            num_heads=nheads,
            hidden_sectors=hidden,
            drive_number=drive,
            volume_id=volid,
            volume_label=vollabel.decode("ascii", "replace").rstrip(),
            fs_type=fstype.decode("ascii", "replace").rstrip(),
        )


def compute_fat_size(total_sectors, bytes_per_sector, sectors_per_cluster,
                      reserved_sector_count, num_fats, root_entry_count):
    """Microsoft's fatgen103 formula for how many sectors one FAT copy needs."""
    root_dir_sectors = -(-(root_entry_count * 32) // bytes_per_sector)
    tmp1 = total_sectors - (reserved_sector_count + root_dir_sectors)
    tmp2 = (256 * sectors_per_cluster) + num_fats
    fat_size = (tmp1 + (tmp2 - 1)) // tmp2
    return fat_size


def choose_sectors_per_cluster(total_sectors, bytes_per_sector,
                                reserved_sector_count, num_fats, root_entry_count):
    """Pick the smallest cluster size that lands the volume in the FAT16
    cluster-count range, mirroring what real formatters do for small volumes."""
    for spc in (1, 2, 4, 8, 16, 32, 64, 128):
        fat_size = compute_fat_size(total_sectors, bytes_per_sector, spc,
                                     reserved_sector_count, num_fats, root_entry_count)
        root_dir_sectors = -(-(root_entry_count * 32) // bytes_per_sector)
        data_sectors = total_sectors - (reserved_sector_count + num_fats * fat_size + root_dir_sectors)
        if data_sectors <= 0:
            continue
        n_clusters = data_sectors // spc
        if FAT16_MIN_CLUSTERS <= n_clusters < FAT16_MAX_CLUSTERS:
            return spc, fat_size
    raise BPBError(
        f"no sectors-per-cluster value (1..128) makes {total_sectors} sectors "
        f"a valid FAT16 volume — image is too small or too large for FAT16"
    )
