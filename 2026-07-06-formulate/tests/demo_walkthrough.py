#!/usr/bin/env python3
"""End-to-end walkthrough: drives the real HTTP API (the same one the
browser UI talks to) through every required + stretch feature, in order,
and asserts on the results. Exits non-zero on the first failure.
"""

import json
import shutil
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server  # noqa: E402

CHECKS_PASSED = 0


def check(label, cond):
    global CHECKS_PASSED
    if not cond:
        print(f"[FAIL] {label}")
        sys.exit(1)
    CHECKS_PASSED += 1
    print(f"[PASS] {label}")


def main():
    tmpdir = tempfile.mkdtemp()
    state = server.AppState(save_dir=tmpdir)
    httpd = server.make_server(state, "127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def post(path, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def get(path):
        with urllib.request.urlopen(base + path) as resp:
            return resp.read()

    try:
        # D1: formula engine -- arithmetic, precedence, functions, error propagation
        post("/api/edit", {"ref": "A1", "raw": "10"})
        post("/api/edit", {"ref": "A2", "raw": "20"})
        r = post("/api/edit", {"ref": "B1", "raw": "=ROUND(AVERAGE(A1:A2)*2+1,1)"})
        check("D1 formula engine (precedence + functions)",
              r["changed"]["Sheet1"]["B1"]["value"] == 31.0)
        r = post("/api/edit", {"ref": "B2", "raw": "=A1/0"})
        check("D1 error propagation (#DIV/0!)",
              r["changed"]["Sheet1"]["B2"]["error"] == "#DIV/0!")

        # D2: dependency graph -- incremental recalculation
        post("/api/edit", {"ref": "C1", "raw": "=B1*10"})
        r = post("/api/edit", {"ref": "A1", "raw": "100"})
        check("D2 dependency graph propagates through a 3-level chain",
              r["changed"]["Sheet1"]["C1"]["value"] == 1210.0)

        # D3: circular reference detection
        r = post("/api/edit", {"ref": "D1", "raw": "=D1+1"})
        check("D3 self-cycle caught as #CIRC! (no hang)",
              r["changed"]["Sheet1"]["D1"]["error"] == "#CIRC!")

        # D4: undo/redo
        post("/api/edit", {"ref": "E1", "raw": "1"})
        post("/api/edit", {"ref": "E1", "raw": "2"})
        r = post("/api/undo", {})
        check("D4 undo restores previous value", r["changed"]["Sheet1"]["E1"]["value"] == 1.0)
        r = post("/api/redo", {})
        check("D4 redo reapplies it", r["changed"]["Sheet1"]["E1"]["value"] == 2.0)

        # D5: autofill with relative + absolute reference shifting
        post("/api/edit", {"ref": "F1", "raw": "5"})
        post("/api/edit", {"ref": "F2", "raw": "6"})
        post("/api/edit", {"ref": "G1", "raw": "=F1*2"})
        r = post("/api/autofill", {"src": "G1", "targets": ["G2"]})
        check("D5 autofill shifts relative refs", r["changed"]["Sheet1"]["G2"]["value"] == 12.0)

        # D6: CSV import/export round trip
        post("/api/import_csv", {"sheet": "Sheet1", "text": "9,8\n7,6\n", "start": "H1"})
        csv_text = get("/api/export_csv?sheet=Sheet1").decode()
        check("D6 CSV import landed real values", "9,8" in csv_text and "7,6" in csv_text)

        # D7: JSON persistence save/load
        post("/api/save", {"name": "demo"})
        post("/api/edit", {"ref": "A1", "raw": "999999"})  # mutate after saving
        r = post("/api/load", {"name": "demo"})
        check("D7 save/load restores the pre-mutation formulas",
              r["state"]["cells"]["A1"]["value"] == 100.0 and r["state"]["cells"]["C1"]["value"] == 1210.0)

        # D8: multi-sheet + cross-sheet references
        post("/api/sheet", {"action": "add", "name": "Data"})
        post("/api/edit", {"sheet": "Data", "ref": "A1", "raw": "42"})
        r = post("/api/edit", {"sheet": "Sheet1", "ref": "Z1", "raw": "=Data!A1+8"})
        check("D8 cross-sheet reference resolves", r["changed"]["Sheet1"]["Z1"]["value"] == 50.0)

        # D9: live chart data
        chart = json.loads(get("/api/chart?sheet=Sheet1&range=F1:F2"))
        check("D9 chart endpoint returns the selected column's values",
              chart["series"][0]["values"] == [5.0, 6.0])

        print(f"\n{CHECKS_PASSED}/{CHECKS_PASSED} walkthrough checks passed (covering D1-D9).")
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
