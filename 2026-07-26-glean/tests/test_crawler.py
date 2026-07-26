import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from glean.crawler import crawl


class TestCrawler(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="glean_test_crawl_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, relpath, content=""):
        full = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)

    def test_finds_matching_extensions_only(self):
        self._write("a.md", "hello")
        self._write("b.txt", "world")
        self._write("c.py", "print('x')")
        results = {relpath for relpath, _, _ in crawl(self.root)}
        self.assertEqual(results, {"a.md", "b.txt"})

    def test_custom_extensions(self):
        self._write("a.md", "hello")
        self._write("c.py", "print('x')")
        results = {relpath for relpath, _, _ in crawl(self.root, extensions=(".py",))}
        self.assertEqual(results, {"c.py"})

    def test_skips_hidden_and_vcs_directories(self):
        self._write(".git/objects/deadbeef.md", "not real content")
        self._write(".glean/docs.json", "{}")
        self._write("node_modules/pkg/readme.md", "should be skipped")
        self._write("real.md", "should be found")
        results = {relpath for relpath, _, _ in crawl(self.root)}
        self.assertEqual(results, {"real.md"})

    def test_returns_content_and_mtime(self):
        self._write("doc.md", "# Title\ncontent")
        results = list(crawl(self.root))
        self.assertEqual(len(results), 1)
        relpath, text, mtime = results[0]
        self.assertEqual(relpath, "doc.md")
        self.assertIn("Title", text)
        self.assertIsInstance(mtime, float)

    def test_empty_directory(self):
        self.assertEqual(list(crawl(self.root)), [])

    def test_nonexistent_directory_raises_or_empty(self):
        bogus = os.path.join(self.root, "does-not-exist")
        # os.walk on a missing dir silently yields nothing rather than raising --
        # confirm crawl() doesn't crash either way.
        self.assertEqual(list(crawl(bogus)), [])


if __name__ == "__main__":
    unittest.main()
