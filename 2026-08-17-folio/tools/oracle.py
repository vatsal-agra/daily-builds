"""The Chromium ground-truth oracle used by the block-layout test suite.

Renders a fixture in real headless Chromium (pre-installed in this
environment) at a fixed viewport width and reads back
`getBoundingClientRect()` for every element carrying a `data-t` attribute --
the exact geometry a real browser produces for the same markup, to compare
Folio's own layout engine against.
"""

import os

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

_CHROME_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

_browser = None
_playwright = None


def _get_browser():
    global _browser, _playwright
    if _browser is None:
        from playwright.sync_api import sync_playwright

        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            executable_path=_CHROME_PATH, args=["--no-sandbox"]
        )
    return _browser


def close():
    global _browser, _playwright
    if _browser is not None:
        _browser.close()
        _browser = None
    if _playwright is not None:
        _playwright.stop()
        _playwright = None


def chromium_boxes(html, viewport_width=800, viewport_height=1200):
    """Render `html` (a full document string) in real Chromium and return
    {data_t_value: (x, y, width, height)} for every element with a `data-t`
    attribute, using getBoundingClientRect() (border-box geometry, same as
    Folio's LayoutBox.rect())."""
    browser = _get_browser()
    page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})
    try:
        page.set_content(html, wait_until="load")
        result = page.eval_on_selector_all(
            "[data-t]",
            """(els) => els.map(el => {
                const r = el.getBoundingClientRect();
                return [el.getAttribute('data-t'), r.x, r.y, r.width, r.height];
            })""",
        )
        return {row[0]: (row[1], row[2], row[3], row[4]) for row in result}
    finally:
        page.close()
