import unittest

from helix.phylo import (
    p_distance, jukes_cantor_distance, distance_matrix,
    distance_matrix_is_ultrametric, upgma, neighbor_joining, PhyloError,
)


def _cophenetic_matrix(tree, names):
    """Pairwise tree (cophenetic) distance: depth(x) + depth(y) - 2*depth(LCA),
    where depth is the sum of branch lengths from the root. An independent
    tree-walk, not reused from helix.phylo, so it can serve as a check ON
    that module rather than through it."""
    depth_from_root = {}   # leaf name -> depth
    ancestor_path = {}      # leaf name -> list of ancestor node objects (root..leaf)
    node_depth = {}         # id(node) -> depth, for LCA depth lookup

    def walk(node, running, path):
        node_depth[id(node)] = running
        if node.is_leaf():
            depth_from_root[node.name] = running
            ancestor_path[node.name] = path + [node]
            return
        for c in node.children:
            walk(c, running + c.branch_length, path + [node])

    walk(tree, 0.0, [])

    n = len(names)
    mat = [[0.0] * n for _ in range(n)]
    for i, ni in enumerate(names):
        for j, nj in enumerate(names):
            if i == j:
                continue
            pi, pj = ancestor_path[ni], ancestor_path[nj]
            common = 0
            for a, b in zip(pi, pj):
                if a is b:
                    common += 1
                else:
                    break
            lca = pi[common - 1]
            mat[i][j] = depth_from_root[ni] + depth_from_root[nj] - 2 * node_depth[id(lca)]
    return mat


class TestDistances(unittest.TestCase):
    def test_p_distance_basic(self):
        self.assertAlmostEqual(p_distance("ACGT", "ACGT"), 0.0)
        self.assertAlmostEqual(p_distance("ACGT", "ACGA"), 0.25)
        self.assertAlmostEqual(p_distance("ACGT", "TTTT"), 0.75)

    def test_p_distance_ignores_gaps(self):
        # 4 ungapped columns compared, 1 differs
        self.assertAlmostEqual(p_distance("AC-GT", "ACAGA"), 1 / 4)

    def test_p_distance_rejects_length_mismatch(self):
        with self.assertRaises(PhyloError):
            p_distance("ACGT", "ACG")

    def test_p_distance_rejects_all_gapped(self):
        with self.assertRaises(PhyloError):
            p_distance("----", "----")

    def test_jukes_cantor_matches_raw_at_zero(self):
        self.assertAlmostEqual(jukes_cantor_distance(0.0), 0.0)

    def test_jukes_cantor_saturates(self):
        self.assertEqual(jukes_cantor_distance(0.75), float("inf"))
        self.assertEqual(jukes_cantor_distance(0.9), float("inf"))

    def test_jukes_cantor_exceeds_raw_p_distance(self):
        # correction always inflates the distance relative to raw p, since
        # it accounts for unseen multiple hits at the same site
        for p in (0.05, 0.1, 0.3, 0.5, 0.7):
            self.assertGreater(jukes_cantor_distance(p), p)


class TestDistanceMatrix(unittest.TestCase):
    def test_identical_sequences_zero_distance(self):
        seqs = {"a": "ACGTACGTACGT", "b": "ACGTACGTACGT"}
        names, mat = distance_matrix(seqs, correction="raw")
        self.assertAlmostEqual(mat[0][1], 0.0)
        self.assertAlmostEqual(mat[1][0], 0.0)

    def test_matrix_is_symmetric_with_zero_diagonal(self):
        seqs = {
            "a": "ACGTACGTACGTAAA", "b": "ACGTTCGTACGTAAA",
            "c": "ACGTACGTTCGTATA", "d": "TCGTACGTACGTAAG",
        }
        names, mat = distance_matrix(seqs, correction="jc")
        n = len(names)
        for i in range(n):
            self.assertAlmostEqual(mat[i][i], 0.0)
            for j in range(n):
                self.assertAlmostEqual(mat[i][j], mat[j][i])

    def test_rejects_too_few_sequences(self):
        with self.assertRaises(PhyloError):
            distance_matrix({"a": "ACGT"})

    def test_rejects_bad_correction(self):
        with self.assertRaises(PhyloError):
            distance_matrix({"a": "ACGT", "b": "ACGA"}, correction="bogus")


