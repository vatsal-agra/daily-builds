"""Headless-Chromium smoke test for the block explorer: starts a tiny demo
network + explorer server in-process, loads the page in a real browser, and
fails if there's any console error or the expected content is missing.
Skips cleanly (exit 0, printing a note) if the `playwright` package or the
pre-installed Chromium binary isn't available -- this is a bonus check on
top of the plain HTTP route tests in test_explorer.py, not a hard
dependency of the test suite."""
import glob
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def find_chromium():
    candidates = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
    return candidates[0] if candidates else None


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright python package not installed -- browser check skipped "
              "(plain-HTTP explorer route tests in test_explorer.py still cover correctness)")
        return 0

    chromium_path = find_chromium()
    if not chromium_path:
        print("SKIP: no pre-installed Chromium found -- browser check skipped")
        return 0

    from keystone import explorer, pow as pow_module
    from keystone.chain import Blockchain, create_genesis_chain
    from keystone.node import FullNode
    from keystone.wallet import Wallet

    EASY_BITS = pow_module.target_to_bits(pow_module.MAX_TARGET)
    genesis_wallet = Wallet.generate()
    seed = create_genesis_chain(genesis_wallet, bits=EASY_BITS)
    genesis = seed.blocks[seed.tip_hash]

    wallets = [Wallet.generate() for _ in range(2)]
    nodes = []
    for i, w in enumerate(wallets):
        chain = Blockchain(genesis)
        node = FullNode("127.0.0.1", 24700 + i, chain, miner_wallet=w, name=f"b{i}")
        node.start()
        nodes.append(node)
    nodes[0].connect_to("127.0.0.1", 24701)
    nodes[1].connect_to("127.0.0.1", 24700)
    time.sleep(0.3)
    for node in nodes:
        node.start_mining()
    time.sleep(2.5)
    for node in nodes:
        node.stop_mining()
    time.sleep(0.3)

    server, _thread = explorer.run_explorer_in_thread(nodes[0], "127.0.0.1", 0)
    port = server.server_address[1]

    console_errors = []
    ok = True
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium_path, args=["--no-sandbox"])
            page = browser.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: console_errors.append(str(exc)))

            page.goto(f"http://127.0.0.1:{port}/", timeout=10000)
            content = page.content()
            if "Keystone" not in content or "height" not in content:
                print("FAIL: index page missing expected content")
                ok = False

            block_link = page.query_selector("a[href^='/block?hash=']")
            if block_link:
                block_link.click()
                page.wait_for_load_state("load", timeout=5000)
                if "Block #" not in page.content():
                    print("FAIL: block detail page missing expected content")
                    ok = False

            page.goto(f"http://127.0.0.1:{port}/mempool", timeout=10000)
            if "Mempool" not in page.content():
                print("FAIL: mempool page missing expected content")
                ok = False

            browser.close()
    finally:
        server.shutdown()
        for node in nodes:
            node.stop()

    if console_errors:
        print(f"FAIL: {len(console_errors)} browser console error(s): {console_errors}")
        ok = False

    if ok:
        print("PASS: explorer renders correctly in real headless Chromium, zero console errors")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
