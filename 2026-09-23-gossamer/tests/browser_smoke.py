"""Headless-Chromium smoke test for the live dashboard: loads the real page
against a real running cluster, asserts on rendered DOM content, and fails
on any browser console error. Not part of `unittest discover` (needs
Playwright + a cluster already running) -- invoked directly by demo.sh.
"""
import sys
import time

from playwright.sync_api import sync_playwright


def main(url):
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        def on_console(msg):
            if msg.type == "error" and "favicon" not in msg.text:
                errors.append(msg.text)
        page.on("console", on_console)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(url)
        page.wait_for_timeout(2500)  # let a few poll cycles run

        node_dots = page.locator(".node-dot").count()
        assert node_dots >= 5, f"expected >=5 node dots on the ring, got {node_dots}"

        table_rows = page.locator("#node-table tbody tr").count()
        assert table_rows >= 5, f"expected >=5 rows in the node table, got {table_rows}"

        pills = page.locator(".pill.alive").count()
        assert pills >= 1, "expected at least one node shown as alive"

        events_text = page.locator("#events").inner_text()
        assert "waiting for events" not in events_text, "event feed never populated"
        assert "put" in events_text or "get" in events_text, f"no put/get events rendered: {events_text[:300]}"

        conflicts_text = page.locator("#conflicts").inner_text()
        assert "none observed yet" not in conflicts_text, "expected a rendered vector-clock conflict"

        page.screenshot(path="/tmp/gossamer-dashboard.png")
        browser.close()

    if errors:
        print("BROWSER CONSOLE ERRORS:")
        for e in errors:
            print(" ", e)
        sys.exit(1)
    print("dashboard smoke test OK: ring, table, events, and a real conflict all rendered, zero console errors")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9995/dashboard")