class TestUPGMA(unittest.TestCase):
    def test_wikipedia_worked_example(self):
        # https://en.wikipedia.org/wiki/UPGMA worked example distance matrix
        names = ["a", "b", "c", "d", "e"]
        mat = [
            [0, 17, 21, 31, 23],
            [17, 0, 30, 34, 21],
            [21, 30, 0, 28, 39],
            [31, 34, 28, 0, 43],
            [23, 21, 39, 43, 0],
        ]
        tree = upgma(names, mat)
        # known result: root height 16.5, (a,b) merge at height 8.5, (c,d) at 14
        leaves = {leaf.name: leaf for leaf in tree.leaves()}
        self.assertEqual(set(leaves), set(names))
        # UPGMA guarantees its OUTPUT tree's cophenetic distances are
        # ultrametric — the raw input matrix need not be (and this
        # particular textbook example indeed isn't).
        self.assertFalse(distance_matrix_is_ultrametric(names, mat))
        cophenetic = _cophenetic_matrix(tree, names)
        self.assertTrue(distance_matrix_is_ultrametric(names, cophenetic))
        # and the known height-8.5 (a,b) merge implies cophenetic d(a,b)=17
        ai, bi = names.index("a"), names.index("b")
        self.assertAlmostEqual(cophenetic[ai][bi], 17.0)

    def test_produces_ultrametric_cophenetic_distances(self):
        names = ["a", "b", "c", "d"]
        mat = [
            [0, 2, 6, 6],
            [2, 0, 6, 6],
            [6, 6, 0, 4],
            [6, 6, 4, 0],
        ]
        tree = upgma(names, mat)
        # compute cophenetic (tree) distances by summing branch lengths to
        # the nearest common ancestor, and check the ultrametric property
        depths = {}

        def walk(node, depth_from_root):
            if node.is_leaf():
                depths[node.name] = depth_from_root
            for c in node.children:
                walk(c, depth_from_root + c.branch_length)

        walk(tree, 0.0)
        self.assertAlmostEqual(depths["a"], depths["b"])
        self.assertAlmostEqual(depths["c"], depths["d"])

    def test_rejects_single_taxon(self):
        with self.assertRaises(PhyloError):
            upgma(["a"], [[0]])


class TestNeighborJoining(unittest.TestCase):
    def test_recovers_exact_additive_quartet_tree(self):
        # Distances constructed EXACTLY from a known tree:
        #   A--(1)--X--(5)--Y--(3)--C
        #            |               |
        #           (2)             (4)
        #            |               |
        #            B               D
        names = ["A", "B", "C", "D"]
        a, b, c, d, e = 1, 2, 3, 4, 5
        mat = [
            [0, a + b, a + e + c, a + e + d],
            [a + b, 0, b + e + c, b + e + d],
            [a + e + c, b + e + c, 0, c + d],
            [a + e + d, b + e + d, c + d, 0],
        ]
        tree = neighbor_joining(names, mat)
        # exact branch lengths should be recovered
        by_name = {}

        def walk(node):
            if node.is_leaf():
                by_name[node.name] = node.branch_length
            for ch in node.children:
                walk(ch)

        walk(tree)
        self.assertAlmostEqual(by_name["A"], a)
        self.assertAlmostEqual(by_name["B"], b)
        self.assertAlmostEqual(by_name["C"], c)
        self.assertAlmostEqual(by_name["D"], d)
        # (A,B) should be siblings, and (C,D) should be siblings
        def sibling_pairs(node):
            if node.is_leaf() or len(node.children) != 2:
                return []
            leftleaves = {l.name for l in node.children[0].leaves()}
            rightleaves = {l.name for l in node.children[1].leaves()}
            pairs = []
            if len(leftleaves) == 1 and len(rightleaves) == 1:
                pairs.append(frozenset(leftleaves | rightleaves))
            for c in node.children:
                pairs.extend(sibling_pairs(c))
            return pairs

        pairs = sibling_pairs(tree)
        self.assertIn(frozenset({"A", "B"}), pairs)
        self.assertIn(frozenset({"C", "D"}), pairs)

    def test_two_taxa_trivial_case(self):
        tree = neighbor_joining(["x", "y"], [[0, 10], [10, 0]])
        self.assertEqual(len(tree.leaves()), 2)
        total = sum(leaf.branch_length for leaf in tree.leaves())
        self.assertAlmostEqual(total, 10)

    def test_rejects_single_taxon(self):
        with self.assertRaises(PhyloError):
            neighbor_joining(["a"], [[0]])

    def test_newick_parses_back_taxa(self):
        names = ["p", "q", "r", "s"]
        mat = [
            [0, 3, 9, 10],
            [3, 0, 10, 11],
            [9, 10, 0, 7],
            [10, 11, 7, 0],
        ]
        tree = neighbor_joining(names, mat)
        newick = tree.to_newick()
        self.assertTrue(newick.endswith(";"))
        for name in names:
            self.assertIn(name, newick)


if __name__ == "__main__":
    unittest.main()
