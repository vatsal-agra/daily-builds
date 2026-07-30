import os
import unittest

from sector.image import FatImage, needed_clusters
from sector.bpb import BPBError
from sector.fat import FatFullError
from sector.direntry import DirEntryError


def mk(size_mb=4, label="TEST"):
    return FatImage.mkfs(size_mb * 1024 * 1024, volume_label=label)


class TestMkfs(unittest.TestCase):
    def test_basic_geometry(self):
        img = mk()
        info = img.info()
        self.assertEqual(info["volume_label"], "TEST")
        self.assertGreater(info["count_of_clusters"], 4085)
        self.assertEqual(info["free_clusters"], info["count_of_clusters"] - 0)

    def test_root_has_volume_label_entry_but_list_dir_hides_it(self):
        img = mk()
        self.assertEqual(img.list_dir("/"), [])  # volume-id entry is not a "file"

    def test_rejects_non_sector_multiple_size(self):
        with self.assertRaises(ValueError):
            FatImage.mkfs(1000)

    def test_rejects_size_outside_fat16_range(self):
        with self.assertRaises(BPBError):
            FatImage.mkfs(32 * 1024)


class TestFilesAndDirs(unittest.TestCase):
    def test_write_and_read_small_file(self):
        img = mk()
        img.write_file("/hello.txt", b"hello world")
        self.assertEqual(img.read_file("/hello.txt"), b"hello world")

    def test_write_multi_cluster_file(self):
        img = mk()
        data = os.urandom(img.bpb.cluster_size * 5 + 123)
        img.write_file("/big.bin", data)
        self.assertEqual(img.read_file("/big.bin"), data)

    def test_empty_file(self):
        img = mk()
        img.write_file("/empty.txt", b"")
        self.assertEqual(img.read_file("/empty.txt"), b"")
        self.assertEqual(img.stat("/empty.txt")["first_cluster"], 0)

    def test_mkdir_and_nested_file(self):
        img = mk()
        img.mkdir("/sub")
        img.write_file("/sub/f.txt", b"nested")
        self.assertEqual(img.read_file("/sub/f.txt"), b"nested")
        names = {e["display_name"] for e in img.list_dir("/sub")}
        self.assertEqual(names, {"f.txt"})

    def test_dot_and_dotdot_hidden_from_listing(self):
        img = mk()
        img.mkdir("/sub")
        listing = img.list_dir("/sub")
        self.assertEqual(listing, [])

    def test_overwrite_changes_content_and_size(self):
        img = mk()
        img.write_file("/f.txt", b"x" * 5000)
        img.write_file("/f.txt", b"y" * 100)
        self.assertEqual(img.read_file("/f.txt"), b"y" * 100)

    def test_overwrite_leaks_no_clusters(self):
        img = mk()
        free0 = img.fat.count_free()
        for size in (10000, 100, 50000, 0, 20000):
            img.write_file("/churn.bin", os.urandom(size))
        expected = free0 - needed_clusters(20000, img.bpb.cluster_size)
        self.assertEqual(img.fat.count_free(), expected)

    def test_write_into_missing_parent_raises(self):
        img = mk()
        with self.assertRaises(FileNotFoundError):
            img.write_file("/nosuch/f.txt", b"x")

    def test_mkdir_over_existing_name_raises(self):
        img = mk()
        img.mkdir("/a")
        with self.assertRaises(FileExistsError):
            img.mkdir("/a")

    def test_write_file_over_directory_raises(self):
        img = mk()
        img.mkdir("/a")
        with self.assertRaises(IsADirectoryError):
            img.write_file("/a", b"x")

    def test_read_directory_as_file_raises(self):
        img = mk()
        img.mkdir("/a")
        with self.assertRaises(IsADirectoryError):
            img.read_file("/a")

    def test_read_missing_file_raises(self):
        img = mk()
        with self.assertRaises(FileNotFoundError):
            img.read_file("/nope.txt")

    def test_case_insensitive_lookup(self):
        img = mk()
        img.write_file("/File.TXT", b"data")
        self.assertEqual(img.read_file("/file.txt"), b"data")

    def test_double_slash_and_trailing_slash(self):
        img = mk()
        img.mkdir("/sub")
        img.write_file("/sub/f.txt", b"data")
        self.assertEqual(img.read_file("//sub//f.txt"), b"data")
        self.assertEqual(img.list_dir("/sub/"), img.list_dir("/sub"))

    def test_illegal_names_rejected(self):
        img = mk()
        for bad in ["a" * 300, "bad\x01ctrl.txt", " leading.txt", "trailing.txt "]:
            with self.assertRaises(DirEntryError):
                img.write_file(f"/{bad}", b"x")

    def test_deep_nesting(self):
        img = mk(size_mb=8)
        path = ""
        for i in range(15):
            path += f"/l{i}"
            img.mkdir(path)
        img.write_file(path + "/leaf.txt", b"deep")
        self.assertEqual(img.read_file(path + "/leaf.txt"), b"deep")

    def test_subdirectory_grows_past_one_cluster(self):
        img = mk(size_mb=8)
        img.mkdir("/many")
        cs = img.bpb.cluster_size
        n = (cs // 32) + 5
        for i in range(n):
            img.write_file(f"/many/f{i}.txt", str(i).encode())
        entry = [e for e in img.list_dir("/") if e["display_name"] == "many"][0]
        chain = img.fat.chain(entry["short"]["first_cluster"])
        self.assertGreaterEqual(len(chain), 2)
        self.assertEqual(len(img.list_dir("/many")), n)


class TestLongNamesAndCollisions(unittest.TestCase):
    def test_long_name_round_trips(self):
        img = mk()
        name = "a genuinely long descriptive file name.txt"
        img.write_file(f"/{name}", b"data")
        self.assertEqual(img.read_file(f"/{name}"), b"data")
        self.assertIn(name, {e["display_name"] for e in img.list_dir("/")})

    def test_unicode_name_round_trips(self):
        img = mk()
        for name in ["héllo wörld.txt", "日本語ファイル.txt", "emoji 🎉🚀.txt"]:
            img.write_file(f"/{name}", name.encode("utf-8"))
        for name in ["héllo wörld.txt", "日本語ファイル.txt", "emoji 🎉🚀.txt"]:
            self.assertEqual(img.read_file(f"/{name}"), name.encode("utf-8"))

    def test_255_char_name_round_trips(self):
        img = mk()
        name = ("a" * 251) + ".txt"
        self.assertEqual(len(name), 255)
        img.write_file(f"/{name}", b"payload")
        self.assertEqual(img.read_file(f"/{name}"), b"payload")

    def test_many_colliding_names_get_unique_short_names(self):
        img = mk()
        names = [f"identical name {i}.txt" for i in range(12)]
        for i, n in enumerate(names):
            img.write_file(f"/{n}", str(i).encode())
        shorts = {(e["short"]["name8"], e["short"]["ext3"]) for e in img.list_dir("/")}
        self.assertEqual(len(shorts), 12)
        for i, n in enumerate(names):
            self.assertEqual(img.read_file(f"/{n}"), str(i).encode())


class TestUnlink(unittest.TestCase):
    def test_delete_file_frees_clusters(self):
        img = mk()
        img.write_file("/f.bin", os.urandom(img.bpb.cluster_size * 3))
        free_before = img.fat.count_free()
        img.unlink("/f.bin")
        self.assertEqual(img.fat.count_free(), free_before + 3)
        with self.assertRaises(FileNotFoundError):
            img.read_file("/f.bin")

    def test_delete_empty_directory(self):
        img = mk()
        img.mkdir("/d")
        img.unlink("/d")
        self.assertEqual(img.list_dir("/"), [])

    def test_delete_nonempty_directory_raises(self):
        img = mk()
        img.mkdir("/d")
        img.write_file("/d/f.txt", b"x")
        with self.assertRaises(OSError):
            img.unlink("/d")

    def test_delete_missing_raises(self):
        img = mk()
        with self.assertRaises(FileNotFoundError):
            img.unlink("/nope.txt")

    def test_reclaimed_space_is_reused(self):
        img = mk()
        img.write_file("/old.bin", os.urandom(img.bpb.cluster_size * 10))
        img.unlink("/old.bin")
        img.write_file("/new.bin", os.urandom(img.bpb.cluster_size * 10))
        self.assertEqual(len(img.read_file("/new.bin")), img.bpb.cluster_size * 10)


class TestRootDirectoryFull(unittest.TestCase):
    def test_root_full_raises_cleanly_with_no_leak(self):
        img = mk()
        # Uppercase 8.3-fitting names need exactly 1 slot each (no LFN), so
        # 511 of them plus the 1 slot the volume label already used exactly
        # fills the fixed 512-entry root.
        for i in range(511):
            img.write_file(f"/F{i}.TXT", b"x")
        free_before_failed_attempt = img.fat.count_free()
        with self.assertRaises(DirEntryError):
            img.write_file("/ONEMORE.TXT", b"x")
        self.assertEqual(img.fat.count_free(), free_before_failed_attempt,
                          "a failed create must not leak a data cluster")


class TestOverwriteDiskFull(unittest.TestCase):
    def test_failed_overwrite_preserves_original_content(self):
        img = mk()
        original = b"important original content"
        img.write_file("/keep.txt", original)
        free = img.fat.count_free()
        cs = img.bpb.cluster_size
        img.write_file("/filler.bin", os.urandom((free - 2) * cs))
        with self.assertRaises(FatFullError):
            img.write_file("/keep.txt", os.urandom(50 * cs))
        self.assertEqual(img.read_file("/keep.txt"), original)


class TestPersistence(unittest.TestCase):
    def test_save_reopen_round_trip(self, tmp_path="/tmp/sector_test_reopen.img"):
        img = mk()
        img.mkdir("/a")
        img.write_file("/a/b.txt", b"persisted")
        img.save(tmp_path)
        img2 = FatImage.open(tmp_path)
        self.assertEqual(img2.read_file("/a/b.txt"), b"persisted")
        img2.write_file("/a/c.txt", b"second session")
        img2.save(tmp_path)
        img3 = FatImage.open(tmp_path)
        self.assertEqual(img3.read_file("/a/b.txt"), b"persisted")
        self.assertEqual(img3.read_file("/a/c.txt"), b"second session")
        os.remove(tmp_path)

    def test_reopen_free_count_never_exceeds_total(self):
        # regression for the Phase-3 FAT-padding bug
        img = mk()
        img.write_file("/f.txt", b"x" * 5000)
        img.save("/tmp/sector_test_freecount.img")
        img2 = FatImage.open("/tmp/sector_test_freecount.img")
        self.assertLessEqual(img2.fat.count_free(), img2.bpb.count_of_clusters)
        os.remove("/tmp/sector_test_freecount.img")

    def test_open_garbage_bytes_raises(self):
        with self.assertRaises(BPBError):
            FatImage.open(os.urandom(1024))

    def test_open_truncated_bytes_raises(self):
        with self.assertRaises(BPBError):
            FatImage.open(b"tiny")


class TestTreeAndStat(unittest.TestCase):
    def test_tree_structure(self):
        img = mk()
        img.mkdir("/a")
        img.write_file("/a/f.txt", b"x")
        img.write_file("/top.txt", b"y")
        tree = img.tree("/")
        names = {n["name"] for n in tree}
        self.assertEqual(names, {"a", "top.txt"})
        a_node = [n for n in tree if n["name"] == "a"][0]
        self.assertTrue(a_node["is_dir"])
        self.assertEqual({c["name"] for c in a_node["children"]}, {"f.txt"})

    def test_stat_file(self):
        img = mk()
        img.write_file("/f.txt", b"12345")
        st = img.stat("/f.txt")
        self.assertEqual(st["size"], 5)
        self.assertFalse(st["is_dir"])

    def test_stat_root(self):
        img = mk()
        st = img.stat("/")
        self.assertTrue(st["is_dir"])


if __name__ == "__main__":
    unittest.main()
