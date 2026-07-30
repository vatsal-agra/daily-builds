import datetime
import unittest

from sector.direntry import (
    generate_short_name, short_name_checksum, pack_lfn_entries, unpack_lfn_entry,
    decode_lfn_chars, pack_short_entry, unpack_short_entry, short_display_name,
    encode_datetime, decode_datetime, ATTR_ARCHIVE, ATTR_DIRECTORY, DELETED_MARK,
    KANJI_E5_ESCAPE,
)


class TestShortNameGeneration(unittest.TestCase):
    def test_fits_losslessly_no_lfn(self):
        name8, ext3, needs_lfn = generate_short_name("README.TXT", set())
        self.assertEqual((name8, ext3), ("README  ", "TXT"))
        self.assertFalse(needs_lfn)

    def test_lowercase_forces_lfn(self):
        name8, ext3, needs_lfn = generate_short_name("readme.txt", set())
        self.assertTrue(needs_lfn)
        self.assertTrue(name8.startswith("README"))

    def test_long_base_gets_tilde_one(self):
        name8, ext3, needs_lfn = generate_short_name("a very long file name.txt", set())
        self.assertTrue(needs_lfn)
        self.assertTrue(name8.rstrip().endswith("~1"))
        self.assertEqual(ext3, "TXT")

    def test_collision_increments_tail(self):
        existing = set()
        n1 = generate_short_name("report.txt", existing)
        existing.add((n1[0], n1[1]))
        n2 = generate_short_name("report x.txt", existing)  # sanitizes to same REPORT base
        self.assertNotEqual((n1[0], n1[1]), (n2[0], n2[1]))

    def test_illegal_characters_replaced(self):
        name8, ext3, needs_lfn = generate_short_name("bad*name?.txt", set())
        self.assertTrue(needs_lfn)
        self.assertNotIn("*", name8)
        self.assertNotIn("?", name8)

    def test_dot_and_dotdot_are_special(self):
        self.assertEqual(generate_short_name(".", set()), (".".ljust(8), "   ", False))
        self.assertEqual(generate_short_name("..", set()), ("..".ljust(8), "   ", False))

    def test_multi_dot_forces_lfn(self):
        name8, ext3, needs_lfn = generate_short_name("archive.tar.gz", set())
        self.assertTrue(needs_lfn)

    def test_tail_shrinks_base_at_double_digits(self):
        existing = {("AAAAAA~1".ljust(8)[:8], "TXT") for _ in range(0)}
        # simulate 9 prior collisions so the 10th needs a 2-digit tail
        pairs = set()
        base = "identical name"
        for i in range(11):
            n8, e3, _ = generate_short_name(f"{base} {i}.txt", pairs)
            pairs.add((n8, e3))
        self.assertEqual(len(pairs), 11, "11 distinct long names must yield 11 distinct short names")


class TestChecksum(unittest.TestCase):
    def test_checksum_is_deterministic_and_8bit(self):
        v = short_name_checksum(b"README  TXT")
        self.assertTrue(0 <= v <= 255)
        self.assertEqual(v, short_name_checksum(b"README  TXT"))

    def test_checksum_differs_for_different_names(self):
        self.assertNotEqual(short_name_checksum(b"README  TXT"), short_name_checksum(b"OTHER   TXT"))


