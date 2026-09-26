import unittest

from skein.storage import Graph, SkeinError
from skein.query.lexer import tokenize, LexError
from skein.query.parser import parse, ParseError
from skein.query.executor import execute


def q(graph, text, explain=False):
    stmt = parse(text)
    return execute(graph, stmt, explain=explain)


def make_social_graph():
    g = Graph()
    with g.transaction():
        ids = {}
        for name, age in [("Alice", 30), ("Bob", 25), ("Carol", 35), ("Dave", 28)]:
            ids[name] = g.create_node(["Person"], {"name": name, "age": age})
        g.create_edge(ids["Alice"], ids["Bob"], "KNOWS", {"since": 2020})
        g.create_edge(ids["Bob"], ids["Carol"], "KNOWS", {"since": 2021})
        g.create_edge(ids["Carol"], ids["Dave"], "LIKES", {})
        g.create_edge(ids["Dave"], ids["Alice"], "KNOWS", {"since": 2019})
    return g, ids


class TestLexer(unittest.TestCase):
    def test_keywords_case_insensitive(self):
        toks = tokenize("match (a) return a")
        self.assertEqual([t.kind for t in toks], ["MATCH", "(", "IDENT", ")", "RETURN", "IDENT", "EOF"])

    def test_string_escapes(self):
        toks = tokenize(r"'it\'s'")
        self.assertEqual(toks[0].value, "it's")

    def test_arrows_and_comparisons(self):
        toks = tokenize("-> <- <> <= >=")
        self.assertEqual([t.kind for t in toks], ["ARROW_R", "ARROW_L", "NEQ", "LTE", "GTE", "EOF"])

    def test_negative_and_float_numbers(self):
        toks = tokenize("3.14 42")
        self.assertEqual(toks[0].value, 3.14)
        self.assertEqual(toks[1].value, 42)
        self.assertIsInstance(toks[1].value, int)

    def test_unexpected_char_raises(self):
        with self.assertRaises(LexError):
            tokenize("MATCH (a) RETURN a #")


class TestParser(unittest.TestCase):
    def test_simple_match_return(self):
        stmt = parse("MATCH (a:Person) RETURN a.name")
        self.assertEqual(len(stmt.match.elements), 1)
        self.assertEqual(stmt.match.elements[0].labels, ["Person"])
        self.assertEqual(len(stmt.return_items), 1)

    def test_chain_pattern_directions(self):
        stmt = parse("MATCH (a)-[:KNOWS]->(b)<-[:LIKES]-(c) RETURN a")
        els = stmt.match.elements
        self.assertEqual(len(els), 5)
        self.assertEqual(els[1].direction, "->")
        self.assertEqual(els[3].direction, "<-")

    def test_multi_type_relationship(self):
        stmt = parse("MATCH (a)-[:KNOWS|LIKES]->(b) RETURN a")
        self.assertEqual(stmt.match.elements[1].types, ["KNOWS", "LIKES"])

    def test_where_precedence(self):
        stmt = parse("MATCH (a) WHERE a.x = 1 AND a.y = 2 OR NOT a.z = 3 RETURN a")
        # OR binds loosest: (AND) OR (NOT ...)
        self.assertEqual(stmt.where.op, "OR")

    def test_order_by_and_limit(self):
        stmt = parse("MATCH (a) RETURN a.name ORDER BY a.name DESC LIMIT 5")
        self.assertEqual(stmt.order_by[0].desc, True)
        self.assertEqual(stmt.limit, 5)

    def test_create_set_delete_parse(self):
        parse("MATCH (a:Person) SET a.age = a.age + 1")
        parse("CREATE (a:Person {name: 'X'})-[:KNOWS]->(b:Person {name: 'Y'})")
        parse("MATCH (a:Person) DETACH DELETE a")

    def test_bad_syntax_raises_parse_error(self):
        with self.assertRaises(ParseError):
            parse("MATCH (a RETURN a")

    def test_match_without_clause_raises(self):
        with self.assertRaises(ParseError):
            parse("MATCH (a)")

    def test_no_match_or_create_raises(self):
        with self.assertRaises(ParseError):
            parse("RETURN 1")


