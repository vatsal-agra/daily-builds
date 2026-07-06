import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import server as server_mod


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state = server_mod.AppState(save_dir=self.tmpdir)
        self.httpd = server_mod.make_server(self.state, "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path)) as resp:
            return json.loads(resp.read())

    def post(self, path, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.url(path), data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def get_raw(self, path, headers=None):
        req = urllib.request.Request(self.url(path), headers=headers or {})
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.headers.get("Content-Type"), resp.read()


class TestBasicEditFlow(ServerTestCase):
    def test_edit_then_state_reflects_change(self):
        status, resp = self.post("/api/edit", {"ref": "A1", "raw": "5"})
        self.assertEqual(status, 200)
        self.assertEqual(resp["changed"]["Sheet1"]["A1"]["value"], 5.0)

        state = self.get("/api/state")
        self.assertEqual(state["cells"]["A1"]["display"], "5")

    def test_dependent_recalculates_on_precedent_edit(self):
        self.post("/api/edit", {"ref": "A1", "raw": "5"})
        self.post("/api/edit", {"ref": "A2", "raw": "=A1*10"})
        status, resp = self.post("/api/edit", {"ref": "A1", "raw": "7"})
        self.assertEqual(resp["changed"]["Sheet1"]["A2"]["value"], 70.0)

    def test_error_formula_reports_error_field(self):
        status, resp = self.post("/api/edit", {"ref": "A1", "raw": "=1/0"})
        self.assertEqual(resp["changed"]["Sheet1"]["A1"]["error"], "#DIV/0!")
        self.assertIsNone(resp["changed"]["Sheet1"]["A1"]["value"])

    def test_undo_redo_roundtrip(self):
        self.post("/api/edit", {"ref": "A1", "raw": "1"})
        self.post("/api/edit", {"ref": "A1", "raw": "2"})
        status, resp = self.post("/api/undo", {})
        self.assertEqual(resp["changed"]["Sheet1"]["A1"]["value"], 1.0)
        self.assertTrue(resp["can_redo"])
        status, resp = self.post("/api/redo", {})
        self.assertEqual(resp["changed"]["Sheet1"]["A1"]["value"], 2.0)

    def test_empty_batch_edit_is_a_noop_not_an_undo_frame(self):
        self.post("/api/edit", {"ref": "A1", "raw": "1"})
        status, resp = self.post("/api/edit", {"edits": []})
        self.assertEqual(resp["changed"], {})
        self.assertFalse(resp["can_redo"])
        # the no-op must not have pushed a frame: undo should still remove A1's edit
        status, resp = self.post("/api/undo", {})
        self.assertIsNone(resp["changed"]["Sheet1"]["A1"])
        self.assertFalse(resp["can_undo"])

    def test_batch_edit_for_clearing_a_range(self):
        self.post("/api/edit", {"ref": "A1", "raw": "1"})
        self.post("/api/edit", {"ref": "A2", "raw": "2"})
        status, resp = self.post("/api/edit", {"edits": [{"ref": "A1", "raw": ""}, {"ref": "A2", "raw": ""}]})
        self.assertIsNone(resp["changed"]["Sheet1"]["A1"])
        self.assertIsNone(resp["changed"]["Sheet1"]["A2"])


class TestAutofillEndpoint(ServerTestCase):
    def test_autofill_shifts_relative_refs(self):
        self.post("/api/edit", {"ref": "A1", "raw": "1"})
        self.post("/api/edit", {"ref": "A2", "raw": "2"})
        self.post("/api/edit", {"ref": "A3", "raw": "3"})
        self.post("/api/edit", {"ref": "B1", "raw": "=A1*2"})
        status, resp = self.post("/api/autofill", {"src": "B1", "targets": ["B2", "B3"]})
        self.assertEqual(resp["changed"]["Sheet1"]["B2"]["value"], 4.0)
        self.assertEqual(resp["changed"]["Sheet1"]["B3"]["value"], 6.0)


class TestCsvEndpoints(ServerTestCase):
    def test_import_then_export_roundtrip(self):
        self.post("/api/import_csv", {"text": "1,2\n3,4\n"})
        status, ctype, body = self.get_raw("/api/export_csv")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", ctype)
        self.assertEqual(body.decode().strip(), "1,2\r\n3,4")


class TestSheetEndpoints(ServerTestCase):
    def test_add_and_switch_sheet(self):
        status, resp = self.post("/api/sheet", {"action": "add", "name": "Sheet2"})
        self.assertEqual(resp["sheets"], ["Sheet1", "Sheet2"])
        self.post("/api/edit", {"sheet": "Sheet2", "ref": "A1", "raw": "99"})
        status, resp = self.post("/api/sheet", {"action": "switch", "name": "Sheet1"})
        state = self.get("/api/state")
        self.assertEqual(state["active"], "Sheet1")

    def test_cross_sheet_reference_via_api(self):
        self.post("/api/sheet", {"action": "add", "name": "Data"})
        self.post("/api/edit", {"sheet": "Data", "ref": "A1", "raw": "42"})
        status, resp = self.post("/api/edit", {"sheet": "Sheet1", "ref": "A1", "raw": "=Data!A1+1"})
        self.assertEqual(resp["changed"]["Sheet1"]["A1"]["value"], 43.0)

    def test_duplicate_sheet_name_rejected(self):
        status, resp = self.post("/api/sheet", {"action": "add", "name": "Sheet1"})
        self.assertEqual(status, 400)


class TestSaveLoad(ServerTestCase):
    def test_save_then_load_restores_formulas(self):
        self.post("/api/edit", {"ref": "A1", "raw": "5"})
        self.post("/api/edit", {"ref": "A2", "raw": "=A1*3"})
        status, resp = self.post("/api/save", {"name": "mywb"})
        self.assertTrue(resp["ok"])

        self.post("/api/edit", {"ref": "A1", "raw": "999"})  # mutate after saving
        status, resp = self.post("/api/load", {"name": "mywb"})
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["state"]["cells"]["A2"]["value"], 15.0)

    def test_load_missing_workbook_404s(self):
        status, resp = self.post("/api/load", {"name": "does-not-exist"})
        self.assertEqual(status, 404)


class TestChartEndpoint(ServerTestCase):
    def test_single_column_chart(self):
        for i, v in enumerate([10, 20, 30], start=1):
            self.post("/api/edit", {"ref": f"A{i}", "raw": str(v)})
        data = self.get("/api/chart?sheet=Sheet1&range=A1:A3")
        self.assertEqual(data["series"][0]["values"], [10.0, 20.0, 30.0])

    def test_single_row_chart_treats_each_column_as_a_point(self):
        self.post("/api/edit", {"ref": "A1", "raw": "10"})
        self.post("/api/edit", {"ref": "B1", "raw": "20"})
        self.post("/api/edit", {"ref": "C1", "raw": "30"})
        data = self.get("/api/chart?sheet=Sheet1&range=A1:C1")
        self.assertEqual(data["labels"], ["A", "B", "C"])
        self.assertEqual(data["series"], [{"name": "value", "values": [10.0, 20.0, 30.0]}])

    def test_two_column_chart_uses_first_as_labels(self):
        self.post("/api/edit", {"ref": "A1", "raw": "jan"})
        self.post("/api/edit", {"ref": "B1", "raw": "5"})
        self.post("/api/edit", {"ref": "A2", "raw": "feb"})
        self.post("/api/edit", {"ref": "B2", "raw": "8"})
        data = self.get("/api/chart?sheet=Sheet1&range=A1:B2")
        self.assertEqual(data["labels"], ["jan", "feb"])
        self.assertEqual(data["series"][0]["values"], [5.0, 8.0])


if __name__ == "__main__":
    unittest.main()
