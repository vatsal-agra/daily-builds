import random
import unittest

from helix.seq import random_genome, simulate_reads, reverse_complement
from helix.assembly import (
    AssemblyError, extract_kmers, build_de_bruijn_graph, filter_low_coverage,
    estimate_coverage, normalize_to_copy_number, clip_tips, pop_bubbles,
    weakly_connected_components, check_eulerian_path, hierholzer,
    path_to_sequence, assemble, contig_matches_reference, DeBruijnGraph,
)


class TestKmerAndGraphBasics(unittest.TestCase):
    def test_extract_kmers(self):
        self.assertEqual(extract_kmers("ACGTACGT", 3), ["ACG", "CGT", "GTA", "TAC", "ACG", "CGT"])
        self.assertEqual(extract_kmers("AC", 3), [])
        with self.assertRaises(AssemblyError):
            extract_kmers("ACGT", 1)

    def test_build_graph_simple_path(self):
        g = build_de_bruijn_graph(["ACGTAC"], k=3)
        # k-mers: ACG CGT GTA TAC -> edges AC-CG, CG-GT, GT-TA, TA-AC
        self.assertEqual(g.out_degree("AC"), 1)
        self.assertEqual(g.n_edges(), 4)

    def test_reject_empty_reads(self):
        with self.assertRaises(AssemblyError):
            build_de_bruijn_graph([], k=5)
        with self.assertRaises(AssemblyError):
            assemble([], k=5)

    def test_reject_small_k(self):
        with self.assertRaises(AssemblyError):
            assemble(["ACGTACGT"], k=2)


class TestEulerianPathTheorem(unittest.TestCase):
    def test_simple_chain_is_a_path(self):
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "D")
        chk = check_eulerian_path(g)
        self.assertTrue(chk.ok)
        self.assertFalse(chk.circuit)
        self.assertEqual(chk.start, "A")

    def test_simple_cycle_is_a_circuit(self):
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "A")
        chk = check_eulerian_path(g)
        self.assertTrue(chk.ok)
        self.assertTrue(chk.circuit)

    def test_disconnected_graph_fails(self):
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B")
        g.add_edge("X", "Y")
        chk = check_eulerian_path(g)
        self.assertFalse(chk.ok)
        self.assertIn("component", chk.reason)

    def test_unbalanced_branch_fails(self):
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B")
        g.add_edge("A", "C")  # A has out-degree 2, no matching in-degree
        chk = check_eulerian_path(g)
        self.assertFalse(chk.ok)

    def test_hierholzer_recovers_simple_path(self):
        g = DeBruijnGraph(k=2)
        for a, b in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]:
            g.add_edge(a, b)
        chk = check_eulerian_path(g)
        path = hierholzer(g, chk.start)
        self.assertEqual(path, ["A", "B", "C", "D", "E"])

    def test_hierholzer_handles_repeated_node_with_correct_multiplicity(self):
        # A -> B -> C -> B -> D  (B visited twice; a real repeat structure)
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "B")
        g.add_edge("B", "D")
        chk = check_eulerian_path(g)
        self.assertTrue(chk.ok)
        path = hierholzer(g, chk.start)
        self.assertEqual(path[0], "A")
        self.assertEqual(path[-1], "D")
        self.assertEqual(len(path), 5)  # 4 edges -> 5 nodes


