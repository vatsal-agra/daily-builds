import os
import shutil
import tempfile
import unittest

from strata.repository import (
    DirtyWorktree, MergeConflict, NotARepository, Repository, RepositoryError,
)


def write(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


class RepoTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = Repository.init(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)


class TestInitAndDiscover(RepoTestCase):
    def test_init_creates_structure(self):
        self.assertTrue(os.path.isdir(self.p(".strata", "objects")))
        self.assertTrue(os.path.isdir(self.p(".strata", "refs", "heads")))
        self.assertTrue(os.path.isfile(self.p(".strata", "HEAD")))

    def test_double_init_rejected(self):
        with self.assertRaises(RepositoryError):
            Repository.init(self.tmp)

    def test_discover_from_subdirectory(self):
        os.makedirs(self.p("a", "b"))
        found = Repository.discover(self.p("a", "b"))
        self.assertEqual(found.root, self.repo.root)

    def test_discover_outside_repo_fails(self):
        outside = tempfile.mkdtemp()
        try:
            with self.assertRaises(NotARepository):
                Repository.discover(outside)
        finally:
            shutil.rmtree(outside, ignore_errors=True)


class TestAddCommitLog(RepoTestCase):
    def test_add_and_commit_end_to_end(self):
        write(self.p("a.txt"), "hello\n")
        result = self.repo.add(["a.txt"])
        self.assertEqual(result["staged"], ["a.txt"])
        commit_id = self.repo.commit("Initial commit")
        self.assertEqual(len(commit_id), 64)
        log = self.repo.log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0][1].message, "Initial commit\n")

    def test_commit_content_survives_reread(self):
        write(self.p("a.txt"), "hello world\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        files = self.repo._flatten_tree(self.repo._head_tree_id())
        blob_hash = files["a.txt"][0]
        self.assertEqual(self.repo.store.read(blob_hash)[1], b"hello world\n")

    def test_add_directory_recursively(self):
        write(self.p("src", "a.py"), "a")
        write(self.p("src", "lib", "b.py"), "b")
        result = self.repo.add(["src"])
        self.assertEqual(set(result["staged"]), {"src/a.py", "src/lib/b.py"})

    def test_empty_commit_message_rejected(self):
        write(self.p("a.txt"), "x")
        self.repo.add(["a.txt"])
        with self.assertRaises(RepositoryError):
            self.repo.commit("")
        with self.assertRaises(RepositoryError):
            self.repo.commit("   ")

    def test_noop_commit_rejected(self):
        write(self.p("a.txt"), "x")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        with self.assertRaises(RepositoryError):
            self.repo.commit("c2")  # nothing changed since parent

    def test_add_nonexistent_path_rejected(self):
        with self.assertRaises(RepositoryError):
            self.repo.add(["does-not-exist.txt"])

    def test_add_path_outside_repo_rejected(self):
        outside = os.path.join(self.tmp, "..", "outside.txt")
        with open(outside, "w") as fh:
            fh.write("secret")
        try:
            with self.assertRaises(RepositoryError):
                self.repo.add([outside])
        finally:
            os.remove(outside)

    def test_deletion_can_be_staged_and_committed(self):
        write(self.p("f.txt"), "content")
        self.repo.add(["f.txt"])
        self.repo.commit("add f")
        os.remove(self.p("f.txt"))
        result = self.repo.add(["f.txt"])
        self.assertEqual(result["removed"], ["f.txt"])
        commit_id = self.repo.commit("remove f")
        files = self.repo._flatten_tree(self.repo.get_commit(commit_id).tree)
        self.assertNotIn("f.txt", files)

    def test_merge_commit_message_defaults_and_config_author(self):
        self.repo.set_config("user.name", "Ada")
        self.repo.set_config("user.email", "ada@example.com")
        write(self.p("a.txt"), "x")
        self.repo.add(["a.txt"])
        cid = self.repo.commit("c1")
        self.assertEqual(self.repo.get_commit(cid).author, "Ada <ada@example.com>")


class TestStatus(RepoTestCase):
    def test_untracked_shows_up(self):
        write(self.p("a.txt"), "x")
        st = self.repo.status()
        self.assertEqual(st["untracked"], ["a.txt"])

    def test_staged_added(self):
        write(self.p("a.txt"), "x")
        self.repo.add(["a.txt"])
        st = self.repo.status()
        self.assertEqual(st["staged_added"], ["a.txt"])
        self.assertEqual(st["untracked"], [])

    def test_unstaged_modified_after_commit(self):
        write(self.p("a.txt"), "x")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        write(self.p("a.txt"), "y")
        st = self.repo.status()
        self.assertEqual(st["unstaged_modified"], ["a.txt"])

    def test_unstaged_deleted(self):
        write(self.p("a.txt"), "x")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        os.remove(self.p("a.txt"))
        st = self.repo.status()
        self.assertEqual(st["unstaged_deleted"], ["a.txt"])

    def test_clean_after_commit(self):
        write(self.p("a.txt"), "x")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        self.assertTrue(self.repo.is_clean())


class TestBranchAndCheckout(RepoTestCase):
    def _commit(self, name, content):
        write(self.p(name), content)
        self.repo.add([name])
        return self.repo.commit(f"add {name}")

    def test_branch_and_checkout_roundtrip(self):
        self._commit("a.txt", "one\n")
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        self.assertEqual(self.repo.current_branch(), "feature")
        write(self.p("a.txt"), "one\ntwo\n")
        self.repo.add(["a.txt"])
        self.repo.commit("edit")
        self.repo.checkout("main")
        with open(self.p("a.txt")) as fh:
            self.assertEqual(fh.read(), "one\n")
        self.repo.checkout("feature")
        with open(self.p("a.txt")) as fh:
            self.assertEqual(fh.read(), "one\ntwo\n")

    def test_branch_invalid_name_rejected(self):
        self._commit("a.txt", "x")
        with self.assertRaises(RepositoryError):
            self.repo.create_branch("../../evil")
        # must not have escaped the repo
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "..", "evil")))

    def test_duplicate_branch_rejected(self):
        self._commit("a.txt", "x")
        self.repo.create_branch("dup")
        with self.assertRaises(RepositoryError):
            self.repo.create_branch("dup")

    def test_checkout_unknown_ref_rejected(self):
        self._commit("a.txt", "x")
        with self.assertRaises(RepositoryError):
            self.repo.checkout("nope")

    def test_checkout_refuses_to_clobber_dirty_tracked_file(self):
        self._commit("a.txt", "one\n")
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        write(self.p("a.txt"), "changed on feature\n")
        self.repo.add(["a.txt"])
        self.repo.commit("edit")
        self.repo.checkout("main")
        write(self.p("a.txt"), "uncommitted local edit\n")
        with self.assertRaises(DirtyWorktree):
            self.repo.checkout("feature")

    def test_checkout_refuses_to_clobber_untracked_file(self):
        self._commit("a.txt", "one\n")
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        write(self.p("newfile.txt"), "feature version\n")
        self.repo.add(["newfile.txt"])
        self.repo.commit("add newfile")
        self.repo.checkout("main")
        write(self.p("newfile.txt"), "my uncommitted untracked content\n")
        with self.assertRaises(DirtyWorktree):
            self.repo.checkout("feature")
        with open(self.p("newfile.txt")) as fh:
            self.assertEqual(fh.read(), "my uncommitted untracked content\n")

    def test_checkout_prunes_empty_directories(self):
        write(self.p("a", "b", "c", "f.txt"), "deep")
        self.repo.add(["a"])
        self.repo.commit("deep file")
        self.repo.create_branch("nofile")
        self.repo.checkout("nofile")
        os.remove(self.p("a", "b", "c", "f.txt"))
        self.repo.add(["a/b/c/f.txt"])
        self.repo.commit("remove deep file")
        self.repo.checkout("main")
        self.assertTrue(os.path.isfile(self.p("a", "b", "c", "f.txt")))
        self.repo.checkout("nofile")
        self.assertFalse(os.path.exists(self.p("a")))

    def test_detached_head_checkout(self):
        cid = self._commit("a.txt", "x")
        self.repo.checkout(cid)
        self.assertIsNone(self.repo.current_branch())
        with self.assertRaises(RepositoryError):
            self.repo.merge("main")  # cannot merge while detached


