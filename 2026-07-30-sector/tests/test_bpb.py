import unittest

from sector.bpb import (
    BPB, BPBError, compute_fat_size, choose_sectors_per_cluster,
    FAT16_MIN_CLUSTERS, FAT16_MAX_CLUSTERS,
)


def make_bpb(**overrides):
    kw = dict(
        oem_name="SECTOR16", bytes_per_sector=512, sectors_per_cluster=4,
        reserved_sector_count=1, num_fats=2, root_entry_count=512,
        total_sectors=32768, media=0xF8, fat_size=32, sectors_per_track=32,
        num_heads=64, hidden_sectors=0, drive_number=0x80, volume_id=0x12345678,
        volume_label="TESTVOL", fs_type="FAT16   ",
    )
    kw.update(overrides)
    return BPB(**kw)


class TestBPBPackUnpack(unittest.TestCase):
    def test_round_trip(self):
        bpb = make_bpb()
        raw = bpb.pack()
        self.assertEqual(len(raw), 512)
        back = BPB.unpack(raw)
        for field in ("bytes_per_sector", "sectors_per_cluster", "reserved_sector_count",
                      "num_fats", "root_entry_count", "total_sectors", "media", "fat_size",
                      "sectors_per_track", "num_heads", "hidden_sectors", "drive_number",
                      "volume_id"):
            self.assertEqual(getattr(bpb, field), getattr(back, field), field)
        self.assertEqual(back.volume_label, "TESTVOL")
        self.assertEqual(back.fs_type, "FAT16")

    def test_boot_signature_present(self):
        raw = make_bpb().pack()
        self.assertEqual(raw[510], 0x55)
        self.assertEqual(raw[511], 0xAA)

    def test_total_sectors_16_vs_32_split(self):
        small = make_bpb(total_sectors=8192).pack()
        # total_sectors_16 at offset 19-20 should carry it, total_sectors_32 (32-35) zero
        self.assertEqual(int.from_bytes(small[19:21], "little"), 8192)
        self.assertEqual(int.from_bytes(small[32:36], "little"), 0)

        big = make_bpb(total_sectors=200000).pack()
        self.assertEqual(int.from_bytes(big[19:21], "little"), 0)
        self.assertEqual(int.from_bytes(big[32:36], "little"), 200000)

    def test_unpack_rejects_bad_signature(self):
        raw = bytearray(make_bpb().pack())
        raw[510] = 0x00
        with self.assertRaises(BPBError):
            BPB.unpack(bytes(raw))

    def test_unpack_rejects_short_buffer(self):
        with self.assertRaises(BPBError):
            BPB.unpack(b"\x00" * 100)

    def test_unpack_rejects_zero_bytes_per_sector(self):
        raw = bytearray(make_bpb().pack())
        raw[11:13] = (0).to_bytes(2, "little")
        with self.assertRaises(BPBError):
            BPB.unpack(bytes(raw))

    def test_unpack_rejects_non_power_of_two_cluster(self):
        raw = bytearray(make_bpb().pack())
        raw[13] = 3
        with self.assertRaises(BPBError):
            BPB.unpack(bytes(raw))


class TestGeometry(unittest.TestCase):
    def test_root_dir_sectors_rounds_up(self):
        bpb = make_bpb(root_entry_count=1)  # 32 bytes -> 1 sector even though tiny
        self.assertEqual(bpb.root_dir_sectors, 1)
        bpb2 = make_bpb(root_entry_count=17)  # 17*32=544 bytes -> 2 sectors
        self.assertEqual(bpb2.root_dir_sectors, 2)

    def test_region_offsets_are_contiguous(self):
        bpb = make_bpb()
        self.assertEqual(bpb.fat_region_start, bpb.reserved_sector_count)
        self.assertEqual(bpb.root_dir_start, bpb.fat_region_start + bpb.num_fats * bpb.fat_size)
        self.assertEqual(bpb.data_region_start, bpb.root_dir_start + bpb.root_dir_sectors)

    def test_cluster_to_offset(self):
        bpb = make_bpb()
        base = bpb.data_region_start * bpb.bytes_per_sector
        self.assertEqual(bpb.cluster_to_offset(2), base)
        self.assertEqual(bpb.cluster_to_offset(3), base + bpb.cluster_size)

    def test_cluster_to_offset_rejects_reserved_clusters(self):
        bpb = make_bpb()
        with self.assertRaises(ValueError):
            bpb.cluster_to_offset(1)
        with self.assertRaises(ValueError):
            bpb.cluster_to_offset(0)

    def test_validate_is_fat16_boundaries(self):
        bpb = make_bpb()
        n = bpb.count_of_clusters
        self.assertTrue(FAT16_MIN_CLUSTERS <= n < FAT16_MAX_CLUSTERS)
        bpb.validate_is_fat16()  # should not raise


class TestFatSizeMath(unittest.TestCase):
    def test_compute_fat_size_matches_real_mkfs_vfat_4mb_geometry(self):
        # observed from real mkfs.vfat -F16 on a 4 MiB image in this repo's
        # own verification: 1 reserved sector, spc=1, 512 root entries -> 32-sector FATs
        fat_size = compute_fat_size(
            total_sectors=8192, bytes_per_sector=512, sectors_per_cluster=1,
            reserved_sector_count=1, num_fats=2, root_entry_count=512,
        )
        self.assertEqual(fat_size, 32)

    def test_choose_sectors_per_cluster_lands_in_fat16_range(self):
        for total_sectors in (8192, 16384, 32768, 131072):
            spc, fat_size = choose_sectors_per_cluster(
                total_sectors, 512, reserved_sector_count=1, num_fats=2, root_entry_count=512,
            )
            root_dir_sectors = -(-(512 * 32) // 512)
            data_sectors = total_sectors - (1 + 2 * fat_size + root_dir_sectors)
            n_clusters = data_sectors // spc
            self.assertTrue(FAT16_MIN_CLUSTERS <= n_clusters < FAT16_MAX_CLUSTERS,
                             f"total_sectors={total_sectors} spc={spc} -> {n_clusters} clusters")

    def test_choose_sectors_per_cluster_rejects_too_small(self):
        with self.assertRaises(BPBError):
            choose_sectors_per_cluster(100, 512, 1, 2, 512)

    def test_choose_sectors_per_cluster_rejects_too_large(self):
        with self.assertRaises(BPBError):
            choose_sectors_per_cluster(100_000_000, 512, 1, 2, 512)


if __name__ == "__main__":
    unittest.main()
