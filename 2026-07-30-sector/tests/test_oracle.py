"""Cross-checks against three independent, real FAT tools installed on this
box: fsck.vfat (structural validator), mkfs.vfat (format), and mtools
(mdir/mcopy/mtype -- read/write FAT images without root or a loopback
mount). These are the strongest verification this project has: not "does
our own code agree with itself" but "does a real production FAT
implementation accept what we wrote, and does our reader correctly
understand what a real production implementation wrote."
"""
import os
import shutil
import subprocess
import tempfile
import unittest

from sector.image import FatImage

HAVE_FSCK = shutil.which("fsck.vfat") is not None
HAVE_MKFS = shutil.which("mkfs.vfat") is not None
HAVE_MTOOLS = shutil.which("mcopy") is not None


def fsck_clean(path):
    r = subprocess.run(["fsck.vfat", "-n", path], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


@unittest.skipUnless(HAVE_FSCK, "fsck.vfat not installed")
class TestFsckOracle(unittest.TestCase):
    def _check(self, img):
        path = tempfile.mktemp(suffix=".img")
        img.save(path)
        try:
            ok, output = fsck_clean(path)
            self.assertTrue(ok, f"fsck.vfat rejected our image:\n{output}")
        finally:
            os.remove(path)

    def test_fresh_mkfs_is_clean(self):
        self._check(FatImage.mkfs(4 * 1024 * 1024, volume_label="ORACLE1"))

    def test_files_and_dirs_stay_clean(self):
        img = FatImage.mkfs(4 * 1024 * 1024, volume_label="ORACLE2")
        img.mkdir("/docs")
        img.write_file("/docs/hello.txt", b"hello from sector")
        img.write_file("/docs/a very long filename that needs vfat.txt", b"lfn payload")
        img.write_file("/big.bin", os.urandom(3 * 1024 * 1024 + 777))
        self._check(img)

    def test_after_delete_is_clean_and_no_lost_clusters(self):
        img = FatImage.mkfs(4 * 1024 * 1024, volume_label="ORACLE3")
        img.write_file("/keep.txt", b"keep me")
        img.write_file("/gone.bin", os.urandom(50_000))
        img.unlink("/gone.bin")
        path = tempfile.mktemp(suffix=".img")
        img.save(path)
        try:
            r = subprocess.run(["fsck.vfat", "-v", "-n", path], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("Reclaimed", r.stdout, "fsck found an orphaned cluster our unlink() should have freed")
        finally:
            os.remove(path)


@unittest.skipUnless(HAVE_MTOOLS, "mtools not installed")
class TestMtoolsOracle(unittest.TestCase):
    """mtools reads/writes our images: proves our writer produced something
    a real, independent FAT implementation understands."""

    def setUp(self):
        self.img = FatImage.mkfs(4 * 1024 * 1024, volume_label="MTOOLSRT")
        self.img.mkdir("/docs")
        self.img.write_file("/docs/hello.txt", b"hello from sector")
        self.path = tempfile.mktemp(suffix=".img")
        self.img.save(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_mdir_lists_our_files(self):
        r = subprocess.run(["mdir", "-i", self.path, "::docs"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("HELLO", r.stdout)

    def test_mtype_reads_our_file_content(self):
        r = subprocess.run(["mtype", "-i", self.path, "::docs/hello.txt"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "hello from sector")

    def test_mcopy_extracts_a_large_file_byte_identical(self):
        data = os.urandom(2_500_003)
        self.img.write_file("/big.bin", data)
        self.img.save(self.path)
        out = tempfile.mktemp()
        try:
            r = subprocess.run(["mcopy", "-i", self.path, "::big.bin", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), data)
        finally:
            if os.path.exists(out):
                os.remove(out)


@unittest.skipUnless(HAVE_MKFS and HAVE_MTOOLS, "mkfs.vfat/mtools not installed")
class TestReaderAgainstRealWriter(unittest.TestCase):
    """The acid test for the 'from-scratch reader' required feature: build a
    volume using ONLY real mkfs.vfat + mtools (sector's writer never
    touches it), then confirm sector's own reader gets every byte right."""

    def setUp(self):
        self.path = tempfile.mktemp(suffix=".img")
        with open(self.path, "wb") as f:
            f.truncate(16 * 1024 * 1024)
        subprocess.run(["mkfs.vfat", "-F16", "-n", "ORACLE", self.path],
                        check=True, capture_output=True)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_reads_nested_dirs_and_long_names_from_a_real_volume(self):
        subprocess.run(["mmd", "-i", self.path, "::photos"], check=True, capture_output=True)
        subprocess.run(["mmd", "-i", self.path, "::photos/summer vacation 2026"], check=True, capture_output=True)
        src = tempfile.mktemp()
        with open(src, "w") as f:
            f.write("made entirely by real mkfs.vfat + mtools")
        try:
            subprocess.run(
                ["mcopy", "-i", self.path, src, "::photos/summer vacation 2026/a genuinely long file name.txt"],
                check=True, capture_output=True,
            )
        finally:
            os.remove(src)

        img = FatImage.open(self.path)
        tree = img.tree("/")
        photos = [n for n in tree if n["name"].lower() == "photos"][0]
        self.assertTrue(photos["is_dir"])
        vacation = [n for n in photos["children"] if "vacation" in n["name"].lower()][0]
        long_named = vacation["children"][0]
        self.assertIn("genuinely long file name", long_named["name"])
        content = img.read_file(
            "/photos/summer vacation 2026/a genuinely long file name.txt"
        )
        self.assertEqual(content, b"made entirely by real mkfs.vfat + mtools")

    def test_reads_a_large_file_written_by_real_mcopy_byte_identical(self):
        data = os.urandom(2_500_003)
        src = tempfile.mktemp()
        with open(src, "wb") as f:
            f.write(data)
        try:
            subprocess.run(["mcopy", "-i", self.path, src, "::big.bin"], check=True, capture_output=True)
        finally:
            os.remove(src)
        img = FatImage.open(self.path)
        self.assertEqual(img.read_file("/big.bin"), data)


if __name__ == "__main__":
    unittest.main()
