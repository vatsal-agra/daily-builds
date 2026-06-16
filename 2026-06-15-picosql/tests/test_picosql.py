"""Comprehensive test suite for PicoSQL — run with `python3 -m unittest`."""

import os
import random
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from picosql import Database, DBError, ParseError
from picosql.btree import BTree
from picosql.pager import Pager
from picosql.types import decode_row, encode_row
from picosql.repl import render_table, _take_complete, _parse_cell


def tmp_path(suffix=".picodb"):
    d = tempfile.mkdtemp()
    return os.path.join(d, "t" + suffix)


# ---------------------------------------------------------------- storage
class TestStorage(unittest.TestCase):
    def test_type_roundtrip(self):
        rows = [
            (1, "hello", 3.5, None),
            (-42, "", 0.0, "x"),
            (2**62, "unicode ✓ é", -1.25, None),
        ]
        for r in rows:
            self.assertEqual(decode_row(encode_row(r)), r)

    def test_pager_durability(self):
        path = tmp_path()
        p = Pager(path)
        n = p.allocate_page()
        p.write_page(n, b"A" * 4096)
        p.commit()
        p.close()
        p2 = Pager(path)
        self.assertEqual(p2.read_page(n), b"A" * 4096)
        p2.close()

    def test_btree_oracle(self):
        path = tmp_path()
        p = Pager(path)
        t = BTree(p, p.catalog_root)
        oracle = {}
        random.seed(42)
        for _ in range(4000):
            k = random.randint(0, 15000)
            v = f"v{k}-{'x' * random.randint(0, 60)}".encode()
            t.insert(k, v)
            oracle[k] = v
        p.set_catalog_root(t.root)
        p.commit()
        for k, v in oracle.items():
            self.assertEqual(t.search(k), v)
        scanned = list(t.scan())
        self.assertEqual([k for k, _ in scanned], sorted(oracle))
        self.assertEqual(dict(scanned), oracle)
        # range scan
        lo, hi = 4000, 9000
        self.assertEqual(
            [kv for kv in t.scan(lo, hi)],
            sorted((k, v) for k, v in oracle.items() if lo <= k <= hi),
        )
        # delete a chunk; tree stays consistent
        for k in list(oracle)[:800]:
            t.delete(k)
            del oracle[k]
        p.set_catalog_root(t.root)
        p.commit()
        self.assertEqual(dict(t.scan()), oracle)
        p.close()

    def test_crash_recovery_rolls_back(self):
        """A crash before the journal is removed must undo the partial commit."""
        path = tmp_path()
        db = Database(path)
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (id, v) VALUES (1, 'a'), (2, 'b'), (3, 'c')")
        db.close()

        # Simulate a crash: write the journal + main pages but die before the
        # commit point (os.remove of the journal).
        p = Pager(path)
        import os as _os
        real_remove = _os.remove
        p.begin()
        # mutate page 1 (a real existing page) directly
        target = 1
        p.write_page(target, b"Z" * 4096)

        def boom(pth):
            if pth == p.journal_path:
                raise RuntimeError("simulated crash before commit point")
            return real_remove(pth)

        _os.remove = boom
        try:
            with self.assertRaises(RuntimeError):
                p.commit()
        finally:
            _os.remove = real_remove
        p.close()
        self.assertTrue(os.path.exists(path + "-journal"))

        # Reopen: recovery should restore the original bytes and drop the journal.
        db2 = Database(path)
        rows = db2.execute("SELECT * FROM t ORDER BY id").rows
        self.assertEqual(rows, [(1, "a"), (2, "b"), (3, "c")])
        self.assertFalse(os.path.exists(path + "-journal"))
        db2.close()


# ----------------------------------------------------------------- parser
class TestParser(unittest.TestCase):
    def test_parses(self):
        from picosql.parser import parse
        for sql in [
            "CREATE TABLE u (id INTEGER PRIMARY KEY, n TEXT)",
            "INSERT INTO u VALUES (1, 'x')",
            "SELECT a, b.c, COUNT(*) FROM t JOIN s ON t.id = s.id "
            "WHERE x IN (1,2) AND y IS NOT NULL GROUP BY a HAVING COUNT(*) > 1 "
            "ORDER BY a DESC LIMIT 5 OFFSET 2",
            "UPDATE t SET a = a + 1 WHERE id = 3",
            "DELETE FROM t WHERE x LIKE 'a%'",
            "EXPLAIN SELECT * FROM t",
        ]:
            parse(sql)

    def test_syntax_errors_have_position(self):
        from picosql.parser import parse
        for sql in ["SELECT FROM t", "SELECT * FROM", "CREATE TABLE x (a)"]:
            with self.assertRaises(ParseError) as ctx:
                parse(sql)
            self.assertIsInstance(ctx.exception.pos, int)


