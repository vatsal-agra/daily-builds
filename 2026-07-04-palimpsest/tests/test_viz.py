import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palimpsest.repository import Repository
from palimpsest.viz import generate_html


class TestViz(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name
        self.repo = Repository.init(self.root)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _extract_data(self, htm: str) -> dict:
        m = re.search(r"const DATA = (\{.*\});", htm)
        self.assertIsNotNone(m)
        return json.loads(m.group(1))

    def test_empty_repo_renders_valid_html_with_no_commits(self):
        htm = generate_html(self.repo)
        self.assertIn("<html>", htm)
        data = self._extract_data(htm)
        self.assertEqual(data["commits"], [])
        self.assertIsNone(data["head"])

    def test_single_commit_included_with_diff(self):
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("hello\n")
        self.repo.add(["a.txt"])
        sha = self.repo.commit("first", timestamp=1000)
        htm = generate_html(self.repo)
        data = self._extract_data(htm)
        self.assertEqual(len(data["commits"]), 1)
        self.assertEqual(data["commits"][0]["sha"], sha)
        self.assertIn("+hello", data["diffs"][sha])
        self.assertEqual(data["head"], sha)
        self.assertEqual(data["headBranch"], "main")

    def test_merge_commit_has_two_parents_and_both_branches_present(self):
        with open(os.path.join(self.root, "f.txt"), "w") as f:
            f.write("base\n")
        self.repo.add(["f.txt"])
        self.repo.commit("base", timestamp=1000)
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        with open(os.path.join(self.root, "f.txt"), "w") as f:
            f.write("base\nfeature\n")
        self.repo.add(["f.txt"])
        self.repo.commit("feature change", timestamp=1001)
        self.repo.checkout("main")
        with open(os.path.join(self.root, "g.txt"), "w") as f:
            f.write("main-only\n")
        self.repo.add(["g.txt"])
        self.repo.commit("main change", timestamp=1002)

        from palimpsest.merge import merge_branch

        result = merge_branch(self.repo, "feature", timestamp=1003)
        self.assertFalse(result.conflicts)

        htm = generate_html(self.repo)
        data = self._extract_data(htm)
        shas = {c["sha"]: c for c in data["commits"]}
        self.assertIn(result.commit_sha, shas)
        self.assertEqual(len(shas[result.commit_sha]["parents"]), 2)
        self.assertEqual(set(data["branches"].keys()), {"main", "feature"})

    def test_no_double_quote_breaks_json_embedding(self):
        # A commit message containing characters that could break naive
        # string interpolation should still produce valid embedded JSON.
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("x\n")
        self.repo.add(["a.txt"])
        self.repo.commit('message with "quotes" and \\backslash', timestamp=1000)
        htm = generate_html(self.repo)
        data = self._extract_data(htm)
        self.assertIn('"quotes"', data["commits"][0]["message"])

    def test_script_tag_in_commit_message_cannot_break_out_of_script_block(self):
        # A malicious/careless commit message containing a literal
        # "</script>" must not be able to prematurely close the <script>
        # block the JSON payload is embedded in (real HTML-parsing bug: a
        # naive json.dumps() embed lets attacker-controlled commit text
        # break out and inject markup/script).
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("x\n")
        self.repo.add(["a.txt"])
        self.repo.commit("</script><img src=x onerror=alert(1)>", timestamp=1000)
        htm = generate_html(self.repo)
        script_start = htm.index("const DATA")
        script_end = htm.index("</script>", script_start)
        payload = htm[script_start:script_end]
        self.assertNotIn("</script>", payload)
        data = self._extract_data(htm)
        self.assertEqual(data["commits"][0]["message"], "</script><img src=x onerror=alert(1)>")


if __name__ == "__main__":
    unittest.main()
