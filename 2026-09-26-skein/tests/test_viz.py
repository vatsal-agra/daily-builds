"""Generates the HTML visualizer and, when a headless Chromium is
available, actually loads it in a real browser and checks for console
errors -- catching bugs (like a temporal-dead-zone ReferenceError) that
only show up at runtime, not by reading the generated markup.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from skein.storage import Graph
from skein.viz import render_html

_PLAYWRIGHT_MODULE = "/opt/node22/lib/node_modules/playwright"
_CHROMIUM_BIN = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
_HAS_BROWSER = shutil.which("node") and os.path.exists(_PLAYWRIGHT_MODULE) and os.path.exists(_CHROMIUM_BIN)

_NODE_SCRIPT = r"""
const { chromium } = require(process.argv[2]);
(async () => {
  const browser = await chromium.launch({ executablePath: process.argv[3] });
  const results = [];
  for (const scheme of ['light', 'dark']) {
    const page = await browser.newPage({ colorScheme: scheme });
    const errors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', err => errors.push(String(err)));
    await page.goto('file://' + process.argv[4]);
    await page.waitForTimeout(600);
    const stats = await page.textContent('#stats');
    const box = await page.locator('#cv').boundingBox();
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(150);
    const detail = await page.textContent('#detail-body');
    results.push({ scheme, stats, detail, errors });
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify(results));
})();
"""


def _run_node_script(*args):
    """Runs _NODE_SCRIPT from a real temp .js file (not `node -e`, whose
    argv indexing/quoting is fragile across Node versions) with `args`
    available as process.argv[2:].
    """
    tmpdir = tempfile.mkdtemp(prefix="skein_viz_script_")
    try:
        script_path = os.path.join(tmpdir, "check.js")
        with open(script_path, "w") as f:
            f.write(_NODE_SCRIPT)
        return subprocess.run(["node", script_path, *args], capture_output=True, text=True, timeout=60)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestVizGeneration(unittest.TestCase):
    def _build(self, query_text=None):
        g = Graph()
        with g.transaction():
            a = g.create_node(["Person"], {"name": "Alice"})
            b = g.create_node(["Person"], {"name": "Bob"})
            g.create_edge(a, b, "KNOWS", {})
        return g, render_html(g, query_text=query_text)

    def test_produces_well_formed_html(self):
        _g, html = self._build()
        self.assertTrue(html.strip().startswith("<!doctype html>"))
        self.assertIn("<canvas", html)
        self.assertIn("const DATA", html)

    def test_embedded_json_is_valid_and_matches_graph(self):
        g, html = self._build()
        start = html.index("const DATA = ") + len("const DATA = ")
        end = html.index(";\n", start)
        payload = json.loads(html[start:end])
        self.assertEqual(len(payload["nodes"]), len(g.nodes))
        self.assertEqual(len(payload["edges"]), len(g.edges))

    def test_script_breaking_property_is_neutralized(self):
        g = Graph()
        with g.transaction():
            g.create_node(["Person"], {"name": "</script><script>alert(1)</script>"})
        html = render_html(g)
        script_start = html.index("const DATA")
        self.assertNotIn("</script><script>", html[script_start:])

    def test_query_highlight_matches_pattern(self):
        g, html = self._build(query_text="MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name")
        self.assertIn("QUERY = {", html)
        self.assertIn("highlightNodes", html)

    @unittest.skipUnless(_HAS_BROWSER, "headless Chromium/Playwright not available in this environment")
    def test_renders_with_zero_console_errors_in_light_and_dark(self):
        _g, html = self._build(query_text="MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name")
        tmpdir = tempfile.mkdtemp(prefix="skein_viz_test_")
        try:
            html_path = os.path.join(tmpdir, "graph.html")
            with open(html_path, "w") as f:
                f.write(html)
            proc = _run_node_script(_PLAYWRIGHT_MODULE, _CHROMIUM_BIN, html_path)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            results = json.loads(proc.stdout.strip().splitlines()[-1])
            for r in results:
                self.assertEqual(r["errors"], [], f"{r['scheme']} theme had console errors: {r['errors']}")
                self.assertIn("2 nodes", r["stats"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
