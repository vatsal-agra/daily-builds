"""CLI-level robustness: bad input should produce a clean `error: ...`
message and a non-zero exit code, never a raw Python traceback."""
import contextlib
import io
import os
import tempfile
import unittest

from swarm import cli


def run_cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(args)
        except SystemExit as e:  # argparse itself calls sys.exit on bad args
            code = e.code
    return code, out.getvalue(), err.getvalue()


class TestCliErrorHandling(unittest.TestCase):
    def test_make_torrent_missing_file_is_clean_error(self):
        code, out, err = run_cli(["make-torrent", "/nonexistent/path/x.bin", "--announce", "http://x/announce"])
        self.assertNotEqual(code, 0)
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)

    def test_make_torrent_empty_file_is_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.bin")
            open(path, "wb").close()
            code, out, err = run_cli(["make-torrent", path, "--announce", "http://x/announce"])
            self.assertNotEqual(code, 0)
            self.assertIn("error:", err)
            self.assertNotIn("Traceback", err)

    def test_seed_with_malformed_torrent_is_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_torrent = os.path.join(tmp, "bad.torrent")
            with open(bad_torrent, "wb") as f:
                f.write(b"not bencoded at all")
            src = os.path.join(tmp, "src.bin")
            with open(src, "wb") as f:
                f.write(b"hello world")
            code, out, err = run_cli(["seed", bad_torrent, src])
            self.assertNotEqual(code, 0)
            self.assertIn("error:", err)
            self.assertNotIn("Traceback", err)

    def test_make_torrent_success_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src.bin")
            with open(src, "wb") as f:
                f.write(os.urandom(5000))
            out_torrent = os.path.join(tmp, "out.torrent")
            code, out, err = run_cli(["make-torrent", src, "--announce", "http://x/announce", "-o", out_torrent, "--piece-length", "1000"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out_torrent))
            self.assertIn("info_hash", out)


class TestPieceSpecParsing(unittest.TestCase):
    def test_parse_ranges_and_singles(self):
        self.assertEqual(cli.parse_piece_spec("0-4,7,9-10"), {0, 1, 2, 3, 4, 7, 9, 10})

    def test_parse_empty(self):
        self.assertEqual(cli.parse_piece_spec(""), set())

    def test_parse_single_value(self):
        self.assertEqual(cli.parse_piece_spec("5"), {5})


if __name__ == "__main__":
    unittest.main()
