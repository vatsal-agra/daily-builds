"""Command-line entry point: `helix <subcommand> ...`.

Subcommands: align, phylo, assemble, index, search, simulate, demo.
"""
from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from helix.seq import (
    SequenceError, parse_fasta, random_genome, simulate_reads,
    reverse_complement, gc_content, write_fasta, FastaRecord,
)
from helix.align import global_align, local_align, AlignmentResult
from helix.phylo import distance_matrix, upgma, neighbor_joining, PhyloError
from helix.assembly import assemble as run_assembly, contig_matches_reference, AssemblyError
from helix.fmindex import FMIndex, FMIndexError, align_reads


def _die(msg: str) -> NoReturn:
    print(f"helix: error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _load_sequences_from_fasta(path: str) -> dict[str, str]:
    try:
        with open(path) as fh:
            text = fh.read()
        records = parse_fasta(text)
    except (OSError, SequenceError) as e:
        _die(str(e))
    seqs: dict[str, str] = {}
    for r in records:
        if r.header in seqs:
            _die(f"duplicate FASTA header {r.header!r} — every sequence needs a unique name")
        seqs[r.header] = r.sequence.upper()
    return seqs


def _load_single_sequence_from_fasta(path: str) -> str:
    """For commands that operate on exactly one reference genome: load a
    FASTA file and use its first record, warning loudly (not silently) if
    the file actually contains more than one."""
    seqs = _load_sequences_from_fasta(path)
    names = list(seqs)
    if len(names) > 1:
        print(
            f"helix: warning: {path} contains {len(names)} sequences; "
            f"using only the first ({names[0]!r}) — the other "
            f"{len(names) - 1} were ignored", file=sys.stderr,
        )
    return seqs[names[0]]


# ---------------------------------------------------------------------------
# align
# ---------------------------------------------------------------------------

def cmd_align(args: argparse.Namespace) -> None:
    seq_a, seq_b = args.seq_a.upper(), args.seq_b.upper()
    if not seq_a or not seq_b:
        _die("both --a and --b must be non-empty")
    fn = global_align if args.mode == "global" else local_align
    try:
        result: AlignmentResult = fn(
            seq_a, seq_b, match=args.match, mismatch=args.mismatch,
            gap_open=args.gap_open, gap_extend=args.gap_extend,
        )
    except ValueError as e:
        _die(str(e))
    print(f"mode:  {args.mode}")
    print(f"score: {result.score}")
    print(f"cigar: {result.cigar or '(empty)'}")
    if result.aligned_a:
        print()
        print(result.pretty())
    else:
        print("(no positive-scoring local alignment)")


# ---------------------------------------------------------------------------
# phylo
# ---------------------------------------------------------------------------

def cmd_phylo(args: argparse.Namespace) -> None:
    seqs = _load_sequences_from_fasta(args.fasta)
    if len(seqs) < 2:
        _die("need >= 2 sequences in the FASTA file")
    try:
        names, mat = distance_matrix(seqs, correction=args.correction)
        tree = upgma(names, mat) if args.method == "upgma" else neighbor_joining(names, mat)
    except PhyloError as e:
        _die(str(e))
    print(f"# {len(names)} taxa, method={args.method}, correction={args.correction}")
    print("# pairwise distance matrix:")
    header = "\t" + "\t".join(names)
    print(header)
    for i, name in enumerate(names):
        row = "\t".join(f"{mat[i][j]:.4f}" for j in range(len(names)))
        print(f"{name}\t{row}")
    print()
    print(tree.to_newick())


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

def cmd_assemble(args: argparse.Namespace) -> None:
    if args.fasta:
        genome = _load_single_sequence_from_fasta(args.fasta)
    else:
        genome = random_genome(args.genome_length, seed=args.seed)

    if args.read_length < args.k:
        _die(f"--read-length ({args.read_length}) must be >= --k ({args.k}) — "
             f"otherwise no read can even produce one k-mer")

    reads_obj = simulate_reads(
        genome, n_reads=args.n_reads, read_length=args.read_length,
        error_rate=args.error_rate, seed=args.seed + 1, both_strands=False,
    )
    reads = [r.sequence for r in reads_obj]
    try:
        result = run_assembly(reads, args.k, min_multiplicity=args.min_multiplicity)
    except AssemblyError as e:
        _die(str(e))

    print(f"genome length:      {len(genome)}")
    print(f"reads:              {len(reads)} (len={args.read_length}, "
          f"error_rate={args.error_rate}, est. coverage {args.n_reads*args.read_length/len(genome):.1f}x)")
    print(f"k:                  {args.k}")
    print(f"estimated coverage: {result.estimated_coverage:.1f}x (k-mer depth)")
    print(f"k-mers: raw={result.n_kmers_raw} after filter/normalize={result.n_kmers_after_filter}")
    print(f"contigs:            {len(result.contigs)}")
    lengths = sorted((len(c) for c in result.contigs), reverse=True)
    print(f"contig lengths (top 10): {lengths[:10]}")
    if result.contigs:
        best = result.contigs[0]
        exact = contig_matches_reference(best, genome)
        print(f"longest contig length {len(best)} / genome length {len(genome)} "
              f"({100*len(best)/len(genome):.1f}%)")
        print(f"longest contig reconstructs the FULL genome exactly: {exact}")
    for info in result.components:
        print(f"  component: {info}")


# ---------------------------------------------------------------------------
# index / search
# ---------------------------------------------------------------------------

def cmd_index(args: argparse.Namespace) -> None:
    if args.fasta:
        genome = _load_single_sequence_from_fasta(args.fasta)
    else:
        genome = random_genome(args.genome_length, seed=args.seed)
    try:
        idx = FMIndex(genome, checkpoint_interval=args.checkpoint_interval)
    except FMIndexError as e:
        _die(str(e))
    print(f"reference length: {len(genome)}")
    print(f"BWT (first 80 chars): {idx.bwt[:80]}{'...' if len(idx.bwt) > 80 else ''}")
    print(f"alphabet: {idx.alphabet}")
    if args.save_fasta:
        try:
            with open(args.save_fasta, "w") as fh:
                fh.write(write_fasta([FastaRecord("reference", genome)]))
        except OSError as e:
            _die(f"could not write {args.save_fasta}: {e}")
        print(f"wrote reference FASTA to {args.save_fasta}")


def cmd_search(args: argparse.Namespace) -> None:
    if args.fasta:
        genome = _load_single_sequence_from_fasta(args.fasta)
    else:
        genome = random_genome(args.genome_length, seed=args.seed)
    try:
        idx = FMIndex(genome, checkpoint_interval=args.checkpoint_interval)
        positions = idx.search(args.pattern.upper())
    except FMIndexError as e:
        _die(str(e))
    print(f"reference length: {len(genome)}")
    print(f"pattern: {args.pattern} (length {len(args.pattern)})")
    print(f"occurrences: {len(positions)}")
    print(f"positions: {positions}")


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------

def cmd_simulate(args: argparse.Namespace) -> None:
    genome = random_genome(args.genome_length, seed=args.seed)
    reads = simulate_reads(
        genome, n_reads=args.n_reads, read_length=args.read_length,
        error_rate=args.error_rate, seed=args.seed + 1, both_strands=args.both_strands,
    )
    print(f"genome length: {len(genome)} (GC content {gc_content(genome):.3f})")
    print(f"simulated {len(reads)} reads (read_length={args.read_length}, "
          f"error_rate={args.error_rate}, both_strands={args.both_strands})")
    total_errors = sum(r.n_errors for r in reads)
    print(f"total substitution errors introduced: {total_errors}")
    if args.out_fasta:
        try:
            with open(args.out_fasta, "w") as fh:
                fh.write(write_fasta([FastaRecord("reference", genome)]))
        except OSError as e:
            _die(f"could not write {args.out_fasta}: {e}")
        print(f"wrote reference to {args.out_fasta}")
    if args.out_reads_fasta:
        recs = [FastaRecord(r.read_id, r.sequence) for r in reads]
        try:
            with open(args.out_reads_fasta, "w") as fh:
                fh.write(write_fasta(recs))
        except OSError as e:
            _die(f"could not write {args.out_reads_fasta}: {e}")
        print(f"wrote {len(recs)} reads to {args.out_reads_fasta}")


# ---------------------------------------------------------------------------
# demo — a scripted end-to-end walkthrough of every required feature
# ---------------------------------------------------------------------------

def cmd_demo(args: argparse.Namespace) -> None:
    print("=" * 70)
    print("HELIX DEMO — pairwise alignment, phylogenetics, assembly, FM-index")
    print("=" * 70)

    print("\n--- 1. Pairwise alignment (Gotoh affine-gap global) ---")
    a, b = "GATTACAGATTACA", "GATCACAGATTAGA"
    r = global_align(a, b, match=2, mismatch=-1, gap_open=4, gap_extend=1)
    print(r.pretty())
    print(f"score={r.score} cigar={r.cigar}")

    print("\n--- 2. Phylogenetics (UPGMA + Neighbor-Joining) ---")
    seqs = {
        "human":     "ACGTACGTTGCATGCACGTAGCTAGCATGCA",
        "chimp":     "ACGTACGTTGCATCCACGTAGCTAGCATGCA",
        "gorilla":   "ACGTACCTTGCATGCACGTAGATAGCATGCA",
        "orangutan": "ACTTACGTTGCATGCACCTAGCTAGCATGCA",
    }
    names, mat = distance_matrix(seqs, correction="jc")
    tree = neighbor_joining(names, mat)
    print("Newick (Neighbor-Joining):", tree.to_newick())

    print("\n--- 3. De novo assembly (de Bruijn graph + Eulerian path) ---")
    genome = random_genome(2000, seed=42)
    reads = [r.sequence for r in simulate_reads(
        genome, n_reads=6000, read_length=120, error_rate=0.0, seed=1, both_strands=False,
    )]
    result = run_assembly(reads, k=25, min_multiplicity=2)
    best = result.contigs[0] if result.contigs else ""
    print(f"genome length {len(genome)}; assembled {len(result.contigs)} contig(s); "
          f"longest={len(best)}; exact full reconstruction={contig_matches_reference(best, genome)}")

    print("\n--- 4. FM-index short-read alignment ---")
    genome2 = random_genome(5000, seed=11)
    idx = FMIndex(genome2)
    reads2 = simulate_reads(genome2, n_reads=200, read_length=60, error_rate=0.0, seed=3, both_strands=True)
    aligned = align_reads(idx, [(r.read_id, r.sequence) for r in reads2])
    n_correct = sum(1 for a_, r in zip(aligned, reads2) if a_.mapped and r.true_start in a_.positions)
    print(f"{sum(1 for a_ in aligned if a_.mapped)}/{len(reads2)} reads mapped, "
          f"{n_correct}/{len(reads2)} at the true simulated position")

    print("\nDemo complete — all 4 required features exercised end-to-end.")


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="helix", description="A from-scratch computational biology toolkit.")
    sub = p.add_subparsers(dest="command", required=True)

    p_align = sub.add_parser("align", help="pairwise sequence alignment")
    p_align.add_argument("--a", dest="seq_a", required=True)
    p_align.add_argument("--b", dest="seq_b", required=True)
    p_align.add_argument("--mode", choices=["global", "local"], default="global")
    p_align.add_argument("--match", type=int, default=1)
    p_align.add_argument("--mismatch", type=int, default=-1)
    p_align.add_argument("--gap-open", type=int, default=5)
    p_align.add_argument("--gap-extend", type=int, default=1)
    p_align.set_defaults(func=cmd_align)

    p_phylo = sub.add_parser("phylo", help="build a phylogenetic tree from a FASTA of named sequences")
    p_phylo.add_argument("--fasta", required=True)
    p_phylo.add_argument("--method", choices=["upgma", "nj"], default="nj")
    p_phylo.add_argument("--correction", choices=["raw", "jc"], default="jc")
    p_phylo.set_defaults(func=cmd_phylo)

    p_asm = sub.add_parser("assemble", help="simulate reads from a genome and assemble them de novo")
    p_asm.add_argument("--fasta", help="reference FASTA (else a random genome is generated)")
    p_asm.add_argument("--genome-length", type=int, default=2000)
    p_asm.add_argument("--n-reads", type=int, default=2000)
    p_asm.add_argument("--read-length", type=int, default=120)
    p_asm.add_argument("--error-rate", type=float, default=0.01)
    p_asm.add_argument("--k", type=int, default=25)
    p_asm.add_argument("--min-multiplicity", type=int, default=2)
    p_asm.add_argument("--seed", type=int, default=0)
    p_asm.set_defaults(func=cmd_assemble)

    p_index = sub.add_parser("index", help="build an FM-index over a reference genome")
    p_index.add_argument("--fasta", help="reference FASTA (else a random genome is generated)")
    p_index.add_argument("--genome-length", type=int, default=2000)
    p_index.add_argument("--seed", type=int, default=0)
    p_index.add_argument("--checkpoint-interval", type=int, default=16)
    p_index.add_argument("--save-fasta", help="write the (possibly generated) reference to this path")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", help="exact FM-index search of a pattern against a reference")
    p_search.add_argument("--pattern", required=True)
    p_search.add_argument("--fasta", help="reference FASTA (else a random genome is generated)")
    p_search.add_argument("--genome-length", type=int, default=2000)
    p_search.add_argument("--seed", type=int, default=0)
    p_search.add_argument("--checkpoint-interval", type=int, default=16)
    p_search.set_defaults(func=cmd_search)

    p_sim = sub.add_parser("simulate", help="generate a random genome and simulated reads")
    p_sim.add_argument("--genome-length", type=int, default=2000)
    p_sim.add_argument("--n-reads", type=int, default=200)
    p_sim.add_argument("--read-length", type=int, default=100)
    p_sim.add_argument("--error-rate", type=float, default=0.01)
    p_sim.add_argument("--seed", type=int, default=0)
    p_sim.add_argument("--both-strands", action="store_true")
    p_sim.add_argument("--out-fasta")
    p_sim.add_argument("--out-reads-fasta")
    p_sim.set_defaults(func=cmd_simulate)

    p_demo = sub.add_parser("demo", help="run a scripted walkthrough of every required feature")
    p_demo.set_defaults(func=cmd_demo)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (SequenceError, PhyloError, AssemblyError, FMIndexError) as e:
        _die(str(e))


if __name__ == "__main__":
    main()
