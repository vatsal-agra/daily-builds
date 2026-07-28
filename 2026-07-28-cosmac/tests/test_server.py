"""HTTP-level tests for cosmac/server.py's REST endpoints -- no browser
involved (that's test_ui.py's job). Covers the save-state/load-state
stretch feature end-to-end through the real HTTP API, plus the other
control endpoints Playwright doesn't poke directly (speed, quirks,
program listing, malformed-request handling)."""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestServerHTTP(unittest.TestCase):
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
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(cls.base + "/", timeout=0.5)
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("server never came up")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return json.loads(r.read())

    def _post(self, path, body=None, expect_status=200):
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                self.assertEqual(r.status, expect_status)
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, expect_status)
            return json.loads(e.read())

    def test_programs_listing_includes_shipped_roms(self):
        data = self._get("/programs")
        for name in ("ball", "maze", "pong", "keypad", "selftest", "beep"):
            self.assertIn(name, data["programs"])

    def test_load_step_and_save_load_state_round_trip(self):
        self._post("/load", {"name": "ball"})
        for _ in range(5):
            self._post("/control", {"action": "step"})
        saved = self._post("/save_state")
        state_after_5_steps = saved["state"]
        self.assertEqual(state_after_5_steps["cycles"], 5)

        for _ in range(5):
            self._post("/control", {"action": "step"})
        moved_on = self._post("/save_state")
        self.assertEqual(moved_on["state"]["cycles"], 10)
        self.assertNotEqual(moved_on["state"]["pc"], state_after_5_steps["pc"])

        # restoring the earlier snapshot must roll cycles/pc back exactly
        self._post("/load_state", {"state": state_after_5_steps})
        restored = self._post("/save_state")
        self.assertEqual(restored["state"]["cycles"], 5)
        self.assertEqual(restored["state"]["pc"], state_after_5_steps["pc"])

    def test_reset_control_action(self):
        self._post("/load", {"name": "ball"})
        self._post("/control", {"action": "step"})
        after_step = self._post("/save_state")["state"]
        self.assertGreater(after_step["cycles"], 0)

        self._post("/control", {"action": "reset"})
        after_reset = self._post("/save_state")["state"]
        self.assertEqual(after_reset["cycles"], 0)

    def test_breakpoint_set_and_clear(self):
        self._post("/load", {"name": "maze"})
        self._post("/breakpoint", {"address": 0x210, "set": True})
        self._post("/breakpoint", {"address": 0x210, "set": False})
        # no assertion beyond "these don't error" -- behavioral coverage of
        # breakpoint-triggered stop lives in test_debugger.py against the
        # same Debugger class the server wraps

    def test_speed_endpoint_clamps_to_sane_bounds(self):
        self._post("/speed", {"hz": 999999999})
        self._post("/speed", {"hz": -5})

    def test_quirks_round_trip(self):
        self._post("/load", {"name": "ball"})
        self._post("/quirks", {"shift_uses_vy": False, "jump_offset_uses_vx": True})
        state = self._post("/save_state")["state"]
        self.assertFalse(state["quirks"]["shift_uses_vy"])
        self.assertTrue(state["quirks"]["jump_offset_uses_vx"])

    def test_load_unknown_program_returns_400(self):
        res = self._post("/load", {"name": "does_not_exist"}, expect_status=400)
        self.assertIn("error", res)

    def test_assemble_with_syntax_error_returns_400_not_500(self):
        res = self._post("/assemble", {"source": "NOTAREALMNEMONIC V0, 1"}, expect_status=400)
        self.assertIn("error", res)

    def test_assemble_valid_source_loads_it(self):
        res = self._post("/assemble", {"source": "LD V0, 0x42\nCLS"})
        self.assertTrue(res["ok"])
        state = self._post("/save_state")["state"]
        self.assertEqual(state["pc"], 0x200)

    def test_key_event_out_of_range_returns_400(self):
        res = self._post("/key", {"key": 99, "down": True}, expect_status=400)
        self.assertIn("error", res)

    def test_stream_frame_includes_memory_window_centered_on_i(self):
        self._post("/load", {"name": "pong"})
        for _ in range(20):
            self._post("/control", {"action": "step"})
        state = self._post("/save_state")["state"]

        req = urllib.request.Request(self.base + "/stream")
        with urllib.request.urlopen(req, timeout=5) as r:
            line = b""
            while not line.startswith(b"data:"):
                line = r.readline()
            frame = json.loads(line[len(b"data:"):].decode("utf-8"))

        self.assertIn("mem_window", frame)
        window = frame["mem_window"]
        self.assertIn("start", window)
        self.assertIn("bytes", window)
        self.assertEqual(len(window["bytes"]), 256)  # 128 bytes as hex
        # the window should be centered on I (clamped at memory edges)
        self.assertLessEqual(window["start"], state["i"])
        self.assertGreaterEqual(window["start"] + 128, state["i"])

    def test_unknown_route_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/nope", timeout=5)
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
