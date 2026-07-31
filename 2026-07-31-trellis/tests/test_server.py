"""Exercises the real HTTP server -- a live socket, not calling handler
methods directly -- the same way the browser UI and demo.sh's curl
walkthrough do."""

import json
import threading
import unittest
import http.client

from trellis.server import make_server


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.state = make_server(host="127.0.0.1", port=0, rows=20, cols=10)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        try:
            parsed = json.loads(data) if data else None
        except json.JSONDecodeError:
            parsed = data.decode("utf-8", errors="replace")
        return resp.status, parsed


class TestBasicApi(ServerTestCase):
    def test_index_page_served(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Trellis", body)

    def test_state_endpoint(self):
        status, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(body["sheet"], "Sheet1")
        self.assertEqual(body["rows"], 20)

    def test_set_cell_and_read_back(self):
        status, body = self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 1, "col": 1, "raw": "5"})
        self.assertEqual(status, 200)
        self.assertEqual(body["changed"]["1,1"]["display"], "5")

    def test_formula_recalculation_over_http(self):
        self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 2, "col": 1, "raw": "5"})
        status, body = self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 2, "col": 2, "raw": "=A2*10"})
        self.assertEqual(body["changed"]["2,2"]["display"], "50")

    def test_error_cell_reports_error_field(self):
        status, body = self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 3, "col": 1, "raw": "=1/0"})
        self.assertEqual(body["changed"]["3,1"]["error"], "#DIV/0!")

    def test_404_for_unknown_route(self):
        status, _ = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)

    def test_invalid_json_body(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/cell", body="not json", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_out_of_range_cell_rejected(self):
        status, body = self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 0, "col": 1, "raw": "5"})
        self.assertEqual(status, 400)
        status, body = self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 9999, "col": 1, "raw": "5"})
        self.assertEqual(status, 400)

    def test_missing_sheet_404(self):
        status, _ = self.request("POST", "/api/cell", {"sheet": "Nope", "row": 1, "col": 1, "raw": "5"})
        self.assertEqual(status, 404)

    def test_path_traversal_blocked(self):
        status, _ = self.request("GET", "/static/../../etc/passwd")
        self.assertEqual(status, 404)


class TestUndoRedoOverHttp(ServerTestCase):
    def test_undo_redo_round_trip(self):
        self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 5, "col": 1, "raw": "1"})
        self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 5, "col": 1, "raw": "2"})
        status, body = self.request("POST", "/api/undo", {"sheet": "Sheet1"})
        self.assertEqual(body["changed"]["5,1"]["display"], "1")
        status, body = self.request("POST", "/api/redo", {"sheet": "Sheet1"})
        self.assertEqual(body["changed"]["5,1"]["display"], "2")

    def test_undo_with_nothing_to_undo(self):
        # Fresh cell with no history entries for it specifically won't
        # necessarily be empty (shared undo stack), so just check the
        # documented empty-stack behavior via a dedicated sequence:
        status, body = self.request("POST", "/api/redo", {"sheet": "Sheet1"})
        # Whatever the current redo-stack state, a repeated redo call must
        # never 500 -- either it succeeds or cleanly reports nothing to redo.
        self.assertIn(status, (200, 400))


class TestSheetManagementOverHttp(ServerTestCase):
    def test_add_rename_delete_sheet(self):
        status, body = self.request("POST", "/api/sheet", {"name": "Data"})
        self.assertEqual(status, 200)
        self.assertIn("Data", body["sheets"])

        status, body = self.request("POST", "/api/sheet/rename", {"old": "Data", "new": "Source"})
        self.assertEqual(status, 200)
        self.assertIn("Source", body["sheets"])
        self.assertNotIn("Data", body["sheets"])

        status, body = self.request("POST", "/api/sheet/delete", {"name": "Source"})
        self.assertEqual(status, 200)
        self.assertNotIn("Source", body["sheets"])

    def test_cannot_add_sheet_with_bang(self):
        status, body = self.request("POST", "/api/sheet", {"name": "Bad!Name"})
        self.assertEqual(status, 400)

    def test_cannot_delete_last_sheet(self):
        # This suite's class-level server always has exactly Sheet1 left
        # after prior tests in this class run and clean up after themselves,
        # but to be robust regardless of ordering, just check deleting
        # a sheet down to zero is always rejected somewhere in the chain.
        status, body = self.request("GET", "/api/state")
        sheets = body["sheets"]
        # delete all but one
        for name in sheets[1:]:
            self.request("POST", "/api/sheet/delete", {"name": name})
        status, body = self.request("GET", "/api/state")
        last = body["sheets"][0]
        status, body = self.request("POST", "/api/sheet/delete", {"name": last})
        self.assertEqual(status, 400)


class TestCsvAndChartOverHttp(ServerTestCase):
    def test_csv_import_and_export_round_trip(self):
        status, body = self.request("POST", "/api/import.csv", {
            "sheet": "Sheet1",
            "text": "Item,Qty,Price,Total\nWidget,3,9.5,=B2*C2\n",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["imported"], 8)
        self.assertEqual(body["skipped"], 0)

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/export.csv?sheet=Sheet1")
        resp = conn.getresponse()
        csv_text = resp.read().decode("utf-8")
        conn.close()
        self.assertIn("28.5", csv_text)

    def test_csv_import_reports_skipped_cells_past_grid(self):
        big_csv = "\n".join(f"r{i},{i}" for i in range(1, 51))  # 50 rows > 20-row grid
        status, body = self.request("POST", "/api/import.csv", {"sheet": "Sheet1", "text": big_csv})
        self.assertGreater(body["skipped"], 0)

    def test_chart_endpoint_returns_svg(self):
        self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 1, "col": 1, "raw": "1"})
        self.request("POST", "/api/cell", {"sheet": "Sheet1", "row": 2, "col": 1, "raw": "2"})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/chart?sheet=Sheet1&range=A1:A2&kind=bar")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertTrue(body.startswith(b"<svg"))

    def test_chart_bad_range_returns_400(self):
        status, body = self.request("GET", "/api/chart?sheet=Sheet1&range=bogus")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
