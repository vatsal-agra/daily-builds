import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, 'cli.py')] + args,
        cwd=cwd or PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    )


class TestCLI(unittest.TestCase):
    def test_render_produces_png(self, tmp_out='/tmp/reflow_test_cli_out.png'):
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        result = run_cli(['render', 'examples/hello.html', '-o', tmp_out])
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(tmp_out, 'rb') as f:
            self.assertEqual(f.read(8), b'\x89PNG\r\n\x1a\n')
        os.remove(tmp_out)

    def test_dump_dom_flag(self):
        result = run_cli(['render', 'examples/hello.html', '--dump-dom'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('#document', result.stdout)

    def test_dump_only_run_does_not_write_out_png(self):
        stray = os.path.join(PROJECT_ROOT, 'out.png')
        if os.path.exists(stray):
            os.remove(stray)
        result = run_cli(['render', 'examples/hello.html', '--dump-dom'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(stray), 'a dump-only run should not clutter the cwd with out.png')

    def test_missing_file_gives_friendly_error_not_a_traceback(self):
        result = run_cli(['render', 'does_not_exist.html'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('error:', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_negative_width_rejected(self):
        result = run_cli(['render', 'examples/hello.html', '--width', '-10'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('error:', result.stderr)


if __name__ == '__main__':
    unittest.main()
