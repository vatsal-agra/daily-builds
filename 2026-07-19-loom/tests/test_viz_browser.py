"""Headless-Chromium smoke test for the attention visualizer's real JS.
Skips cleanly if node/playwright/a browser binary aren't available -- this
mirrors the pattern other from-scratch-with-a-viz builds in this repo use
(Node/Playwright only ever verify the generated JS, never implement logic)."""
import glob
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

CHECK_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: process.argv[2] });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push('console.error: ' + msg.text()); });

  await page.goto('file://' + process.argv[3]);
  await page.waitForTimeout(300);
  await page.click('#nextBtn');
  await page.waitForTimeout(100);
  await page.selectOption('#layerSel', '0');
  await page.waitForTimeout(100);

  const headsCount = await page.$$eval('.head-card', els => els.length);
  const frameLabel = await page.textContent('#frameLabel');
  console.log(JSON.stringify({ errors, headsCount, frameLabel }));
  await browser.close();
  process.exit(errors.length ? 1 : 0);
})().catch(e => { console.error('FATAL', e); process.exit(1); });
"""


def _find_chromium():
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                    os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome")):
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    return None


def _node_has_playwright():
    node_path = os.environ.get("NODE_PATH", "")
    candidates = [node_path] if node_path else []
    candidates.append("/opt/node22/lib/node_modules")
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, "playwright")):
            return c
    return None


NODE = shutil.which("node")
CHROMIUM = _find_chromium()
NODE_MODULES = _node_has_playwright()


@unittest.skipUnless(NODE and CHROMIUM and NODE_MODULES, "node/playwright/chromium not available in this environment")
class TestVizBrowser(unittest.TestCase):
    def test_visualizer_loads_without_js_errors(self):
        import sys
        sys.path.insert(0, ROOT)
        from loom.attn_viz import render

        frames = [
            {"tokens": ["T", "h", "e"][:i + 1], "layers": [[[[1.0] * (i + 1) for _ in range(i + 1)] for _ in range(2)]]}
            for i in range(3)
        ]
        with tempfile.TemporaryDirectory() as d:
            html_path = os.path.join(d, "attn.html")
            render(frames, "The", html_path)

            script_path = os.path.join(d, "check.js")
            with open(script_path, "w") as f:
                f.write(CHECK_SCRIPT)

            env = dict(os.environ)
            env["NODE_PATH"] = NODE_MODULES
            result = subprocess.run(
                [NODE, script_path, CHROMIUM, os.path.abspath(html_path)],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(result.returncode, 0, f"stdout={result.stdout}\nstderr={result.stderr}")
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["errors"], [])
            self.assertEqual(payload["headsCount"], 2)


if __name__ == "__main__":
    unittest.main()