# ---------------------------------------------------------- SQL behaviour
class TestSQL(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def q(self, sql):
        return self.db.execute(sql)

    def test_crud_lifecycle(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
        self.q("INSERT INTO u (name, age) VALUES ('A', 1), ('B', 2), ('C', 3)")
        self.assertEqual(self.q("SELECT COUNT(*) FROM u").rows, [(3,)])
        self.q("UPDATE u SET age = age * 10 WHERE id >= 2")
        self.assertEqual(
            self.q("SELECT age FROM u ORDER BY id").rows, [(1,), (20,), (30,)]
        )
        self.q("DELETE FROM u WHERE age > 25")
        self.assertEqual(
            self.q("SELECT name FROM u ORDER BY id").rows, [("A",), ("B",)]
        )

    def test_autoincrement_and_explicit_pk(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT)")
        self.q("INSERT INTO u (v) VALUES ('a')")          # id 1
        self.q("INSERT INTO u (id, v) VALUES (10, 'b')")  # id 10
        self.q("INSERT INTO u (v) VALUES ('c')")          # id 11
        self.assertEqual(
            self.q("SELECT id FROM u ORDER BY id").rows, [(1,), (10,), (11,)]
        )

    def test_duplicate_pk_rejected(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT)")
        self.q("INSERT INTO u (id, v) VALUES (1, 'a')")
        with self.assertRaises(DBError):
            self.q("INSERT INTO u (id, v) VALUES (1, 'b')")

    def test_type_enforcement(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, n INTEGER)")
        with self.assertRaises(DBError):
            self.q("INSERT INTO u (n) VALUES ('not a number')")

    def test_insert_is_atomic(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, n INTEGER)")
        self.q("INSERT INTO u (n) VALUES (1), (2)")
        with self.assertRaises(DBError):
            self.q("INSERT INTO u (n) VALUES (3), ('bad'), (5)")
        self.assertEqual(self.q("SELECT COUNT(*) FROM u").rows, [(2,)])

    def test_index_plan_selected(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT)")
        self.q("INSERT INTO u (v) VALUES ('a'),('b'),('c'),('d')")
        self.assertIn("IndexSeek", self.q("EXPLAIN SELECT * FROM u WHERE id = 2").message)
        self.assertIn("IndexRange", self.q("EXPLAIN SELECT * FROM u WHERE id >= 2 AND id < 4").message)
        self.assertIn("SeqScan", self.q("EXPLAIN SELECT * FROM u WHERE v = 'a'").message)

    def test_null_three_valued_logic(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, a INTEGER, b INTEGER)")
        self.q("INSERT INTO u (a, b) VALUES (1, NULL), (NULL, 2), (3, 3)")
        self.assertEqual(self.q("SELECT id FROM u WHERE a = b").rows, [(3,)])
        self.assertEqual(self.q("SELECT id FROM u WHERE a IS NULL").rows, [(2,)])
        self.assertEqual(
            self.q("SELECT COUNT(a), COUNT(*) FROM u").rows, [(2, 3)]
        )

    def test_empty_aggregate(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, v INTEGER)")
        self.assertEqual(
            self.q("SELECT COUNT(*), SUM(v), AVG(v), MIN(v), MAX(v) FROM u").rows,
            [(0, None, None, None, None)],
        )

    def test_transactions(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT)")
        self.q("INSERT INTO u (v) VALUES ('a')")
        self.q("BEGIN")
        self.q("INSERT INTO u (v) VALUES ('b'), ('c')")
        self.assertEqual(self.q("SELECT COUNT(*) FROM u").rows, [(3,)])
        self.q("ROLLBACK")
        self.assertEqual(self.q("SELECT COUNT(*) FROM u").rows, [(1,)])
        self.q("BEGIN")
        self.q("INSERT INTO u (v) VALUES ('d')")
        self.q("COMMIT")
        self.assertEqual(self.q("SELECT COUNT(*) FROM u").rows, [(2,)])

    def test_persistence_across_reopen(self):
        path = tmp_path()
        db = Database(path)
        db.execute("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO u (v) VALUES ('persisted')")
        db.close()
        db2 = Database(path)
        self.assertEqual(db2.execute("SELECT v FROM u").rows, [("persisted",)])
        db2.close()

    def test_many_rows_force_splits(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT)")
        vals = ", ".join(f"('row number {i}')" for i in range(2000))
        self.q(f"INSERT INTO u (v) VALUES {vals}")
        self.assertEqual(self.q("SELECT COUNT(*) FROM u").rows, [(2000,)])
        self.assertEqual(self.q("SELECT v FROM u WHERE id = 1500").rows, [("row number 1499",)])

    def test_drop_table(self):
        self.q("CREATE TABLE u (id INTEGER PRIMARY KEY)")
        self.q("DROP TABLE u")
        with self.assertRaises(DBError):
            self.q("SELECT * FROM u")
        self.q("DROP TABLE IF EXISTS u")  # no error


# --------------------------------------------- differential vs sqlite3
class TestDifferential(unittest.TestCase):
    def setUp(self):
        self.sq = sqlite3.connect(":memory:")
        self.pg = Database(":memory:")
        ddl = [
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER, city TEXT)",
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, uid INTEGER, total REAL, status TEXT)",
            "INSERT INTO users (name,age,city) VALUES ('Ada',36,'Paris'),('Bob',40,'Rome'),"
            "('Cy',19,'Paris'),('Di',40,NULL),('Ed',25,'Rome'),('Fi',NULL,'Paris')",
            "INSERT INTO orders (uid,total,status) VALUES (1,9.5,'paid'),(1,3.0,'paid'),"
            "(2,100.0,'open'),(4,7.25,'paid'),(2,5.0,'open'),(1,2.0,'open')",
        ]
        for s in ddl:
            self.sq.execute(s)
            self.pg.execute(s)

    def tearDown(self):
        self.pg.close()

    QUERIES = [
        "SELECT * FROM users ORDER BY id",
        "SELECT name, age FROM users WHERE age >= 25 ORDER BY age DESC, name",
        "SELECT name FROM users WHERE city = 'Paris' ORDER BY name",
        "SELECT name FROM users WHERE age IS NULL",
        "SELECT count(*), min(age), max(age), sum(age), avg(age) FROM users",
        "SELECT city, count(*) FROM users GROUP BY city ORDER BY city",
        "SELECT age, count(*) FROM users GROUP BY age HAVING count(*) >= 2 ORDER BY age",
        "SELECT u.name, o.total FROM users u JOIN orders o ON u.id=o.uid ORDER BY o.total DESC, u.name",
        "SELECT u.name, count(*) c, sum(o.total) s FROM users u JOIN orders o ON u.id=o.uid GROUP BY u.name ORDER BY s DESC",
        "SELECT name FROM users WHERE id = 3",
        "SELECT name FROM users WHERE id >= 2 AND id <= 4 ORDER BY id",
        "SELECT name FROM users WHERE id = 2 AND city='Rome'",
        "SELECT name FROM users WHERE name LIKE 'A%' OR name LIKE '%i' ORDER BY name",
        "SELECT DISTINCT city FROM users ORDER BY city",
        "SELECT name, age+1 FROM users WHERE id<=2 ORDER BY id",
        "SELECT name FROM users ORDER BY age DESC LIMIT 2 OFFSET 1",
        "SELECT status, count(*), sum(total) FROM orders GROUP BY status ORDER BY status",
        "SELECT name FROM users WHERE id IN (1,3,5) ORDER BY id",
        "SELECT name FROM users WHERE id NOT IN (1,2) ORDER BY id",
        "SELECT name, age FROM users ORDER BY 2 DESC, 1",
        "SELECT sum(age) FROM users WHERE age > 100",
    ]

    @staticmethod
    def _norm(rows):
        out = []
        for r in rows:
            out.append(tuple(round(v, 6) if isinstance(v, float) else v for v in r))
        return out

    def test_queries_match_sqlite(self):
        for q in self.QUERIES:
            se = self._norm(self.sq.execute(q).fetchall())
            pe = self._norm(self.pg.execute(q).rows)
            if "ORDER BY" not in q.upper():
                se = sorted(se, key=str)
                pe = sorted(pe, key=str)
            self.assertEqual(se, pe, f"mismatch on: {q}")


# ----------------------------------------------------------------- REPL
class TestRepl(unittest.TestCase):
    def test_render_table(self):
        out = render_table(["id", "name"], [(1, "Ada"), (2, None)])
        self.assertIn("┌", out)
        self.assertIn("NULL", out)
        self.assertIn("(2 rows)", out)

    def test_take_complete(self):
        stmts, rem = _take_complete("SELECT 1; SELECT 2; SEL")
        self.assertEqual([s.strip() for s in stmts], ["SELECT 1", "SELECT 2"])
        self.assertEqual(rem.strip(), "SEL")
        # semicolon inside a string must not split
        stmts, rem = _take_complete("INSERT INTO t VALUES ('a;b');")
        self.assertEqual(len(stmts), 1)

    def test_parse_cell(self):
        self.assertEqual(_parse_cell(""), None)
        self.assertEqual(_parse_cell("42"), 42)
        self.assertEqual(_parse_cell("3.5"), 3.5)
        self.assertEqual(_parse_cell("hello"), "hello")


if __name__ == "__main__":
    unittest.main(verbosity=2)
