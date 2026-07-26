"""Headless-browser smoke test for the HTML visualizer: loads the real
generated page in Chromium and checks it renders with zero console errors
and its interactive controls actually work (tabs, scrubbing, hover
tooltips). Skips gracefully if Playwright/Chromium isn't available in this
environment -- the Python test suite doesn't depend on it."""
import os
import tempfile
import unittest

from loom.train import train
from loom.sample import generate
from loom.viz import render_html

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

_CHROMIUM_PATH = "/opt/pw-browsers/chromium"
_CORPUS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "corpus", "hollow_loom.txt")

with open(_CORPUS_PATH, encoding="utf-8") as _f:
    CORPUS = _f.read()[:3000]  # varied real text -- avoids BPE over-compressing a short repeated phrase


@unittest.skipUnless(_PLAYWRIGHT_AVAILABLE, "playwright not installed")
@unittest.skipUnless(os.path.exists(_CHROMIUM_PATH), "no headless chromium available")
class TestVizBrowser(unittest.TestCase):
    def test_visualizer_renders_without_console_errors(self):
        with tempfile.TemporaryDirectory() as d:
            model, tokenizer, history = train(
                CORPUS, out_dir=d, num_merges=60, block_size=24, n_embd=16, n_head=4, n_layer=2,
                batch_size=8, steps=30, eval_every=10, seed=0, log_fn=lambda *a, **k: None,
            )
            _, trace = generate(model, tokenizer, prompt="the", max_new_tokens=20, seed=0, capture_attn=True)
            html = render_html(model, tokenizer, {"history": history}, trace, prompt="the")
            html_path = os.path.join(d, "viz.html")
            with open(html_path, "w") as f:
                f.write(html)

            errors = []
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=_CHROMIUM_PATH)
                page = browser.new_page()
                page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(f"file://{html_path}")
                page.wait_for_timeout(300)

                config_text = page.inner_text("#config-row")
                self.assertIn("vocab_size", config_text)

                page.click("#btn-next")
                page.click("#btn-next")
                step_info = page.inner_text("#step-info")
                self.assertIn("step", step_info)

                cells = page.query_selector_all(".heat-cell")
                self.assertGreater(len(cells), 0)
                cells[0].hover()
                page.wait_for_timeout(150)
                tooltip_display = page.eval_on_selector("#tooltip", "el => getComputedStyle(el).display")
                self.assertEqual(tooltip_display, "block")

                tabs = page.query_selector_all(".tab")
                if len(tabs) > 1:
                    tabs[1].click()
                    page.wait_for_timeout(150)

                browser.close()

            self.assertEqual(errors, [], f"console errors found: {errors}")


if __name__ == "__main__":
    unittest.main()
