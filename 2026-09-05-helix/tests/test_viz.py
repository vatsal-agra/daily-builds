import re
import unittest

from helix.assembly import DeBruijnGraph, assemble, build_de_bruijn_graph
from helix.phylo import distance_matrix, neighbor_joining, upgma
from helix.variants import PileupColumn, Variant
from helix.viz import (
    render_alignment_svg, render_dendrogram_svg, render_assembly_graph_svg,
    render_pileup_svg, build_report_html,
)


def _assert_no_double_escaped_entities(test, html_str):
    # REVIEW.md-style regression: "&middot;" written directly into an
    # f-string must never itself get run through html.escape() a second
    # time, or it turns into the literal text "&amp;middot;".
    test.assertNotIn("&amp;middot;", html_str)
    test.assertNotIn("&amp;nbsp;", html_str)
    test.assertNotIn("&amp;#", html_str)


class TestAlignmentViz(unittest.TestCase):
    def test_renders_valid_svg_with_highlighted_path(self):
        html_str = render_alignment_svg("GATTACA", "GATCACA", match=2, mismatch=-1, gap_open=4, gap_extend=1)
        self.assertIn("<svg", html_str)
        self.assertIn("</svg>", html_str)
        _assert_no_double_escaped_entities(self, html_str)
        # every base of both sequences should appear as a row/column label
        for ch in "GATTACA":
            self.assertIn(f">{ch}<", html_str)

    def test_local_mode_renders(self):
        html_str = render_alignment_svg("AAAGATTACAAAA", "GGGGATTACAGGGG", mode="local", gap_open=5, gap_extend=1)
        self.assertIn("<svg", html_str)
        _assert_no_double_escaped_entities(self, html_str)


class TestDendrogramViz(unittest.TestCase):
    def test_renders_all_leaf_labels_uncut(self):
        seqs = {
            "human": "ACGTACGTTGCATGCACGTAGCTAGCATGCA",
            "chimp": "ACGTACGTTGCATCCACGTAGCTAGCATGCA",
            "orangutan": "ACTTACGTTGCATGCACCTAGCTAGCATGCA",
        }
        names, mat = distance_matrix(seqs, correction="jc")
        tree = neighbor_joining(names, mat)
        html_str = render_dendrogram_svg(tree, method_label="Neighbor-Joining")
        _assert_no_double_escaped_entities(self, html_str)
        for name in names:
            self.assertIn(f">{name}<", html_str)
        # the SVG width must actually fit the longest label (regression:
        # labels used to be clipped by a fixed right-padding).
        width = int(re.search(r'width="(\d+)"', html_str).group(1))
        longest = max(len(n) for n in names)
        self.assertGreater(width, 140 + 480 + longest * 6)

    def test_upgma_tree_also_renders(self):
        names = ["a", "b", "c", "d"]
        mat = [[0, 2, 6, 6], [2, 0, 6, 6], [6, 6, 0, 4], [6, 6, 4, 0]]
        tree = upgma(names, mat)
        html_str = render_dendrogram_svg(tree, method_label="UPGMA")
        self.assertIn("<svg", html_str)
        _assert_no_double_escaped_entities(self, html_str)

    def test_html_special_characters_in_label_are_escaped(self):
        html_str = render_dendrogram_svg(
            neighbor_joining(["a", "b"], [[0, 4], [4, 0]]), method_label="<script>",
        )
        self.assertNotIn("<script>", html_str.split("<svg")[0].replace("&lt;script&gt;", ""))
        self.assertIn("&lt;script&gt;", html_str)


class TestAssemblyGraphViz(unittest.TestCase):
    def test_clean_single_path_renders_one_segment(self):
        g = DeBruijnGraph(k=2)
        for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
            g.add_edge(a, b)
        html_str = render_assembly_graph_svg(g)
        self.assertIn("1 segment(s)", html_str)
        _assert_no_double_escaped_entities(self, html_str)

    def test_branching_graph_shows_multiple_junctions(self):
        g = DeBruijnGraph(k=2)
        g.add_edge("A", "B")
        g.add_edge("B", "C1")
        g.add_edge("B", "C2")
        html_str = render_assembly_graph_svg(g)
        # A (source), B (the real branch point), C1 and C2 (both tips) -> 4
        self.assertIn("4 junction(s)", html_str)
        self.assertIn("3 segment(s)", html_str)
        _assert_no_double_escaped_entities(self, html_str)
        # regression: B's two children used to collide onto the same row
        # (same y-coordinate), rendering as one indistinguishable line
        # instead of two. Every rendered node position must be unique.
        positions = re.findall(r'<circle cx="(-?\d+)" cy="(-?\d+)"', html_str)
        self.assertEqual(len(positions), len(set(positions)),
                          f"two junctions rendered at the same position: {positions}")

    def test_real_assembly_run_renders_without_crashing(self):
        from helix.seq import random_genome, simulate_reads
        genome = random_genome(300, seed=1)
        reads = [r.sequence for r in simulate_reads(genome, n_reads=30, read_length=50, error_rate=0.02, seed=2, both_strands=False)]
        graph = build_de_bruijn_graph(reads, k=15)
        html_str = render_assembly_graph_svg(graph)
        self.assertIn("<svg", html_str)
        _assert_no_double_escaped_entities(self, html_str)

    def test_single_node_no_edges_component_does_not_crash(self):
        # a graph with an isolated node and no edges at all is a degenerate
        # but real possibility after aggressive filtering.
        g = DeBruijnGraph(k=2)
        html_str = render_assembly_graph_svg(g)
        self.assertIn("<svg", html_str)


class TestPileupViz(unittest.TestCase):
    def test_renders_reads_and_variant_markers(self):
        ref = "ACGTACGTACGTACGT"
        reads = [(0, "ACGT"), (4, "TCGT"), (8, "ACGT")]  # mismatch at position 4
        variants = [Variant(4, "A", "T", 0, 1, 1, 1.0)]
        html_str = render_pileup_svg(ref, reads, variants, window=(0, 16))
        self.assertIn("<svg", html_str)
        self.assertIn("1 variant(s)", html_str)
        _assert_no_double_escaped_entities(self, html_str)

    def test_no_reads_no_variants_still_renders(self):
        html_str = render_pileup_svg("ACGTACGT", [], [], window=(0, 8))
        self.assertIn("<svg", html_str)
        self.assertIn("0 variant(s)", html_str)

    def test_reads_outside_window_are_excluded(self):
        ref = "A" * 100
        reads = [(0, "AAAA"), (90, "AAAA")]
        html_str = render_pileup_svg(ref, reads, [], window=(50, 60))
        self.assertIn("0 reads shown", html_str)


class TestReportShell(unittest.TestCase):
    def test_builds_valid_html_with_all_tabs(self):
        sections = [
            ("a", "Tab A", "<p>content a</p>"),
            ("b", "Tab B", "<p>content b</p>"),
        ]
        report = build_report_html(sections, title="Test Report")
        self.assertTrue(report.startswith("<!doctype html>"))
        self.assertIn("Test Report", report)
        self.assertIn('data-tab="a"', report)
        self.assertIn('id="tab-b"', report)
        self.assertIn("content a", report)
        self.assertIn("content b", report)

    def test_title_is_escaped(self):
        report = build_report_html([("a", "A", "x")], title="<script>alert(1)</script>")
        self.assertNotIn("<script>alert", report)
        self.assertIn("&lt;script&gt;", report)


if __name__ == "__main__":
    unittest.main()
