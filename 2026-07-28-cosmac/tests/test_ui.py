"""Playwright smoke test of the live, server-backed web UI: load the
page, pick a program, run it, and confirm the canvas is really being
redrawn and the debugger's step/breakpoint controls really change
visible state -- not just that the HTTP endpoints return 200."""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

from playwright.sync_api import sync_playwright

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMIUM_PATH = "/opt/pw-browsers/chromium"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.5)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"server at {url} never came up")


class TestWebUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "cosmac.server", str(cls.port)],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_server(cls.base + "/")
        cls.pw = sync_playwright().start()
        launch_kwargs = {}
        if os.path.exists(CHROMIUM_PATH):
            launch_kwargs["executable_path"] = CHROMIUM_PATH
        cls.browser = cls.pw.chromium.launch(**launch_kwargs)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.goto(self.base + "/")
        self.page.wait_for_selector("#screen")

    def tearDown(self):
        self.page.close()

    def _canvas_hash(self):
        return self.page.evaluate(
            "document.getElementById('screen').toDataURL()"
        )

    def test_page_loads_and_stream_connects(self):
        self.page.wait_for_function("document.getElementById('regs').children.length > 0", timeout=5000)
        pc_text = self.page.inner_text("#flags")
        self.assertIn("PC=", pc_text)

    def test_loading_maze_and_running_redraws_the_canvas(self):
        self.page.select_option("#program-select", "maze")
        self.page.click("#btn-load")
        self.page.wait_for_function(
            "document.getElementById('flags').innerText.includes('maze')", timeout=5000
        )
        before = self._canvas_hash()
        self.page.click("#btn-run")
        self.page.wait_for_timeout(1500)
        after = self._canvas_hash()
        self.assertNotEqual(before, after, "canvas did not change after Run on a real program")
        self.page.click("#btn-pause")

    def test_step_button_advances_pc_while_paused(self):
        self.page.select_option("#program-select", "ball")
        self.page.click("#btn-load")
        self.page.wait_for_function(
            "document.getElementById('flags').innerText.includes('ball')", timeout=5000
        )
        self.page.click("#btn-pause")
        self.page.wait_for_timeout(200)

        before = self.page.evaluate("document.querySelector('#disasm .pc')?.dataset.addr")
        self.page.click("#btn-step")
        self.page.wait_for_timeout(150)
        after = self.page.evaluate("document.querySelector('#disasm .pc')?.dataset.addr")
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        self.assertNotEqual(before, after, "PC did not advance after Step")

    def test_breakpoint_click_sets_a_breakpoint_marker(self):
        self.page.select_option("#program-select", "maze")
        self.page.click("#btn-load")
        self.page.wait_for_selector("#disasm .line")
        self.page.click("#disasm .line >> nth=2")
        self.page.wait_for_timeout(300)
        marked = self.page.evaluate(
            "document.querySelectorAll('#disasm .line.bp').length"
        )
        self.assertGreaterEqual(marked, 1)

    def test_keypad_button_sends_key_event_to_server(self):
        self.page.select_option("#program-select", "keypad")
        self.page.click("#btn-load")
        self.page.wait_for_function(
            "document.getElementById('flags').innerText.includes('keypad')", timeout=5000
        )
        self.page.click("#btn-run")  # the CPU only steps while running
        self.page.wait_for_timeout(300)
        before = self._canvas_hash()
        # key "7" button (mapped to CHIP-8 key 0x7 via keyboard row 'a')
        with self.page.expect_response(lambda r: "/key" in r.url):
            self.page.keyboard.down("a")
        self.page.wait_for_timeout(300)
        self.page.keyboard.up("a")
        after = self._canvas_hash()
        self.assertNotEqual(before, after, "keypress did not draw the digit glyph")

    def test_assemble_and_run_custom_source(self):
        self.page.fill("#source", "LD V0, 0xF\nLD I, 0x50\nLD F, V0\nDRW V0, V0, 5")
        self.page.click("#btn-assemble")
        self.page.wait_for_function(
            "document.getElementById('status-line').innerText.includes('assembled')", timeout=5000
        )
        status = self.page.inner_text("#status-line")
        self.assertIn("assembled", status)

    def test_assemble_error_is_surfaced_in_ui(self):
        self.page.fill("#source", "NOTAREALMNEMONIC V0, 1")
        self.page.click("#btn-assemble")
        self.page.wait_for_function(
            "document.getElementById('status-line').innerText.includes('error')", timeout=5000
        )
        self.assertIn("error", self.page.inner_text("#status-line"))


if __name__ == "__main__":
    unittest.main()