class TestLFN(unittest.TestCase):
    def test_round_trip_short_name(self):
        name = "hello.txt"
        entries = pack_lfn_entries(name, checksum=0x42)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0][0] & 0x40, "single LFN entry must carry the 'last' flag")
        unpacked = [unpack_lfn_entry(e) for e in entries]
        ordered = sorted(unpacked, key=lambda e: e["seq"])
        self.assertEqual(decode_lfn_chars(ordered), name)

    def test_round_trip_long_name_spanning_multiple_entries(self):
        name = "a" * 40 + ".txt"  # needs ceil(44/13) = 4 LFN entries
        entries = pack_lfn_entries(name, checksum=0x01)
        self.assertEqual(len(entries), 4)
        # directory order is highest-seq first
        seqs = [unpack_lfn_entry(e)["seq"] & 0x1F for e in entries]
        self.assertEqual(seqs, [4, 3, 2, 1])
        unpacked = [unpack_lfn_entry(e) for e in entries]
        ordered = sorted(unpacked, key=lambda e: e["seq"])
        self.assertEqual(decode_lfn_chars(ordered), name)

    def test_round_trip_unicode(self):
        name = "日本語 🎉.txt"
        entries = pack_lfn_entries(name, checksum=0x7F)
        unpacked = sorted([unpack_lfn_entry(e) for e in entries], key=lambda e: e["seq"])
        self.assertEqual(decode_lfn_chars(unpacked), name)

    def test_all_checksums_match(self):
        entries = pack_lfn_entries("multi entry long name here.txt", checksum=0x99)
        for e in entries:
            self.assertEqual(unpack_lfn_entry(e)["checksum"], 0x99)


class TestShortEntryPackUnpack(unittest.TestCase):
    def test_round_trip(self):
        now = datetime.datetime(2026, 7, 30, 14, 22, 10)
        raw = pack_short_entry("HELLO   ", "TXT", ATTR_ARCHIVE, first_cluster=5, size=1234, ctime=now, wtime=now)
        self.assertEqual(len(raw), 32)
        parsed = unpack_short_entry(raw)
        self.assertEqual(parsed["name8"], "HELLO   ")
        self.assertEqual(parsed["ext3"], "TXT")
        self.assertEqual(parsed["first_cluster"], 5)
        self.assertEqual(parsed["size"], 1234)
        self.assertFalse(parsed["is_dir"])

    def test_large_cluster_number_uses_high_word(self):
        raw = pack_short_entry("BIG     ", "BIN", ATTR_ARCHIVE, first_cluster=0x1_2345, size=0)
        parsed = unpack_short_entry(raw)
        self.assertEqual(parsed["first_cluster"], 0x1_2345)

    def test_directory_attribute_roundtrips(self):
        raw = pack_short_entry("DIR     ", "   ", ATTR_DIRECTORY, first_cluster=9, size=0)
        parsed = unpack_short_entry(raw)
        self.assertTrue(parsed["is_dir"])

    def test_kanji_e5_escape_on_read(self):
        # A real-world foreign image can legally contain a short name whose
        # first character is escaped as 0x05 (meaning "the real first
        # character is byte 0xE5", which would otherwise be mistaken for a
        # deleted-entry marker). This toolkit's own writer can never
        # produce that byte (see pack_short_entry), but the *reader* must
        # still decode a foreign image's use of it correctly.
        name8 = chr(KANJI_E5_ESCAPE) + "EST    "
        self.assertEqual(short_display_name(name8, "TXT")[0], chr(DELETED_MARK))


class TestDisplayName(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(short_display_name("README  ", "TXT"), "README.TXT")

    def test_no_extension(self):
        self.assertEqual(short_display_name("NOEXT   ", "   "), "NOEXT")

    def test_dot_entries(self):
        self.assertEqual(short_display_name(".".ljust(8), "   "), ".")
        self.assertEqual(short_display_name("..".ljust(8), "   "), "..")


class TestDateTime(unittest.TestCase):
    def test_round_trip(self):
        dt = datetime.datetime(2026, 7, 30, 13, 45, 32)
        date_v, time_v = encode_datetime(dt)
        back = decode_datetime(date_v, time_v)
        self.assertEqual((back.year, back.month, back.day, back.hour, back.minute), (2026, 7, 30, 13, 45))
        self.assertEqual(back.second, 32)  # FAT time has 2-second resolution but 32 is even

    def test_odd_seconds_truncate_to_even(self):
        dt = datetime.datetime(2026, 1, 1, 0, 0, 33)
        date_v, time_v = encode_datetime(dt)
        back = decode_datetime(date_v, time_v)
        self.assertEqual(back.second, 32)

    def test_invalid_date_falls_back_gracefully(self):
        back = decode_datetime(0, 0)  # month=0, day=0 -- not a real calendar date
        self.assertEqual(back, datetime.datetime(1980, 1, 1))


if __name__ == "__main__":
    unittest.main()
