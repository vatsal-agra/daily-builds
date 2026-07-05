import os
import tempfile
import unittest

from sift.index import InvertedIndex, build_index_from_dir


class TestInvertedIndex(unittest.TestCase):
    def setUp(self):
        self.index = InvertedIndex()
        self.d0 = self.index.add_document("a.txt", "Doc A", "the quick brown fox jumps")
        self.d1 = self.index.add_document("b.txt", "Doc B", "the lazy fox sleeps")

    def test_doc_count_and_ids(self):
        self.assertEqual(self.index.doc_count, 2)
        self.assertEqual(self.d0, 0)
        self.assertEqual(self.d1, 1)

    def test_postings_contain_expected_docs(self):
        self.assertEqual(set(self.index.postings["fox"].keys()), {0, 1})
        self.assertEqual(set(self.index.postings["quick"].keys()), {0})

    def test_term_freq(self):
        self.index.add_document("c.txt", "Doc C", "fox fox fox")
        self.assertEqual(self.index.term_freq("fox", 2), 3)
        self.assertEqual(self.index.term_freq("fox", 0), 1)
        self.assertEqual(self.index.term_freq("nonexistent", 0), 0)

    def test_doc_freq(self):
        self.assertEqual(self.index.doc_freq("fox"), 2)
        self.assertEqual(self.index.doc_freq("quick"), 1)
        self.assertEqual(self.index.doc_freq("nope"), 0)

    def test_avg_doc_length(self):
        # doc0: quick,brown,fox,jump = 4 (the removed); doc1: lazi,fox,sleep = 3
        self.assertAlmostEqual(self.index.avg_doc_length, 3.5)

    def test_empty_index_avg_length_no_crash(self):
        empty = InvertedIndex()
        self.assertEqual(empty.avg_doc_length, 0.0)

    def test_positions_recorded_correctly(self):
        # "the"(0,filtered) "quick"(1) "brown"(2) "fox"(3) "jumps"(4)
        self.assertEqual(self.index.postings["fox"][0].positions, [3])


class TestBuildIndexFromDir(unittest.TestCase):
    def test_builds_from_txt_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "one.txt"), "w") as fh:
                fh.write("First Document\nabout rockets and space travel")
            with open(os.path.join(tmp, "two.txt"), "w") as fh:
                fh.write("Second Document\nabout cooking bread")
            with open(os.path.join(tmp, "ignore.json"), "w") as fh:
                fh.write("{}")

            index = build_index_from_dir(tmp)
            self.assertEqual(index.doc_count, 2)
            titles = sorted(doc.title for doc in index.documents.values())
            self.assertEqual(titles, ["First Document", "Second Document"])

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = build_index_from_dir(tmp)
            self.assertEqual(index.doc_count, 0)

    def test_blank_leading_line_does_not_produce_empty_title(self):
        # regression test for REVIEW.md #4
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "blank_first.txt"), "w") as fh:
                fh.write("\n\nActual Title\nbody text about rockets")
            index = build_index_from_dir(tmp)
            self.assertEqual(index.documents[0].title, "Actual Title")

    def test_entirely_blank_file_falls_back_to_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "blank.txt"), "w") as fh:
                fh.write("\n\n   \n")
            index = build_index_from_dir(tmp)
            self.assertEqual(index.documents[0].title, "blank.txt")


if __name__ == "__main__":
    unittest.main()