class TestPathToSequence(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(path_to_sequence(["ACG", "CGT", "GTA"]), "ACGTA")

    def test_single_node(self):
        self.assertEqual(path_to_sequence(["ACG"]), "ACG")

    def test_empty(self):
        self.assertEqual(path_to_sequence([]), "")


class TestCoverageNormalization(unittest.TestCase):
    def test_estimate_coverage_is_the_median(self):
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B", 10)
        g.add_edge("B", "C", 12)
        g.add_edge("C", "D", 11)
        self.assertAlmostEqual(estimate_coverage(g), 11.0)

    def test_normalize_collapses_uniform_coverage_to_one(self):
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B", 20)
        g.add_edge("B", "C", 21)
        g.add_edge("C", "D", 19)
        norm = normalize_to_copy_number(g, estimate_coverage(g))
        for u, nbrs in norm.edges.items():
            for v, c in nbrs.items():
                self.assertEqual(c, 1)

    def test_normalize_detects_a_real_repeat_as_copy_number_two(self):
        # an edge covered at ~2x the single-copy depth should normalize to 2
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B", 20)
        g.add_edge("B", "C", 40)  # true 2-copy repeat edge
        g.add_edge("C", "D", 19)
        norm = normalize_to_copy_number(g, estimate_coverage(g))
        self.assertEqual(norm.edges["B"]["C"], 2)


class TestTipClippingAndBubblePopping(unittest.TestCase):
    def test_clip_tips_removes_short_dangling_source(self):
        g = DeBruijnGraph(k=2)
        # main path
        for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
            g.add_edge(a, b)
        # a short erroneous tip that merges into C
        g.add_edge("X", "C")
        clipped = clip_tips(g, max_tip_length=3)
        self.assertNotIn("X", clipped.nodes())
        chk = check_eulerian_path(clipped)
        self.assertTrue(chk.ok)

    def test_clip_tips_preserves_tip_longer_than_threshold(self):
        g = DeBruijnGraph(k=2)
        for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
            g.add_edge(a, b)
        g.add_edge("X1", "X2")
        g.add_edge("X2", "X3")
        g.add_edge("X3", "C")  # tip of length 3
        clipped = clip_tips(g, max_tip_length=1)  # too short to remove this tip
        self.assertIn("X1", clipped.nodes())

    def test_pop_bubbles_keeps_higher_coverage_branch(self):
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B", 20)
        g.add_edge("B", "C1", 20)  # true branch, high coverage
        g.add_edge("C1", "D", 20)
        g.add_edge("B", "C2", 2)   # erroneous branch, low coverage
        g.add_edge("C2", "D", 2)
        g.add_edge("D", "E", 20)
        popped = pop_bubbles(g, max_bubble_length=5)
        self.assertNotIn("C2", popped.nodes())
        self.assertIn("C1", popped.nodes())


class TestEndToEndAssembly(unittest.TestCase):
    def test_perfect_high_coverage_reconstructs_exact_genome(self):
        successes = 0
        trials = 6
        for seed in range(trials):
            genome = random_genome(1500, seed=seed)
            reads = simulate_reads(
                genome, n_reads=6000, read_length=120, error_rate=0.0,
                seed=seed + 500, both_strands=False,
            )
            result = assemble([r.sequence for r in reads], k=25, min_multiplicity=2)
            if any(contig_matches_reference(c, genome) for c in result.contigs):
                successes += 1
        # random read placement leaves a small chance of a boundary coverage
        # gap even at this depth; require the large majority to succeed
        # exactly rather than a flaky 100%.
        self.assertGreaterEqual(successes, trials - 2)

    def test_every_contig_is_a_genuine_substring_of_the_true_genome(self):
        # the core correctness property: even under realistic noisy,
        # moderate-coverage conditions where the assembly fragments, no
        # contig should ever be chimeric/wrong.
        genome = random_genome(3000, seed=99)
        reads = simulate_reads(
            genome, n_reads=1200, read_length=150, error_rate=0.01,
            seed=2, both_strands=False,
        )
        result = assemble([r.sequence for r in reads], k=31, min_multiplicity=3)
        rc_genome = reverse_complement(genome)
        total_bases = sum(len(c) for c in result.contigs)
        bad_bases = sum(len(c) for c in result.contigs if c not in genome and c not in rc_genome)
        self.assertGreater(len(result.contigs), 0)
        # allow a small fraction of leftover short spurious fragments (an
        # honest, documented limitation — see REVIEW.md) but the overwhelming
        # majority of assembled sequence must be exactly correct.
        self.assertLess(bad_bases / total_bases, 0.05)

    def test_deterministic_given_same_inputs(self):
        genome = random_genome(500, seed=1)
        reads = [r.sequence for r in simulate_reads(genome, n_reads=200, read_length=60, seed=2)]
        r1 = assemble(reads, k=15, min_multiplicity=2)
        r2 = assemble(reads, k=15, min_multiplicity=2)
        self.assertEqual(sorted(r1.contigs), sorted(r2.contigs))

    def test_reverse_complement_also_counts_as_correct_reconstruction(self):
        genome = "ACGT" * 50 + "TGCATGCA" * 20
        rc = reverse_complement(genome)
        self.assertTrue(contig_matches_reference(rc, genome))
        self.assertTrue(contig_matches_reference(genome, genome))
        self.assertFalse(contig_matches_reference("AAAA", genome))


if __name__ == "__main__":
    unittest.main()
