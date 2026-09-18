"""Headless-Chromium checks for visualizer/index.html, run by demo.sh.

Exercises the actual browser artifact end to end: every tab, the
interactive controls, and the two regression scenarios REVIEW.md
documents as real, previously-reproduced bugs (the stale-setTimeout
reset race, and the self-play/oracle interaction). Exits 0 and prints
"N/N checks green" only if every check passes; prints which check failed
and why, and exits 1, otherwise.
"""
import os
import random
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = "file://" + os.path.join(HERE, "visualizer", "index.html")
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM", "/opt/pw-browsers/chromium")

results = []


def check(name):
    def decorator(fn):
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:  # noqa: BLE001 -- want every failure caught and reported
            results.append((name, False, str(e)))
        return fn
    return decorator


def new_page(browser, width=1400, height=1000):
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    return page, errors


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM)

        @check("Cliff Walking tab: loads, all 4 algorithms + playback controls, zero console errors")
        def _():
            page, errors = new_page(browser)
            page.goto(INDEX)
            page.wait_for_timeout(300)
            for algo in ["optimal", "sarsa", "qlearning", "sarsa_lambda"]:
                page.click(f"#algo-picker button[data-algo={algo}]")
                page.wait_for_timeout(50)
            page.click("#cliff-play")
            page.wait_for_timeout(150)
            page.click("#cliff-play")
            page.click("#cliff-step-fwd")
            page.click("#cliff-step-back")
            label = page.inner_text("#cliff-step-label")
            assert "step 0" in label, f"scrubber didn't reset to step 0: {label!r}"
            assert not errors, f"console errors: {errors}"
            page.close()

        @check("Tic-Tac-Toe tab: naive human never beats the perfect oracle")
        def _():
            page, errors = new_page(browser)
            page.goto(INDEX)
            page.click("nav.tabs button[data-panel=ttt-panel]")
            page.click("#opponent-toggle button[data-opp=oracle]")
            page.wait_for_timeout(150)
            for _ in range(9):
                cells = page.query_selector_all(".ttt-cell")
                empties = [c for c in cells if "disabled" not in (c.get_attribute("class") or "")]
                if not empties:
                    break
                empties[0].click()
                page.wait_for_timeout(300)
                status = page.inner_text("#ttt-status")
                if status.strip():
                    assert "You win!" not in status, f"human beat the perfect oracle: {status!r}"
                    break
            assert not errors, f"console errors: {errors}"
            page.close()

        @check("Tic-Tac-Toe tab: reset mid-turn does not crash (stale setTimeout regression)")
        def _():
            page, errors = new_page(browser)
            page.goto(INDEX)
            page.click("nav.tabs button[data-panel=ttt-panel]")
            page.click("#opponent-toggle button[data-opp=oracle]")
            page.wait_for_timeout(150)
            for _ in range(3):
                cells = page.query_selector_all(".ttt-cell")
                cells[0].click()
                page.wait_for_timeout(25)  # well within the bot's 250ms reply delay
                page.click("#ttt-reset")
                page.wait_for_timeout(350)
            assert not errors, f"console errors: {errors}"
            page.close()

        @check("Tic-Tac-Toe tab: 10 mixed random games across both opponents/sides, zero errors")
        def _():
            page, errors = new_page(browser)
            page.goto(INDEX)
            page.click("nav.tabs button[data-panel=ttt-panel]")
            rng = random.Random(1)
            for game in range(10):
                opp = "oracle" if game % 2 == 0 else "agent"
                side = "X" if game % 3 else "O"
                page.click(f"#opponent-toggle button[data-opp={opp}]")
                page.click(f"#side-toggle button[data-side={side}]")
                page.wait_for_timeout(120)
                for _ in range(9):
                    cells = page.query_selector_all(".ttt-cell")
                    empties = [i for i, c in enumerate(cells) if "disabled" not in (c.get_attribute("class") or "")]
                    if not empties:
                        break
                    cells[rng.choice(empties)].click()
                    page.wait_for_timeout(280)
                    if page.inner_text("#ttt-status").strip():
                        break
            assert not errors, f"console errors: {errors}"
            page.close()

        @check("CartPole tab: gradient check badge is PASS, playback works, zero console errors")
        def _():
            page, errors = new_page(browser)
            page.goto(INDEX)
            page.click("nav.tabs button[data-panel=reinforce-panel]")
            page.wait_for_timeout(300)
            badge = page.inner_text("#reinforce-panel .stat-cards .stat:first-child .value")
            assert badge.strip() == "PASS", f"gradient check badge is not PASS: {badge!r}"
            page.click("#cp-play")
            page.wait_for_timeout(200)
            page.click("#cp-play")
            assert not errors, f"console errors: {errors}"
            page.close()

        @check("Mobile viewport (390px): no horizontal overflow on any tab")
        def _():
            page, errors = new_page(browser, width=390, height=844)
            page.goto(INDEX)
            for panel in ["cliff-panel", "ttt-panel", "reinforce-panel"]:
                page.click(f"nav.tabs button[data-panel={panel}]")
                page.wait_for_timeout(150)
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                assert not overflow, f"{panel} overflows horizontally at 390px"
            assert not errors, f"console errors: {errors}"
            page.close()

        @check("Malformed data.js is caught and reported, not a blank silent page")
        def _():
            page, errors = new_page(browser)
            # Intercept the real data file and swap in deliberately-broken
            # data, so this exercises the actual boot()/try-catch code path
            # in index.html rather than simulating it.
            page.route("**/bellman_data.js", lambda route: route.fulfill(
                status=200, content_type="application/javascript",
                body="var BELLMAN_DATA = {cliff: null, tictactoe: null, reinforce: null};",
            ))
            page.goto(INDEX)
            page.wait_for_timeout(300)
            error_box = page.locator("#load-error")
            assert error_box.is_visible(), "malformed data did not surface the #load-error box"
            text = error_box.inner_text()
            assert "viz_export" in text, f"error message doesn't point at how to fix it: {text!r}"
            page.close()

        browser.close()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for name, ok, err in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            print(f"         {err}")

    print(f"\nbrowser checks: {passed}/{total} green")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
