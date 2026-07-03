import json
import os
import re
import shutil
import tempfile
import unittest

from strata.repository import Repository
from strata.visualizer import render_html


def write(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


class TestVisualizer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = Repository.init(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _extract_data(self, html):
        m = re.search(r"const DATA = (.*?);\n", html)
        self.assertIsNotNone(m)
        return json.loads(m.group(1))

    def test_empty_repo_renders_without_crashing(self):
        html = render_html(self.repo)
        self.assertTrue(html.startswith("<!doctype html>"))
        data = self._extract_data(html)
        self.assertEqual(data["nodes"], [])

    def test_linear_history_layout(self):
        write(os.path.join(self.tmp, "a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        write(os.path.join(self.tmp, "a.txt"), "one\ntwo\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c2")
        html = render_html(self.repo)
        data = self._extract_data(html)
        self.assertEqual(len(data["nodes"]), 2)
        self.assertEqual(data["lanes"], 1)  # linear history needs only one lane
        self.assertTrue(any(n["isHead"] for n in data["nodes"]))

    def test_diverging_branches_use_multiple_lanes(self):
        write(os.path.join(self.tmp, "a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        write(os.path.join(self.tmp, "a.txt"), "one\ntwo\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c2")
        self.repo.checkout("main")
        write(os.path.join(self.tmp, "b.txt"), "x")
        self.repo.add(["b.txt"])
        self.repo.commit("c3")
        html = render_html(self.repo)
        data = self._extract_data(html)
        self.assertGreaterEqual(data["lanes"], 2)

    def test_merge_commit_has_two_parents_in_graph(self):
        write(os.path.join(self.tmp, "a.txt"), "base\n")
        self.repo.add(["a.txt"])
        self.repo.commit("init")
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        write(os.path.join(self.tmp, "c.txt"), "x")
        self.repo.add(["c.txt"])
        self.repo.commit("feature work")
        self.repo.checkout("main")
        write(os.path.join(self.tmp, "d.txt"), "y")
        self.repo.add(["d.txt"])
        self.repo.commit("main work")
        self.repo.merge("feature")
        html = render_html(self.repo)
        data = self._extract_data(html)
        merge_nodes = [n for n in data["nodes"] if len(n["parents"]) == 2]
        self.assertEqual(len(merge_nodes), 1)

    def test_diff_field_is_populated_and_correct(self):
        write(os.path.join(self.tmp, "a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        write(os.path.join(self.tmp, "a.txt"), "one\ntwo\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c2")
        data = self._extract_data(render_html(self.repo))
        latest = [n for n in data["nodes"] if not n["parents"] == []][0]
        self.assertIn("+two", latest["diff"])

    def test_root_commit_diff_shows_full_file_as_added(self):
        write(os.path.join(self.tmp, "a.txt"), "one\n")
        self.repo.add(["a.txt"])
        self.repo.commit("c1")
        data = self._extract_data(render_html(self.repo))
        root = data["nodes"][0]
        self.assertEqual(root["parents"], [])
        self.assertIn("+one", root["diff"])


if __name__ == "__main__":
    unittest.main()
