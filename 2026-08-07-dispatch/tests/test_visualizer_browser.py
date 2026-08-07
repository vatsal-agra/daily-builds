"""Real headless-Chromium check of the generated HTML report: zero console
errors on normal data, and the Phase-3 stored-XSS regression actually does
NOT execute in a real browser (not just "the source code looks escaped").
Skips cleanly if Node/Playwright/a Chromium binary aren't available in this
environment, rather than failing the whole suite over an optional dependency.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.process import Process
import html_report

NODE = shutil.which("node")
PW_BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
CHROMIUM = Path(PW_BROWSERS) / "chromium"
NODE_MODULES = "/opt/node22/lib/node_modules"


def _browser_available():
    return NODE is not None and CHROMIUM.exists() and Path(NODE_MODULES, "playwright").exists()


_RUNNER = r"""
const { chromium } = require('playwright');
(async () => {
  const url = process.argv[2];
  const browser = await chromium.launch({ executablePath: process.argv[3] });
  const page = await browser.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', err => pageErrors.push(String(err)));
  await page.goto('file://' + url);
  await page.waitForTimeout(300);
  await page.mouse.move(300, 220);
  await page.waitForTimeout(150);
  const xssFired = await page.evaluate(() => window.__pwn === 1);
  console.log(JSON.stringify({ consoleErrors, pageErrors, xssFired }));
  await browser.close();
})();
"""


def _run_in_browser(html_path):
    script = Path("/tmp/dispatch_browser_runner.js")
    script.write_text(_RUNNER)
    env = dict(os.environ)
    env["NODE_PATH"] = NODE_MODULES
    result = subprocess.run(
        [NODE, str(script), str(html_path), str(CHROMIUM)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"browser runner failed: {result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(_browser_available(), "Node/Playwright/Chromium not available in this environment")
class VisualizerBrowserTest(unittest.TestCase):
    def test_normal_report_has_zero_console_errors(self):
        procs = [Process("P1", 0, 7), Process("P2", 2, 4), Process("P3", 4, 9)]
        out = Path("/tmp/dispatch_browser_test_normal.html")
        try:
            html_report.build_report(procs, 4, [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5], 3, out)
            result = _run_in_browser(out)
            self.assertEqual(result["consoleErrors"], [])
            self.assertEqual(result["pageErrors"], [])
        finally:
            out.unlink(missing_ok=True)

    def test_malicious_pid_does_not_execute_in_a_real_browser(self):
        procs = [Process('<img src=x onerror="window.__pwn=1">', 0, 5), Process("P2", 1, 3)]
        out = Path("/tmp/dispatch_browser_test_xss.html")
        try:
            html_report.build_report(procs, 4, [1, 2, 3, 1, 2], 2, out)
            result = _run_in_browser(out)
            self.assertFalse(result["xssFired"], "XSS payload in a pid executed in a real browser")
            self.assertEqual(result["pageErrors"], [])
        finally:
            out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
