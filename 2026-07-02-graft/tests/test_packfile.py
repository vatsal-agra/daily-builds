import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graft import packfile
from graft.repository import Repository


class TestDelta(unittest.TestCase):
    def test_roundtrip_similar_content(self):
        base = b"the quick brown fox jumps over the lazy dog " * 20
        target = base.replace(b"quick", b"slow").replace(b"lazy", b"sleepy")
        ops = packfile.make_delta(base, target)
        self.assertEqual(packfile.apply_delta(base, ops), target)

    def test_roundtrip_empty_target(self):
        ops = packfile.make_delta(b"some base content", b"")
        self.assertEqual(packfile.apply_delta(b"some base content", ops), b"")

    def test_roundtrip_completely_different(self):
        base = os.urandom(500)
        target = os.urandom(500)
        ops = packfile.make_delta(base, target)
        self.assertEqual(packfile.apply_delta(base, ops), target)

    def test_fuzz_roundtrip(self):
        rng = random.Random(5)
        alphabet = b"abcdefgh"
        for _ in range(200):
            base = bytes(rng.choice(alphabet) for _ in range(rng.randint(0, 200)))
            target = bytes(rng.choice(alphabet) for _ in range(rng.randint(0, 200)))
            ops = packfile.make_delta(base, target)
            self.assertEqual(packfile.apply_delta(base, ops), target)


class TestPackRepository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = Repository.init(self.tmp)

    def test_gc_empty_repo_is_noop(self):
        stats = packfile.pack_repository(self.repo)
        self.assertEqual(stats["object_count"], 0)

    def test_gc_roundtrips_and_removes_loose(self):
        shas = []
        for i in range(10):
            content = f"object number {i} with some shared boilerplate text repeated".encode()
            shas.append(self.repo.write_object("blob", content))
        loose_paths = [
            __import__("graft.objecthash", fromlist=["object_path"]).object_path(
                self.repo.objects_dir, s
            )
            for s in shas
        ]
        self.assertTrue(all(os.path.exists(p) for p in loose_paths))

        stats = packfile.pack_repository(self.repo)
        self.assertEqual(stats["object_count"], 10)
        self.assertTrue(all(not os.path.exists(p) for p in loose_paths))

        for i, sha in enumerate(shas):
            obj_type, content = self.repo.read_object_any(sha)
            self.assertEqual(obj_type, "blob")
            self.assertEqual(
                content,
                f"object number {i} with some shared boilerplate text repeated".encode(),
            )

    def test_gc_twice_is_idempotent(self):
        self.repo.write_object("blob", b"content one")
        packfile.pack_repository(self.repo)
        stats = packfile.pack_repository(self.repo)
        self.assertEqual(stats["object_count"], 0)

    def test_prefix_resolution_after_gc(self):
        sha = self.repo.write_object("blob", b"unique content for prefix test")
        packfile.pack_repository(self.repo)
        matches = packfile.matching_prefixes(self.repo.gitdir, sha[:8])
        self.assertEqual(matches, {sha})


if __name__ == "__main__":
    unittest.main()
