import unittest

from trellis.depgraph import DependencyGraph


class TestDependencyGraph(unittest.TestCase):
    def test_set_precedents_updates_reverse_edges(self):
        g = DependencyGraph()
        g.set_precedents("B1", {"A1"})
        self.assertEqual(g.precedents_of("B1"), {"A1"})
        self.assertEqual(g.dependents_of("A1"), {"B1"})

    def test_reassigning_precedents_removes_stale_edges(self):
        g = DependencyGraph()
        g.set_precedents("B1", {"A1"})
        g.set_precedents("B1", {"C1"})
        self.assertEqual(g.precedents_of("B1"), {"C1"})
        self.assertEqual(g.dependents_of("A1"), set())
        self.assertEqual(g.dependents_of("C1"), {"B1"})

    def test_affected_closure_transitive(self):
        g = DependencyGraph()
        g.set_precedents("B1", {"A1"})
        g.set_precedents("C1", {"B1"})
        g.set_precedents("D1", {"C1"})
        self.assertEqual(g.affected_closure({"A1"}), {"A1", "B1", "C1", "D1"})

    def test_affected_closure_unrelated_cell_untouched(self):
        g = DependencyGraph()
        g.set_precedents("B1", {"A1"})
        g.set_precedents("Z1", {"Y1"})
        self.assertEqual(g.affected_closure({"A1"}), {"A1", "B1"})

    def test_topological_order_respects_edges(self):
        g = DependencyGraph()
        g.set_precedents("B1", {"A1"})
        g.set_precedents("C1", {"B1"})
        order = g.topological_order({"A1", "B1", "C1"})
        self.assertEqual(order.index("A1") < order.index("B1") < order.index("C1"), True)

    def test_topological_order_ignores_out_of_subset_precedent(self):
        g = DependencyGraph()
        g.set_precedents("B1", {"A1"})
        order = g.topological_order({"B1"})  # A1 not in subset -> not required
        self.assertEqual(order, ["B1"])

    def test_topological_order_raises_on_cycle(self):
        g = DependencyGraph()
        g.set_precedents("A1", {"B1"})
        g.set_precedents("B1", {"A1"})
        with self.assertRaises(ValueError):
            g.topological_order({"A1", "B1"})

    def test_find_cycles_two_node(self):
        g = DependencyGraph()
        g.set_precedents("A1", {"B1"})
        g.set_precedents("B1", {"A1"})
        self.assertEqual(g.find_cycles(), {"A1", "B1"})

    def test_find_cycles_self_loop(self):
        g = DependencyGraph()
        g.set_precedents("A1", {"A1"})
        self.assertEqual(g.find_cycles(), {"A1"})

    def test_find_cycles_none_in_acyclic_graph(self):
        g = DependencyGraph()
        g.set_precedents("B1", {"A1"})
        g.set_precedents("C1", {"B1"})
        self.assertEqual(g.find_cycles(), set())

    def test_remove_cell_cleans_both_directions(self):
        g = DependencyGraph()
        g.set_precedents("B1", {"A1"})
        g.remove_cell("B1")
        self.assertEqual(g.dependents_of("A1"), set())
        self.assertEqual(g.precedents_of("B1"), set())


if __name__ == "__main__":
    unittest.main()
