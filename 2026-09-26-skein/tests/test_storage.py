import os
import shutil
import struct
import tempfile
import unittest

from skein.storage import Graph, SkeinError, TransactionError


class TempDirMixin:
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="skein_test_")
        self.path = os.path.join(self.tmpdir, "db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestInMemoryMutations(unittest.TestCase):
    def test_create_and_read_node(self):
        g = Graph()
        with g.transaction():
            nid = g.create_node(["Person"], {"name": "Alice"})
        node = g.get_node(nid)
        self.assertEqual(node.labels, frozenset({"Person"}))
        self.assertEqual(node.props["name"], "Alice")

    def test_mutation_outside_transaction_raises(self):
        g = Graph()
        with self.assertRaises(TransactionError):
            g.create_node(["Person"], {})

    def test_create_edge_requires_existing_nodes(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["Person"], {})
        with self.assertRaises(SkeinError):
            with g.transaction():
                g.create_edge(a, 9999, "KNOWS", {})

    def test_delete_node_with_edges_requires_detach(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["Person"], {})
            b = g.create_node(["Person"], {})
            g.create_edge(a, b, "KNOWS", {})
        with self.assertRaises(SkeinError):
            with g.transaction():
                g.delete_node(a)
        # node must still exist after the failed delete
        self.assertIn(a, g.nodes)
        with g.transaction():
            g.delete_node(a, detach=True)
        self.assertNotIn(a, g.nodes)
        self.assertEqual(len(g.edges), 0)

    def test_set_and_unset_prop(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["Person"], {})
            g.set_node_prop(a, "age", 30)
        self.assertEqual(g.nodes[a].props["age"], 30)
        with g.transaction():
            g.set_node_prop(a, "age", 31)
        self.assertEqual(g.nodes[a].props["age"], 31)

    def test_rollback_undoes_create(self):
        g = Graph()
        g.begin()
        a = g.create_node(["Person"], {"name": "Ghost"})
        self.assertIn(a, g.nodes)
        g.rollback()
        self.assertNotIn(a, g.nodes)
        self.assertEqual(g.label_index.get("Person"), frozenset())

    def test_rollback_undoes_delete(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["Person"], {"name": "Alice"})
        g.begin()
        g.delete_node(a)
        self.assertNotIn(a, g.nodes)
        g.rollback()
        self.assertIn(a, g.nodes)
        self.assertEqual(g.nodes[a].props["name"], "Alice")

    def test_rollback_undoes_set_prop_to_previous_value(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["Person"], {"age": 1})
        g.begin()
        g.set_node_prop(a, "age", 2)
        g.rollback()
        self.assertEqual(g.nodes[a].props["age"], 1)

    def test_exception_inside_transaction_context_rolls_back(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["Person"], {})
        try:
            with g.transaction():
                g.set_node_prop(a, "age", 99)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertNotIn("age", g.nodes[a].props)

    def test_nested_transactions_flatten(self):
        g = Graph()
        g.begin()
        g.begin()
        a = g.create_node(["Person"], {})
        g.commit()  # inner commit: no-op at the WAL level
        self.assertIn(a, g.nodes)
        g.commit()  # outer commit: actually flushes
        self.assertIn(a, g.nodes)

    def test_double_commit_raises(self):
        g = Graph()
        g.begin()
        g.commit()
        with self.assertRaises(TransactionError):
            g.commit()


class TestPropertyIndexMaintenance(unittest.TestCase):
    def test_index_created_after_data_backfills(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["Person"], {"name": "Alice"})
            b = g.create_node(["Person"], {"name": "Bob"})
            g.create_index("Person", "name")
        idx = g.prop_indexes[("Person", "name")]
        self.assertEqual(sorted(idx.eq("Alice")), [a])
        self.assertEqual(sorted(idx.eq("Bob")), [b])

    def test_index_tracks_set_prop(self):
        g = Graph()
        with g.transaction():
            g.create_index("Person", "age")
            a = g.create_node(["Person"], {"age": 10})
        idx = g.prop_indexes[("Person", "age")]
        self.assertEqual(idx.eq(10), [a])
        with g.transaction():
            g.set_node_prop(a, "age", 20)
        self.assertEqual(idx.eq(10), [])
        self.assertEqual(idx.eq(20), [a])

    def test_index_tracks_delete(self):
        g = Graph()
        with g.transaction():
            g.create_index("Person", "age")
            a = g.create_node(["Person"], {"age": 10})
        with g.transaction():
            g.delete_node(a)
        idx = g.prop_indexes[("Person", "age")]
        self.assertEqual(idx.eq(10), [])

    def test_range_query(self):
        g = Graph()
        with g.transaction():
            g.create_index("Person", "age")
            ids = [g.create_node(["Person"], {"age": age}) for age in [10, 20, 30, 40, 50]]
        idx = g.prop_indexes[("Person", "age")]
        self.assertEqual(sorted(idx.range(gt=20, lte=40)), sorted([ids[2], ids[3]]))


class TestDurability(TempDirMixin, unittest.TestCase):
    def test_reopen_after_clean_close(self):
        g = Graph(self.path)
        with g.transaction():
            a = g.create_node(["Person"], {"name": "Alice"})
            b = g.create_node(["Person"], {"name": "Bob"})
            g.create_edge(a, b, "KNOWS", {"since": 2020})
        g.close()

        g2 = Graph(self.path)
        self.assertEqual(len(g2.nodes), 2)
        self.assertEqual(len(g2.edges), 1)
        names = sorted(n.props["name"] for n in g2.nodes.values())
        self.assertEqual(names, ["Alice", "Bob"])
        g2.close()

    def test_checkpoint_truncates_wal_but_preserves_state(self):
        g = Graph(self.path)
        with g.transaction():
            g.create_node(["Person"], {"name": "Alice"})
        g.checkpoint()
        self.assertEqual(os.path.getsize(g._wal_path), 0)
        with g.transaction():
            g.create_node(["Person"], {"name": "Bob"})
        g.close()
        g2 = Graph(self.path)
        self.assertEqual(len(g2.nodes), 2)
        g2.close()

    def test_uncommitted_transaction_never_reaches_disk(self):
        g = Graph(self.path)
        g.begin()
        g.create_node(["Person"], {"name": "Ghost"})
        # No commit -- simulate the process vanishing here.
        del g

        g2 = Graph(self.path)
        self.assertEqual(len(g2.nodes), 0)
        g2.close()

    def test_torn_write_at_wal_tail_is_dropped_on_recovery(self):
        """A crash mid-fsync can leave a partially-written final WAL
        record. Recovery must discard only that torn tail, keeping every
        previously *complete* committed transaction.
        """
        g = Graph(self.path)
        with g.transaction():
            g.create_node(["Person"], {"name": "Alice"})
        g.close()

        with g.transaction():
            g.create_node(["Person"], {"name": "Bob"})
        # Truncate the WAL file to simulate a crash partway through the
        # second transaction's write (after `begin()`, mid `create_node`).
        with open(g._wal_path, "r+b") as f:
            f.truncate(max(0, os.path.getsize(g._wal_path) - 5))

        g2 = Graph(self.path)
        names = sorted(n.props["name"] for n in g2.nodes.values())
        self.assertEqual(names, ["Alice"], "a torn commit must not resurrect a partial transaction")
        g2.close()

    def test_indexes_persist_across_reopen(self):
        g = Graph(self.path)
        with g.transaction():
            g.create_node(["Person"], {"name": "Alice"})
            g.create_index("Person", "name")
        g.close()
        g2 = Graph(self.path)
        self.assertIn(("Person", "name"), g2.prop_indexes)
        self.assertEqual(len(g2.prop_indexes[("Person", "name")]), 1)
        g2.close()

    def test_rollback_never_written_to_wal(self):
        g = Graph(self.path)
        g.begin()
        g.create_node(["Person"], {"name": "Ghost"})
        g.rollback()
        with g.transaction():
            g.create_node(["Person"], {"name": "Real"})
        g.close()
        g2 = Graph(self.path)
        names = sorted(n.props["name"] for n in g2.nodes.values())
        self.assertEqual(names, ["Real"])
        g2.close()


if __name__ == "__main__":
    unittest.main()
