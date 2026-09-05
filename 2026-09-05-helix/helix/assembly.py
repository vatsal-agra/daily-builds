"""De novo genome assembly via de Bruijn graphs.

k-mers extracted from a set of noisy reads become a multigraph whose nodes
are (k-1)-mers and whose edges are k-mers; walking an Eulerian path through
that graph reconstructs the original sequence it was built from (Idury &
Waterman 1995 / Pevzner et al. 2001 — the algorithm behind SPAdes/Velvet-style
assemblers, in miniature).

Scope note: reads are assumed to already be presented in a single, consistent
orientation relative to the reference (this is what every introductory
treatment of de Bruijn assembly — e.g. Rosalind's own de Bruijn graph
problems — assumes too). A real double-stranded instrument's reads come from
both strands, which real assemblers handle with a *bidirected* graph (each
node enterable from either its own sequence or its reverse complement); that
traversal is a meaningfully harder algorithm in its own right and is out of
scope here. `helix.seq.simulate_reads(..., both_strands=True)` exists for
realistic FM-index resequencing input (module `fmindex.py`), where strand
genuinely doesn't matter, but assembly's own demo data is single-stranded.

Real sequencing reads are noisy, so three simplifications are applied before
attempting the walk, mirroring what real assemblers do:
  1. low-coverage k-mer filtering: an erroneous k-mer, introduced by a random
     per-base substitution, is extremely unlikely to recur identically
     across independent reads, so discarding k-mers seen fewer than
     `min_multiplicity` times removes almost all error-derived edges while
     keeping true edges (which recur ~coverage times).
  2. copy-number normalization: raw surviving counts still reflect *coverage
     depth*, not genomic repeat structure, so every edge weight is rescaled
     by the estimated single-copy coverage before the graph is used for
     anything topological (Eulerian-path degree balance, tip/bubble
     detection) — otherwise ordinary, correctly-covered edges would look
     like heavily-repeated ones simply because many reads observed them.
  3. tip clipping + bubble popping: short dead-end branches and short
     reconverging alternate paths (the two graph signatures a single
     leftover sequencing error produces, depending on whether it falls near
     a read's end or in its middle) are located and removed.

Pure Python 3 stdlib only.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field


class AssemblyError(ValueError):
    pass


@dataclass
class DeBruijnGraph:
    k: int
    # node -> Counter(neighbor -> multiplicity)
    edges: dict[str, Counter] = field(default_factory=dict)

    def nodes(self) -> set[str]:
        ns = set(self.edges.keys())
        for nbrs in self.edges.values():
            ns.update(nbrs.keys())
        return ns

    def out_degree(self, node: str) -> int:
        return sum(self.edges.get(node, {}).values())

    def in_degree(self, node: str) -> int:
        return sum(nbrs.get(node, 0) for nbrs in self.edges.values())

    def n_edges(self) -> int:
        return sum(sum(nbrs.values()) for nbrs in self.edges.values())

    def add_edge(self, u: str, v: str, count: int = 1) -> None:
        self.edges.setdefault(u, Counter())[v] += count

    def copy(self) -> "DeBruijnGraph":
        return DeBruijnGraph(self.k, {u: Counter(c) for u, c in self.edges.items()})


def extract_kmers(read: str, k: int) -> list[str]:
    if k < 2:
        raise AssemblyError("k must be >= 2")
    if len(read) < k:
        return []
    return [read[i:i + k] for i in range(len(read) - k + 1)]


def build_de_bruijn_graph(reads: list[str], k: int) -> DeBruijnGraph:
    """Build the multigraph of (k-1)-mer nodes / k-mer edges from a list of
    raw read strings (both strands are already expected to be present in
    `reads` where relevant — this function does not canonicalize strand)."""
    if not reads:
        raise AssemblyError("no reads given")
    counts: Counter[str] = Counter()
    for read in reads:
        counts.update(extract_kmers(read, k))
    graph = DeBruijnGraph(k)
    for kmer, c in counts.items():
        graph.add_edge(kmer[:-1], kmer[1:], c)
    return graph


def filter_low_coverage(graph: DeBruijnGraph, min_multiplicity: int = 2) -> DeBruijnGraph:
    """Drop edges (k-mers) seen fewer than `min_multiplicity` times — the
    standard k-mer-spectrum error filter."""
    out = DeBruijnGraph(graph.k)
    for u, nbrs in graph.edges.items():
        for v, c in nbrs.items():
            if c >= min_multiplicity:
                out.add_edge(u, v, c)
    return out


def estimate_coverage(graph: DeBruijnGraph) -> float:
    """Estimate the single-copy sequencing depth as the median raw k-mer
    count across all surviving edges. A repeat-free genome's true edges all
    cluster tightly around this value; a genuine repeat's edges cluster
    around an integer multiple of it."""
    weights = sorted(c for nbrs in graph.edges.values() for c in nbrs.values())
    if not weights:
        return 1.0
    mid = len(weights) // 2
    if len(weights) % 2 == 0:
        return (weights[mid - 1] + weights[mid]) / 2.0
    return float(weights[mid])


def normalize_to_copy_number(graph: DeBruijnGraph, coverage: float) -> DeBruijnGraph:
    """Rescale raw read-support counts (which conflate sequencing-depth
    redundancy with genuine genomic repeat copy number) down to an estimated
    genomic copy number per edge, by dividing by the estimated single-copy
    coverage. This is what makes the graph's edge multiset match the
    classical Eulerian-path formulation (edge multiplicity = number of times
    that k-mer truly occurs in the genome), rather than "number of reads
    that happened to observe it" — without it, every well-covered edge would
    look like a many-times-repeated one."""
    out = DeBruijnGraph(graph.k)
    for u, nbrs in graph.edges.items():
        for v, c in nbrs.items():
            mult = max(1, round(c / coverage)) if coverage > 0 else 1
            out.add_edge(u, v, mult)
    return out


def _reverse_edges(g: DeBruijnGraph) -> dict[str, "Counter"]:
    rev: dict[str, Counter] = {}
    for u, nbrs in g.edges.items():
        for v, c in nbrs.items():
            rev.setdefault(v, Counter())[u] += c
    return rev


def clip_tips(graph: DeBruijnGraph, max_tip_length: int) -> DeBruijnGraph:
    """Remove short "tips": a private (non-shared) run of nodes hanging off
    the main graph at one end, no longer than `max_tip_length` edges — the
    graph signature of a sequencing error near the very start or end of a
    read. A tip's free end has no counterpart at all (in-degree 0 for a
    source tip, out-degree 0 for a sink tip); its *other* end rejoins a node
    that has other, better-supported connections (that node's opposite
    degree is > 1 once you count both the tip and the main path) — that
    rejoining is what a naive "walk until a dead end" search misses, since
    the tip doesn't dead-end at all, it merges back in. Runs to a fixed
    point (bounded rounds), recomputing degrees fresh each round."""
    g = graph.copy()

    changed = True
    rounds = 0
    while changed and rounds < 50:
        changed = False
        rounds += 1

        def out_deg(n, _g=g):
            return sum(_g.edges.get(n, {}).values())

        rev = _reverse_edges(g)

        def in_deg(n, _rev=rev):
            return sum(_rev.get(n, {}).values())

        # Distinct-neighbor counts, for "did this merge into another
        # branch" checks — see the note in pop_bubbles on why total edge
        # multiplicity (out_deg/in_deg above) is the wrong quantity there.
        def distinct_out_deg(n, _g=g):
            return len(_g.edges.get(n, {}))

        def distinct_in_deg(n, _rev=rev):
            return len(_rev.get(n, {}))

        to_remove: list[tuple[str, str]] = []
        removed_nodes_as_start: set[str] = set()

        for n in list(g.nodes()):
            if n in removed_nodes_as_start:
                continue
            # --- source tip: nothing flows into n ---
            if in_deg(n) == 0 and out_deg(n) >= 1:
                path = [n]
                cur = n
                merged = False
                for _ in range(max_tip_length):
                    nbrs = list(g.edges.get(cur, {}).keys())
                    if len(nbrs) != 1:
                        break
                    nxt = nbrs[0]
                    path.append(nxt)
                    cur = nxt
                    if distinct_in_deg(cur) > 1:
                        merged = True
                        break
                    if out_deg(cur) == 0:
                        break
                if merged and len(path) - 1 <= max_tip_length:
                    for a, b in zip(path, path[1:]):
                        to_remove.append((a, b))
                    removed_nodes_as_start.add(n)
                    changed = True
                    continue
            # --- sink tip: nothing flows out of n ---
            if out_deg(n) == 0 and in_deg(n) >= 1:
                path = [n]
                cur = n
                merged = False
                for _ in range(max_tip_length):
                    preds = list(rev.get(cur, {}).keys())
                    if len(preds) != 1:
                        break
                    prev = preds[0]
                    path.append(prev)
                    cur = prev
                    if distinct_out_deg(cur) > 1:
                        merged = True
                        break
                    if in_deg(cur) == 0:
                        break
                if merged and len(path) - 1 <= max_tip_length:
                    rp = list(reversed(path))  # forward order: cur(merge) .. n
                    for a, b in zip(rp, rp[1:]):
                        to_remove.append((a, b))
                    changed = True

        for a, b in to_remove:
            if a in g.edges and b in g.edges[a]:
                del g.edges[a][b]
                if not g.edges[a]:
                    del g.edges[a]
    return g


def pop_bubbles(graph: DeBruijnGraph, max_bubble_length: int) -> DeBruijnGraph:
    """Collapse "bubbles": a branch point whose two (or more) outgoing
    simple paths reconverge at a common node within `max_bubble_length`
    steps. This is the graph signature of a single sequencing error in the
    *middle* of a read (which a dead-end tip-clip can't catch, since both
    the erroneous and the correct path continue on to rejoin the real
    sequence downstream) — the lower-coverage path is discarded, the
    higher-coverage one kept."""
    g = graph.copy()

    # Structural ("is this node a simple, private pass-through?") checks
    # must count DISTINCT neighbors, not total edge multiplicity — a node
    # with a single true predecessor of copy-number 2 (a real repeat) still
    # has exactly one distinct predecessor, and must not be mistaken for a
    # 2-way merge. Total weight (multiplicity) is used separately, purely
    # as the coverage-support signal for choosing which branch of an actual
    # bubble to keep.
    def distinct_out_deg(n):
        return len(g.edges.get(n, {}))

    def distinct_in_deg(n, _rev):
        return len(_rev.get(n, {}))

    changed = True
    rounds = 0
    while changed and rounds < 20:
        changed = False
        rounds += 1
        rev = _reverse_edges(g)
        for u in list(g.nodes()):
            branch_starts = list(g.edges.get(u, {}).keys())
            if len(branch_starts) < 2:
                continue
            branches = []  # (end_node, path_nodes, total_weight)
            for v0 in branch_starts:
                path = [u, v0]
                weight = g.edges[u][v0]
                cur = v0
                for _ in range(max_bubble_length - 1):
                    if distinct_out_deg(cur) != 1 or distinct_in_deg(cur, rev) != 1:
                        break
                    nxt = next(iter(g.edges.get(cur, {})))
                    weight += g.edges[cur][nxt]
                    path.append(nxt)
                    cur = nxt
                branches.append((cur, path, weight))
            groups: dict[str, list] = {}
            for end, path, weight in branches:
                if end == u:
                    continue
                groups.setdefault(end, []).append((path, weight))
            for end, blist in groups.items():
                if len(blist) < 2:
                    continue
                blist.sort(key=lambda t: t[1], reverse=True)
                for path, weight in blist[1:]:
                    for a, b in zip(path, path[1:]):
                        if a in g.edges and b in g.edges[a]:
                            del g.edges[a][b]
                            if not g.edges[a]:
                                del g.edges[a]
                            changed = True
    return g


def weakly_connected_components(graph: DeBruijnGraph) -> list[set[str]]:
    adj: dict[str, set[str]] = {}
    for u, nbrs in graph.edges.items():
        for v in nbrs:
            adj.setdefault(u, set()).add(v)
            adj.setdefault(v, set()).add(u)
    seen = set()
    comps = []
    for start in adj:
        if start in seen:
            continue
        comp = set()
        q = deque([start])
        seen.add(start)
        while q:
            n = q.popleft()
            comp.add(n)
            for nb in adj.get(n, ()):
                if nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        comps.append(comp)
    return comps


def subgraph(graph: DeBruijnGraph, node_set: set[str]) -> DeBruijnGraph:
    out = DeBruijnGraph(graph.k)
    for u, nbrs in graph.edges.items():
        if u not in node_set:
            continue
        for v, c in nbrs.items():
            if v in node_set:
                out.add_edge(u, v, c)
    return out


@dataclass
class EulerianCheck:
    ok: bool
    reason: str
    start: str | None = None
    circuit: bool = False


def check_eulerian_path(graph: DeBruijnGraph) -> EulerianCheck:
    """The classic existence theorem for a directed Eulerian path: the graph
    (restricted to non-isolated vertices) must be connected, and vertex
    out-degree - in-degree must be +1 at exactly one vertex (the start),
    -1 at exactly one vertex (the end), and 0 everywhere else — OR all zero
    everywhere, in which case an Eulerian CIRCUIT exists starting at any
    vertex with nonzero degree."""
    nodes = graph.nodes()
    if not nodes:
        return EulerianCheck(False, "empty graph")
    comps = weakly_connected_components(graph)
    if len(comps) != 1:
        return EulerianCheck(False, f"not connected: {len(comps)} components")
    plus_one = []
    minus_one = []
    other_bad = []
    for n in nodes:
        diff = graph.out_degree(n) - graph.in_degree(n)
        if diff == 1:
            plus_one.append(n)
        elif diff == -1:
            minus_one.append(n)
        elif diff != 0:
            other_bad.append((n, diff))
    if other_bad:
        return EulerianCheck(False, f"unbalanced vertices: {other_bad[:3]}")
    if len(plus_one) == 0 and len(minus_one) == 0:
        start = next(n for n in nodes if graph.out_degree(n) > 0)
        return EulerianCheck(True, "Eulerian circuit", start=start, circuit=True)
    if len(plus_one) == 1 and len(minus_one) == 1:
        return EulerianCheck(True, "Eulerian path", start=plus_one[0], circuit=False)
    return EulerianCheck(
        False,
        f"{len(plus_one)} vertices with out-in=+1, {len(minus_one)} with -1 "
        "(need exactly 0-and-0 or 1-and-1)",
    )


def hierholzer(graph: DeBruijnGraph, start: str) -> list[str]:
    """Hierholzer's algorithm, iterative (stack-based, no recursion limit
    issues on long genomes). Assumes `graph` genuinely has an Eulerian
    path/circuit starting at `start` — call check_eulerian_path first."""
    # Mutable per-node list of remaining out-neighbors (expanded by
    # multiplicity), consumed from the end (O(1) pop).
    remaining: dict[str, list[str]] = {}
    for u, nbrs in graph.edges.items():
        expanded = []
        for v, c in nbrs.items():
            expanded.extend([v] * c)
        remaining[u] = expanded

    stack = [start]
    path: list[str] = []
    while stack:
        v = stack[-1]
        outs = remaining.get(v)
        if outs:
            stack.append(outs.pop())
        else:
            path.append(stack.pop())
    path.reverse()
    return path


def path_to_sequence(path: list[str]) -> str:
    if not path:
        return ""
    if len(path) == 1:
        return path[0]
    return path[0] + "".join(node[-1] for node in path[1:])


def extract_unitigs(graph: DeBruijnGraph) -> list[list[str]]:
    """Fallback used when a component fails the Eulerian existence check
    (residual branching from uncorrected errors, or a genuine repeat): walk
    every maximal simple path through nodes of in/out-degree 1, so at least
    the unambiguous stretches are still reported as contigs rather than the
    whole component being silently dropped."""
    visited_edges: set[tuple[str, str, int]] = set()
    unitigs: list[list[str]] = []

    def edge_id_list(u):
        ids = []
        for v, c in graph.edges.get(u, {}).items():
            for i in range(c):
                ids.append((u, v, i))
        return ids

    all_edges = []
    for u in graph.edges:
        all_edges.extend(edge_id_list(u))

    def walk_forward(u, first_edge):
        path = [u]
        edge = first_edge
        while edge is not None:
            u2, v, _ = edge
            path.append(v)
            visited_edges.add(edge)
            if graph.out_degree(v) == 1 and graph.in_degree(v) == 1 and v != u:
                cands = [e for e in edge_id_list(v) if e not in visited_edges]
                edge = cands[0] if cands else None
            else:
                edge = None
        return path

    for e in all_edges:
        if e in visited_edges:
            continue
        u, v, _ = e
        # only start a new unitig at a "branch point" or true source, to
        # avoid starting mid-unitig (which would double-count internal
        # nodes into two overlapping unitigs).
        if graph.in_degree(u) == 1 and graph.out_degree(u) == 1:
            continue
        unitigs.append(walk_forward(u, e))

    # anything left over is a pure simple cycle with no branch point at all
    # (every node in/out-degree 1) — walk it starting anywhere.
    for e in all_edges:
        if e in visited_edges:
            continue
        u, v, _ = e
        unitigs.append(walk_forward(u, e))

    return unitigs


@dataclass
class AssemblyResult:
    contigs: list[str]
    k: int
    n_reads: int
    n_kmers_raw: int
    n_kmers_after_filter: int
    estimated_coverage: float
    components: list[dict]


def assemble(
    reads: list[str], k: int, *, min_multiplicity: int = 2,
    max_tip_length: int | None = None, max_bubble_length: int | None = None,
) -> AssemblyResult:
    """Assemble `reads` (same-orientation reads — see module docstring) into
    contigs via a de Bruijn graph of order k.

    A single substitution error corrupts every k-mer that overlaps it,
    which is up to k of them, so both `max_tip_length` and
    `max_bubble_length` default to a multiple of k rather than a small
    constant — a threshold shorter than k would leave most real
    single-error artifacts uncleaned.
    """
    if k < 3:
        raise AssemblyError("k must be >= 3")
    if max_tip_length is None:
        max_tip_length = k + 2
    if max_bubble_length is None:
        max_bubble_length = 2 * k + 5
    raw_graph = build_de_bruijn_graph(reads, k)
    n_kmers_raw = raw_graph.n_edges()
    graph = filter_low_coverage(raw_graph, min_multiplicity)
    coverage_est = estimate_coverage(graph)
    graph = normalize_to_copy_number(graph, coverage_est)
    graph = clip_tips(graph, max_tip_length)
    graph = pop_bubbles(graph, max_bubble_length)
    graph = clip_tips(graph, max_tip_length)
    n_kmers_after = graph.n_edges()

    contigs: list[str] = []
    components_info: list[dict] = []
    for comp in weakly_connected_components(graph):
        sub = subgraph(graph, comp)
        if sub.n_edges() == 0:
            continue
        check = check_eulerian_path(sub)
        if check.ok:
            path = hierholzer(sub, check.start)
            contigs.append(path_to_sequence(path))
            components_info.append({
                "n_nodes": len(comp), "eulerian": True,
                "circuit": check.circuit, "reason": check.reason,
            })
        else:
            unitigs = extract_unitigs(sub)
            for u in unitigs:
                if len(u) >= 2:
                    contigs.append(path_to_sequence(u))
            components_info.append({
                "n_nodes": len(comp), "eulerian": False,
                "reason": check.reason, "n_unitigs": len(unitigs),
            })

    contigs.sort(key=len, reverse=True)
    return AssemblyResult(
        contigs=contigs, k=k, n_reads=len(reads),
        n_kmers_raw=n_kmers_raw, n_kmers_after_filter=n_kmers_after,
        estimated_coverage=coverage_est, components=components_info,
    )


def reverse_complement(seq: str) -> str:
    table = str.maketrans("ACGTacgt", "TGCAtgca")
    return seq.translate(table)[::-1]


def contig_matches_reference(contig: str, reference: str) -> bool:
    """True if `contig` (or its reverse complement) reconstructs the entire
    `reference` exactly."""
    return contig == reference or reverse_complement(contig) == reference
