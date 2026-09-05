# Adversarial Review (Phase 3)

Methodology: attacked the Phase 2 build directly — fuzzed every DP/graph
algorithm against independent oracles, then went after the CLI with
deliberately hostile/degenerate inputs (zero/negative parameters, malformed
files, bad paths, saturating math) hunting for crashes, silent data loss,
and wrong-but-uncrashing output. Findings below are ordered roughly by
severity; every one was fixed and re-verified (see "Verification" at the
bottom).

## 1. `FMIndex(checkpoint_interval=0)` crashes; `checkpoint_interval<0` silently corrupts search results — CRITICAL

`checkpoint_interval=0` raises an uncaught `ZeroDivisionError` from deep
inside `__post_init__` (a raw Python traceback, not a clean error). Worse:
`checkpoint_interval=-3` doesn't crash at all — it *silently returns wrong
search results*. Confirmed directly:

```
idx = FMIndex(ref, checkpoint_interval=-3)
idx.search(ref[20:30])   # -> []  (WRONG — the pattern is right there at position 20)
naive_search(ref, ref[20:30])  # -> [20]
```

This is the worst class of bug an aligner can have: it doesn't error, it
lies. Root cause: negative modulo (`i % checkpoint_interval`) doesn't behave
like the code assumes, corrupting the checkpoint table's indexing silently.

**Fix:** `FMIndex.__post_init__` now validates `checkpoint_interval >= 1`
and raises `FMIndexError` otherwise. Regression test added
(`test_fmindex.py::test_rejects_bad_checkpoint_interval`) covering both 0
and negative values, plus the exact wrong-result reproduction above as a
differential check.

## 2. `assemble()` silently returns an empty result when every read is shorter than k

`assemble(reads, k=21)` with reads all shorter than 21 produces no
exception and no contigs, no error, nothing to indicate why — just a
quiet, useless `AssemblyResult(contigs=[], ...)`. This is exactly the kind
of failure a user (or an automated pipeline calling this as a library)
could easily miss, mistaking "no contigs" for "nothing assembled from a
repetitive genome" rather than "the read length was set wrong."

**Fix:** `build_de_bruijn_graph` now raises a clear `AssemblyError` when
zero k-mers could be extracted from the entire read set, naming k and
explaining every read was shorter than it. `cmd_assemble` also now
validates `read_length >= k` up front with an actionable CLI error before
running the (otherwise wasted) simulation.

## 3. `helix.phylo`: Jukes-Cantor saturation produces `NaN` branch lengths in Neighbor-Joining, silently

Two sequences with p-distance >= 0.75 correctly correct to `math.inf`
under Jukes-Cantor (documented, intentional). But feeding an `inf` distance
into Neighbor-Joining's `Q`-matrix arithmetic produces `inf - inf = nan`
part-way through, and NJ happily keeps going, emitting a tree with `nan`
branch lengths and no warning:

```
(c:inf,(a:nan,b:nan):inf);
```

A `nan` branch length is silently-wrong output, not a crash — worse than
an error, because a user has to notice the tree is nonsense on their own.

**Fix:** both `upgma` and `neighbor_joining` now validate every input
distance is finite up front and raise `PhyloError` with a specific,
actionable message ("use correction='raw', or drop/collapse the
too-divergent sequence pair") naming which pair of taxa produced the
non-finite distance, rather than silently propagating `inf`/`nan` through
the tree-building arithmetic.

## 4. CLI silently uses only the first record of a multi-sequence FASTA for `assemble`/`index`/`search`

`_load_sequences_from_fasta` correctly parses every record, but the
single-genome commands (`assemble`, `index`, `search`) always did
`next(iter(seqs.values()))` — silently discarding every record after the
first, with zero indication to the user. Confirmed: pointing `search` at a
2-record FASTA where the pattern only occurs in the *second* record
reports "0 occurrences" with no hint that an entire sequence was ignored.

**Fix:** these three commands now print an explicit warning to stderr
naming which record was used and how many were ignored, whenever the FASTA
file has more than one record.

## 5. `-0.0` branch lengths in Newick output for identical sequences

`jukes_cantor_distance(0.0)` returns `-0.0` (an IEEE-754 sign artifact of
`-0.75 * math.log(1.0)`), which is mathematically equal to zero but prints
as an ugly literal `-0` in Newick trees: `(c:-0,(a:-0,b:-0));`. Purely
cosmetic, but a from-scratch tool advertising exact, checkable output
shouldn't paper over its own arithmetic with a stray minus sign.

**Fix:** the source (`jukes_cantor_distance`) normalizes `-0.0` to `0.0`
before returning, and `_fmt` in `phylo.py` (the Newick number formatter)
defensively does the same regardless of source, so this class of artifact
can't resurface from some other floating-point path.

## 6. CLI file-write commands crash with a raw traceback on a bad output path

`simulate --out-fasta /nonexistent_dir/out.fasta` (and the equivalent
`--out-reads-fasta` / `index --save-fasta`) raised an uncaught
`FileNotFoundError` with a full Python traceback — after already having
printed successful-looking progress output above it, which is a
particularly confusing failure mode (looks like it worked, then explodes).

**Fix:** all three output-writing call sites are now wrapped and report a
clean `helix: error: ...` message via the same `_die` path used everywhere
else, with the correct exit code.

## 7. Minor: unresolvable `"NoReturn"` type annotation in `cli.py`

`_die(msg: str) -> "NoReturn":` referenced `typing.NoReturn` as a bare
string forward-reference without importing it — harmless at runtime (never
evaluated), but wrong/misleading code all the same.

**Fix:** imported `NoReturn` from `typing` properly.

## Scope note carried over from Phase 2 (not a bug, restated for visibility)

`helix.assembly` assumes reads are already presented in a single, consistent
orientation (see the module docstring) — it does not implement a bidirected
de Bruijn graph for mixed-strand read sets. This was a deliberate, upfront
scope decision (documented before any code was written), not something
discovered during review, but it's restated here because Phase 3 is where
a reviewer would otherwise flag it as a gap: real double-stranded
resequencing data would need the fuller bidirected-graph traversal to
assemble correctly, and that remains out of scope for this build.

## Verification

Every fix above has a dedicated regression test (in `test_fmindex.py`,
`test_assembly.py`, `test_phylo.py`, and `test_cli.py`) reproducing the
exact failing scenario from this review, plus the full existing suite was
re-run to confirm nothing broke. See the Phase 3 commit for the final test
count and a completely clean pass — a fresh run-through of every scenario
listed above now behaves correctly (clean error, correct result, or clean
warning, as appropriate) instead of crashing, corrupting output, or staying
silent.
