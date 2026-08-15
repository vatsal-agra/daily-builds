"""Headless-browser smoke test for the generated HTML report, used by
demo.sh. Not a unittest (needs a browser, which the rest of the suite
deliberately doesn't depend on) -- run standalone: `python3 browser_check.py
<path-to-report.html>`. Prints NO_ERRORS on success.
"""
import asyncio
import sys


async def main(path):
    from playwright.async_api import async_playwright

    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await browser.new_page(viewport={"width": 1200, "height": 900})
        page.on("console", lambda msg: errors.append(f"[console.{msg.type}] {msg.text}")
                if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"[pageerror] {exc}"))

        await page.goto("file://" + path)
        await page.wait_for_timeout(500)

        for tab in ("gridworld", "cartpole", "blackjack"):
            await page.click(f'button[data-tab="{tab}"]')
            await page.wait_for_timeout(200)

        # exercise the CartPole animation for a few frames -- switch back to
        # that tab first (it's inactive/hidden after the loop above leaves
        # "blackjack" selected, and a hidden tab's button isn't clickable).
        await page.click('button[data-tab="cartpole"]')
        await page.wait_for_timeout(200)
        await page.click('#tab-cartpole button:has-text("Play")')
        await page.wait_for_timeout(400)

        await browser.close()

    if errors:
        print(f"FOUND {len(errors)} ERROR(S):")
        for e in errors:
            print(" ", e)
    else:
        print("NO_ERRORS")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