class TestDiff(RepoTestCase):
    def test_diff_worktree(self):
        write(self.p("a.txt"), "one\ntwo\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        write(self.p("a.txt"), "one\nTWO\n")
        out = "".join(self.repo.diff_worktree())
        self.assertIn("-two", out)
        self.assertIn("+TWO", out)

    def test_diff_refs(self):
        write(self.p("a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        write(self.p("a.txt"), "one\ntwo\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c2")
        out = "".join(self.repo.diff_refs("main", "feature"))
        self.assertIn("+two", out)

    def test_diff_identical_refs_is_empty(self):
        write(self.p("a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        self.assertEqual(self.repo.diff_refs("main", "main"), [])

    def test_diff_ref_worktree(self):
        write(self.p("a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        write(self.p("a.txt"), "one\ntwo\n")
        out = "".join(self.repo.diff_ref_worktree("HEAD"))
        self.assertIn("+two", out)


class TestMerge(RepoTestCase):
    def _init_diverging_branches(self, base_content="hello world\n"):
        write(self.p("a.txt"), base_content)
        self.repo.add(["a.txt"])
        self.repo.commit("init")
        self.repo.create_branch("branchA")
        self.repo.create_branch("branchB")
        self.repo.checkout("branchA")
        write(self.p("a.txt"), base_content + "A change\n")
        self.repo.add(["a.txt"])
        self.repo.commit("A change")
        self.repo.checkout("branchB")
        write(self.p("a.txt"), base_content + "B change\n")
        self.repo.add(["a.txt"])
        self.repo.commit("B change")

    def test_fast_forward_merge(self):
        write(self.p("a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        write(self.p("a.txt"), "one\ntwo\n")
        self.repo.add(["a.txt"])
        cid = self.repo.commit("c2")
        self.repo.checkout("main")
        result = self.repo.merge("feature")
        self.assertEqual(result["status"], "fast-forward")
        self.assertEqual(result["commit"], cid)
        with open(self.p("a.txt")) as fh:
            self.assertEqual(fh.read(), "one\ntwo\n")

    def test_merge_up_to_date(self):
        write(self.p("a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        self.repo.create_branch("feature")
        result = self.repo.merge("feature")
        self.assertEqual(result["status"], "up-to-date")

    def test_merge_conflict_sets_merge_head_and_resolving_makes_2parent_commit(self):
        self._init_diverging_branches()
        self.repo.checkout("branchB")
        with self.assertRaises(MergeConflict) as ctx:
            self.repo.merge("branchA")
        self.assertEqual(ctx.exception.paths, ["a.txt"])
        self.assertIsNotNone(self.repo.merge_in_progress())

        with open(self.p("a.txt")) as fh:
            content = fh.read()
        self.assertIn("<<<<<<<", content)

        write(self.p("a.txt"), "hello world\nA change\nB change\n")
        self.repo.add(["a.txt"])
        merge_commit_id = self.repo.commit("resolved")
        merge_commit = self.repo.get_commit(merge_commit_id)
        self.assertEqual(len(merge_commit.parents), 2)
        self.assertIsNone(self.repo.merge_in_progress())

    def test_second_merge_while_unresolved_rejected(self):
        self._init_diverging_branches()
        self.repo.checkout("branchB")
        with self.assertRaises(MergeConflict):
            self.repo.merge("branchA")
        with self.assertRaises(RepositoryError):
            self.repo.merge("branchA")

    def test_merge_dirty_worktree_rejected(self):
        self._init_diverging_branches()
        self.repo.checkout("branchB")
        write(self.p("a.txt"), "uncommitted\n")
        with self.assertRaises(DirtyWorktree):
            self.repo.merge("branchA")

    def test_merge_base_finds_common_ancestor(self):
        self._init_diverging_branches()
        base = self.repo.merge_base("branchA", "branchB")
        self.assertEqual(self.repo.get_commit(base).message, "init\n")


class TestConfig(RepoTestCase):
    def test_set_get_config(self):
        self.assertIsNone(self.repo.get_config("user.name"))
        self.repo.set_config("user.name", "Ada")
        self.assertEqual(self.repo.get_config("user.name"), "Ada")

    def test_config_persists(self):
        self.repo.set_config("user.name", "Ada")
        reloaded = Repository(self.tmp)
        self.assertEqual(reloaded.get_config("user.name"), "Ada")


if __name__ == "__main__":
    unittest.main()
