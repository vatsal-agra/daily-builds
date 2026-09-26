import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "skein.cli", *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="skein_cli_test_")
        self.path = os.path.join(self.tmpdir, "db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_creates_files(self):
        r = run_cli("init", self.path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.path + ".snapshot.json"))
        self.assertTrue(os.path.exists(self.path + ".wal"))

    def test_query_create_and_match(self):
        run_cli("init", self.path)
        r = run_cli("query", self.path, "CREATE (a:Person {name: 'Alice', age: 30})")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_cli("query", self.path, "MATCH (a:Person) RETURN a.name, a.age")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Alice", r.stdout)
        self.assertIn("30", r.stdout)

    def test_query_explain_shows_plan(self):
        run_cli("init", self.path)
        run_cli("query", self.path, "CREATE (a:Person {name: 'Alice'})")
        r = run_cli("query", self.path, "MATCH (a:Person) RETURN a.name", "--explain")
        self.assertIn("plan:", r.stdout)

    def test_bad_query_reports_clean_error_not_traceback(self):
        run_cli("init", self.path)
        r = run_cli("query", self.path, "THIS IS NOT SKEINQL")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("query error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_db_reports_clean_error(self):
        r = run_cli("query", os.path.join(self.tmpdir, "does_not_exist_dir", "db"), "MATCH (a) RETURN a")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_delete_connected_node_without_detach_reports_clean_error(self):
        run_cli("init", self.path)
        run_cli("query", self.path, "CREATE (a:Person {name: 'A'})-[:KNOWS]->(b:Person {name: 'B'})")
        r = run_cli("query", self.path, "MATCH (a:Person {name: 'A'}) DELETE a")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_import_and_algo(self):
        nodes_csv = os.path.join(self.tmpdir, "nodes.csv")
        edges_csv = os.path.join(self.tmpdir, "edges.csv")
        with open(nodes_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "labels", "name"])
            w.writerow(["1", "Person", "Alice"])
            w.writerow(["2", "Person", "Bob"])
            w.writerow(["3", "Person", "Carol"])
        with open(edges_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["src", "dst", "type", "weight"])
            w.writerow(["1", "2", "KNOWS", "1"])
            w.writerow(["2", "3", "KNOWS", "1"])

        r = run_cli("init", self.path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_cli("import", self.path, "--nodes", nodes_csv, "--edges", edges_csv)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("3 nodes", r.stdout)
        self.assertIn("2 edges", r.stdout)

        r = run_cli("algo", "pagerank", self.path)
        self.assertEqual(r.returncode, 0, r.stderr)

        r = run_cli("algo", "shortest-path", self.path, "--src", "1", "--dst", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hops: 2", r.stdout)

        r = run_cli("algo", "components", self.path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 connected component", r.stdout)

    def test_import_rejects_unknown_edge_endpoint(self):
        nodes_csv = os.path.join(self.tmpdir, "nodes.csv")
        edges_csv = os.path.join(self.tmpdir, "edges.csv")
        with open(nodes_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "labels"])
            w.writerow(["1", "Person"])
        with open(edges_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["src", "dst", "type"])
            w.writerow(["1", "999", "KNOWS"])
        run_cli("init", self.path)
        r = run_cli("import", self.path, "--nodes", nodes_csv, "--edges", edges_csv)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_demo_runs_clean(self):
        r = run_cli("demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("demo complete", r.stdout)


if __name__ == "__main__":
    unittest.main()