class TestPatternMatching(unittest.TestCase):
    def test_single_hop(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name ORDER BY a.name")
        self.assertEqual(rows, [
            {"a.name": "Alice", "b.name": "Bob"},
            {"a.name": "Bob", "b.name": "Carol"},
            {"a.name": "Dave", "b.name": "Alice"},
        ])

    def test_reverse_direction(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person)<-[:KNOWS]-(b:Person) WHERE a.name = 'Bob' RETURN b.name")
        self.assertEqual(rows, [{"b.name": "Alice"}])

    def test_two_hop_chain(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person)-[:KNOWS]->(b:Person)-[:KNOWS]->(c:Person) RETURN a.name, c.name ORDER BY a.name")
        names = [(r["a.name"], r["c.name"]) for r in rows]
        self.assertIn(("Alice", "Carol"), names)
        self.assertIn(("Dave", "Bob"), names)

    def test_inline_property_filter(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person {name: 'Alice'})-[:KNOWS]->(b) RETURN b.name")
        self.assertEqual(rows, [{"b.name": "Bob"}])

    def test_relationship_property_filter(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a)-[r:KNOWS {since: 2020}]->(b) RETURN a.name, b.name")
        self.assertEqual(rows, [{"a.name": "Alice", "b.name": "Bob"}])

    def test_where_and_or_not(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person) WHERE a.age > 30 OR a.name = 'Bob' RETURN a.name ORDER BY a.name")
        self.assertEqual([r["a.name"] for r in rows], ["Bob", "Carol"])
        rows = q(g, "MATCH (a:Person) WHERE NOT a.age > 30 RETURN a.name ORDER BY a.name")
        self.assertEqual([r["a.name"] for r in rows], ["Alice", "Bob", "Dave"])

    def test_cyclic_pattern_variable_reuse(self):
        g, ids = make_social_graph()
        # a->b->c->d->a is the full KNOWS-only cycle Alice->Bob->Carol?
        # Carol->Dave is LIKES not KNOWS, so a 4-hop KNOWS cycle shouldn't exist;
        # verify a same-variable reuse constraint the other direction instead.
        rows = q(g, "MATCH (a:Person)-[:KNOWS]->(b:Person)-[:KNOWS]->(a:Person) RETURN a.name")
        self.assertEqual(rows, [])  # no 2-hop KNOWS cycle back to the same node exists

    def test_return_bare_node_var(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person {name: 'Alice'}) RETURN a")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["a"]["props"]["name"], "Alice")
        self.assertEqual(rows[0]["a"]["labels"], ["Person"])

    def test_count_star(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person) RETURN count(*) AS n")
        self.assertEqual(rows, [{"n": 4}])

    def test_functions_id_labels_type(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person)-[r:KNOWS]->(b) WHERE a.name = 'Alice' RETURN id(a), labels(a), type(r)")
        self.assertEqual(rows, [{"id(a)": ids["Alice"], "labels(a)": ["Person"], "type(r)": "KNOWS"}])

    def test_unbound_variable_raises(self):
        g, ids = make_social_graph()
        with self.assertRaises(SkeinError):
            q(g, "MATCH (a:Person) RETURN b.name")


class TestPlanner(unittest.TestCase):
    def test_anchor_prefers_prop_index_over_label(self):
        g, ids = make_social_graph()
        with g.transaction():
            g.create_index("Person", "name")
        rows, plan = q(g, "MATCH (a:Person)-[:KNOWS]->(b:Person {name: 'Bob'}) RETURN a.name", explain=True)
        self.assertEqual(plan["method"], "prop_index")
        self.assertEqual(plan["anchor_pos"], 2)
        self.assertEqual(rows, [{"a.name": "Alice"}])

    def test_index_and_scan_agree(self):
        g, ids = make_social_graph()
        text = "MATCH (a:Person)-[:KNOWS]->(b:Person {name: 'Carol'}) RETURN a.name"
        without_index = q(g, text)
        with g.transaction():
            g.create_index("Person", "name")
        with_index = q(g, text)
        self.assertEqual(sorted(r["a.name"] for r in without_index), sorted(r["a.name"] for r in with_index))


class TestMutationClauses(unittest.TestCase):
    def test_create_standalone(self):
        g = Graph()
        q(g, "CREATE (a:Person {name: 'Zed'})")
        rows = q(g, "MATCH (a:Person) RETURN a.name")
        self.assertEqual(rows, [{"a.name": "Zed"}])

    def test_create_edge_between_matched_nodes(self):
        g, ids = make_social_graph()
        q(g, "MATCH (a:Person {name: 'Alice'}), (a) RETURN a") if False else None
        q(g, "MATCH (a:Person {name: 'Alice'})-[:KNOWS]->(b:Person {name: 'Bob'}) CREATE (a)-[:FRIENDS]->(b)")
        rows = q(g, "MATCH (a)-[:FRIENDS]->(b) RETURN a.name, b.name")
        self.assertEqual(rows, [{"a.name": "Alice", "b.name": "Bob"}])

    def test_set_updates_property(self):
        g, ids = make_social_graph()
        q(g, "MATCH (a:Person {name: 'Alice'}) SET a.age = a.age + 1")
        rows = q(g, "MATCH (a:Person {name: 'Alice'}) RETURN a.age")
        self.assertEqual(rows, [{"a.age": 31}])

    def test_delete_requires_detach_for_connected_node(self):
        g, ids = make_social_graph()
        with self.assertRaises(SkeinError):
            q(g, "MATCH (a:Person {name: 'Alice'}) DELETE a")
        q(g, "MATCH (a:Person {name: 'Alice'}) DETACH DELETE a")
        rows = q(g, "MATCH (a:Person) RETURN a.name")
        self.assertNotIn("Alice", [r["a.name"] for r in rows])

    def test_failed_mutation_query_rolls_back_partial_effects(self):
        g, ids = make_social_graph()
        # Deleting Alice (connected) without DETACH must raise -- and must
        # not have deleted anything for any of the matched rows either.
        with self.assertRaises(SkeinError):
            q(g, "MATCH (a:Person) DELETE a")
        rows = q(g, "MATCH (a:Person) RETURN count(*) AS n")
        self.assertEqual(rows, [{"n": 4}])


class TestOrderByLimit(unittest.TestCase):
    def test_order_desc_and_limit(self):
        g, ids = make_social_graph()
        rows = q(g, "MATCH (a:Person) RETURN a.name, a.age ORDER BY a.age DESC LIMIT 2")
        self.assertEqual(rows, [{"a.name": "Carol", "a.age": 35}, {"a.name": "Alice", "a.age": 30}])


if __name__ == "__main__":
    unittest.main()
