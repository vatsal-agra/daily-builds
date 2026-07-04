import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palimpsest.repository import RepoError, Repository, find_repo_root, NotARepository


class TempRepoTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name
        self.repo = Repository.init(self.root)

    def tearDown(self):
        self._tmpdir.cleanup()

    def write(self, path, content):
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True) if os.path.dirname(full) else None
        with open(full, "w") as f:
            f.write(content)

    def read(self, path):
        with open(os.path.join(self.root, path)) as f:
            return f.read()


class TestInit(TempRepoTestCase):
    def test_creates_plm_dir_structure(self):
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".plm", "objects")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".plm", "refs", "heads")))
        self.assertEqual(self.repo.head_ref(), "main")
        self.assertIsNone(self.repo.head_commit())

    def test_double_init_fails(self):
        with self.assertRaises(RepoError):
            Repository.init(self.root)

    def test_find_repo_root_from_subdirectory(self):
        os.makedirs(os.path.join(self.root, "a", "b"))
        found = find_repo_root(os.path.join(self.root, "a", "b"))
        self.assertEqual(os.path.abspath(found), os.path.abspath(self.root))

    def test_find_repo_root_outside_repo_raises(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(NotARepository):
                find_repo_root(other)


class TestAddAndStatus(TempRepoTestCase):
    def test_untracked_file_shows_in_status(self):
        self.write("a.txt", "hello\n")
        st = self.repo.status()
        self.assertIn("a.txt", st["untracked"])
        self.assertFalse(st["clean"])

    def test_add_stages_file(self):
        self.write("a.txt", "hello\n")
        self.repo.add(["a.txt"])
        st = self.repo.status()
        self.assertIn("a.txt", st["staged_added"])
        self.assertNotIn("a.txt", st["untracked"])

    def test_add_directory_recurses(self):
        self.write("dir/a.txt", "a\n")
        self.write("dir/sub/b.txt", "b\n")
        self.repo.add(["dir"])
        st = self.repo.status()
        self.assertIn("dir/a.txt", st["staged_added"])
        self.assertIn("dir/sub/b.txt", st["staged_added"])

    def test_add_nonexistent_path_raises(self):
        with self.assertRaises(RepoError):
            self.repo.add(["nope.txt"])

    def test_clean_after_commit_matches(self):
        self.write("a.txt", "hello\n")
        self.repo.add(["a.txt"])
        self.repo.commit("first", timestamp=1000)
        st = self.repo.status()
        self.assertTrue(st["clean"])

    def test_modified_after_commit_detected(self):
        self.write("a.txt", "hello\n")
        self.repo.add(["a.txt"])
        self.repo.commit("first", timestamp=1000)
        self.write("a.txt", "changed\n")
        st = self.repo.status()
        self.assertIn("a.txt", st["not_staged_modified"])

    def test_staged_modification_after_restage(self):
        self.write("a.txt", "hello\n")
        self.repo.add(["a.txt"])
        self.repo.commit("first", timestamp=1000)
        self.write("a.txt", "changed\n")
        self.repo.add(["a.txt"])
        st = self.repo.status()
        self.assertIn("a.txt", st["staged_modified"])

    def test_deleted_file_detected(self):
        self.write("a.txt", "hello\n")
        self.repo.add(["a.txt"])
        self.repo.commit("first", timestamp=1000)
        os.remove(os.path.join(self.root, "a.txt"))
        st = self.repo.status()
        self.assertIn("a.txt", st["not_staged_deleted"])


class TestCommit(TempRepoTestCase):
    def test_commit_with_no_staged_changes_after_first_fails(self):
        self.write("a.txt", "hello\n")
        self.repo.add(["a.txt"])
        self.repo.commit("first", timestamp=1000)
        with self.assertRaises(RepoError):
            self.repo.commit("second", timestamp=1001)

    def test_commit_updates_branch_ref(self):
        self.write("a.txt", "hello\n")
        self.repo.add(["a.txt"])
        sha = self.repo.commit("first", timestamp=1000)
        self.assertEqual(self.repo.head_commit(), sha)

    def test_commit_chain_has_correct_parent(self):
        self.write("a.txt", "1\n")
        self.repo.add(["a.txt"])
        sha1 = self.repo.commit("first", timestamp=1000)
        self.write("a.txt", "2\n")
        self.repo.add(["a.txt"])
        sha2 = self.repo.commit("second", timestamp=1001)
        c2 = self.repo.objects.read_commit(sha2)
        self.assertEqual(c2.parents, [sha1])

    def test_empty_initial_commit_rejected_like_real_git(self):
        with self.assertRaises(RepoError):
            self.repo.commit("empty initial commit")

    def test_allow_empty_permits_initial_empty_commit(self):
        sha = self.repo.commit("empty ok", allow_empty=True, timestamp=1000)
        self.assertIsNotNone(sha)

    def test_empty_message_rejected(self):
        self.write("a.txt", "x\n")
        self.repo.add(["a.txt"])
        with self.assertRaises(RepoError):
            self.repo.commit("   ")

    def test_nested_directories_produce_correct_tree(self):
        self.write("dir/sub/deep.txt", "deep\n")
        self.write("top.txt", "top\n")
        self.repo.add(["dir", "top.txt"])
        sha = self.repo.commit("nested", timestamp=1000)
        commit = self.repo.objects.read_commit(sha)
        files = self.repo.flatten_tree(commit.tree)
        self.assertEqual(set(files.keys()), {"dir/sub/deep.txt", "top.txt"})


class TestDeletionStaging(TempRepoTestCase):
    def test_add_stages_deletion_of_tracked_file(self):
        self.write("a.txt", "hi\n")
        self.repo.add(["a.txt"])
        self.repo.commit("add a", timestamp=1000)
        os.remove(os.path.join(self.root, "a.txt"))
        staged = self.repo.add(["a.txt"])
        self.assertEqual(staged, ["a.txt"])
        st = self.repo.status()
        self.assertIn("a.txt", st["staged_deleted"])
        sha = self.repo.commit("remove a", timestamp=1001)
        files = self.repo.flatten_tree(self.repo.objects.read_commit(sha).tree)
        self.assertNotIn("a.txt", files)

    def test_add_directory_stages_deletions_within_it(self):
        self.write("dir/a.txt", "a\n")
        self.write("dir/b.txt", "b\n")
        self.repo.add(["dir"])
        self.repo.commit("add dir", timestamp=1000)
        os.remove(os.path.join(self.root, "dir", "a.txt"))
        self.repo.add(["dir"])
        st = self.repo.status()
        self.assertIn("dir/a.txt", st["staged_deleted"])
        self.assertNotIn("dir/b.txt", st["staged_deleted"])

    def test_add_truly_nonexistent_path_still_raises(self):
        with self.assertRaises(RepoError):
            self.repo.add(["never_existed.txt"])


class TestSymlinks(TempRepoTestCase):
    def test_symlink_stores_link_target_not_referent_content(self):
        self.write("a.txt", "real file content\n")
        os.symlink("a.txt", os.path.join(self.root, "link_to_a"))
        self.repo.add(["a.txt", "link_to_a"])
        entries = {e.path: e for e in self.repo.read_index()}
        self.assertNotEqual(entries["a.txt"].sha, entries["link_to_a"].sha)
        self.assertEqual(self.repo.objects.read_blob(entries["link_to_a"].sha), b"a.txt")

    def test_checkout_recreates_symlink(self):
        self.write("a.txt", "content\n")
        os.symlink("a.txt", os.path.join(self.root, "link_to_a"))
        self.repo.add(["a.txt", "link_to_a"])
        self.repo.commit("add symlink", timestamp=1000)
        link_path = os.path.join(self.root, "link_to_a")
        os.remove(link_path)
        self.write("a.txt", "content\n")  # rewrite so working tree is clean
        self.repo.checkout("main", force=True)
        self.assertTrue(os.path.islink(link_path))
        self.assertEqual(os.readlink(link_path), "a.txt")


class TestPathCollisions(TempRepoTestCase):
    def test_file_directory_path_collision_raises_clean_error(self):
        self.write("conf/settings.txt", "x\n")
        self.repo.add(["conf"])
        self.repo.commit("first", timestamp=1000)
        import shutil

        shutil.rmtree(os.path.join(self.root, "conf"))
        self.write("conf", "collision\n")
        self.repo.add(["conf"])
        with self.assertRaises(RepoError):
            self.repo.commit("collide", timestamp=1001)


class TestLog(TempRepoTestCase):
    def test_log_empty_repo(self):
        self.assertEqual(self.repo.log(), [])

    def test_log_walks_first_parent_chain(self):
        shas = []
        for i in range(3):
            self.write("a.txt", str(i))
            self.repo.add(["a.txt"])
            shas.append(self.repo.commit(f"commit {i}", timestamp=1000 + i))
        entries = self.repo.log()
        self.assertEqual([sha for sha, _ in entries], list(reversed(shas)))


class TestBranchAndCheckout(TempRepoTestCase):
    def _commit_file(self, content, msg, ts):
        self.write("a.txt", content)
        self.repo.add(["a.txt"])
        return self.repo.commit(msg, timestamp=ts)

    def test_branch_requires_a_commit(self):
        with self.assertRaises(RepoError):
            self.repo.create_branch("feature")

    def test_branch_and_switch_isolates_history(self):
        c1 = self._commit_file("v1\n", "first", 1000)
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        c2 = self._commit_file("v2\n", "second on feature", 1001)

        self.repo.checkout("main")
        self.assertEqual(self.read("a.txt"), "v1\n")
        self.assertEqual(self.repo.head_commit(), c1)

        self.repo.checkout("feature")
        self.assertEqual(self.read("a.txt"), "v2\n")
        self.assertEqual(self.repo.head_commit(), c2)

    def test_checkout_refuses_with_dirty_working_tree(self):
        self._commit_file("v1\n", "first", 1000)
        self.repo.create_branch("feature")
        self.write("a.txt", "dirty uncommitted change\n")
        with self.assertRaises(RepoError):
            self.repo.checkout("feature")

    def test_checkout_removes_files_not_in_target(self):
        self._commit_file("v1\n", "first", 1000)
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        self.write("only_on_feature.txt", "x\n")
        self.repo.add(["only_on_feature.txt"])
        self.repo.commit("add file", timestamp=1001)

        self.repo.checkout("main")
        self.assertFalse(os.path.exists(os.path.join(self.root, "only_on_feature.txt")))

    def test_checkout_unknown_ref_raises(self):
        self._commit_file("v1\n", "first", 1000)
        with self.assertRaises(RepoError):
            self.repo.checkout("nope")

    def test_detached_checkout_by_sha_prefix(self):
        c1 = self._commit_file("v1\n", "first", 1000)
        self._commit_file("v2\n", "second", 1001)
        self.repo.checkout(c1[:8])
        self.assertEqual(self.read("a.txt"), "v1\n")
        self.assertIsNone(self.repo.head_ref())  # detached


if __name__ == "__main__":
    unittest.main()
