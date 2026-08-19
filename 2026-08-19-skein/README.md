# Skein

A from-scratch CRDT (Conflict-free Replicated Data Type) for real-time
collaborative text editing — the algorithm family behind modern
collaborative tools (Yjs, Automerge) and, historically, Google Docs'
operational transformation — with a simulated unreliable network, a
multi-site concurrent-edit simulator, a randomized convergence-proof
harness, per-site undo/redo, and an interactive multi-user playground.

## What it is

Three (or more) independent replicas of a document, each able to edit
freely at any time — including while completely cut off from every
other replica — that always converge to the identical document once
their edits reach each other, **without a leader, a vote, or a central
server deciding whose edit wins.** That's Strong Eventual Consistency,
and it's the actual algorithm behind real collaborative editors, not a
simplification of one.

The core is an **RGA (Replicated Growable Array)**: every character
ever typed gets a globally unique id; deletions tombstone rather than
remove; concurrent inserts at the same position resolve via a
deterministic id-based tie-break every replica computes identically,
with no coordination. Skein implements this as a tree (each node's
children are whatever got inserted immediately after it, kept sorted by
id) rather than the classical flat-array/linear-scan formulation — and
then, specifically to catch bugs the tree implementation alone
couldn't reveal, ships a **second, deliberately independent
implementation** (`oracle.py`, the classical array-scan algorithm) and
differentially tests the two against each other across thousands of
randomized sessions.

## How to run it

```bash
cd 2026-08-19-skein

# Unit suite (83 tests) and the full end-to-end walkthrough:
python3 -m unittest discover -s tests -q
./demo.sh

# Individual CLI commands:
python3 -m skein.cli demo                        # narrated walkthrough of every core feature
python3 -m skein.cli sim --sites 3 --edits 40     # one chaos simulation, full transcript
python3 -m skein.cli chaos --trials 300           # randomized convergence-proof sweep
python3 -m skein.cli shuffle-proof --trials 300   # order-independence proof
python3 -m skein.cli serve                        # interactive playground → http://127.0.0.1:8765/
```

In the playground: type in any of the three panes ("Alice"/"Bob"/
"Carol") and watch the other two catch up as the simulated network
delivers your edit; click Disconnect on a pane to partition that site,
keep typing into it while it's "offline," then Reconnect and watch it
converge; drag the drop-rate / duplicate-rate / latency sliders to make
the network actively hostile and watch convergence hold anyway; Undo/
Redo on a pane undoes *that pane's own* last edit specifically, correct
even when a remote edit landed at the position it used to occupy.

## Full feature list

**Required (all 4 shipped, working end-to-end):**

1. **RGA sequence CRDT engine** (`skein/rga.py`) — unique-id-based
   insert/delete with tombstones, a deterministic tie-break for
   concurrent inserts at the same position, and causal buffering
   (an op whose dependency hasn't arrived yet waits, resolved by an
   explicit worklist rather than recursion — see REVIEW.md bug #1).
2. **Simulated unreliable network** (`skein/network.py`) — per-message
   latency jitter, reordering, duplication, drop, and partition/heal
   with real anti-entropy resync on reconnect.
3. **Multi-site concurrent-edit simulator** (`skein/simulate.py`,
   `skein/site.py`) — N independent sites editing (including two sites
   typing at the exact same position in the same tick) and broadcasting
   over the simulated network.
4. **Convergence verification harness** (`skein/convergence.py`) — the
   actual CRDT proof: the same op set replayed through hundreds of
   random delivery orderings must produce byte-identical documents on
   every replica, cross-checked against the independent oracle.

**Stretch (both shipped):**

5. **Interactive HTML collaborative playground** (`skein/web/`) —
   server-backed (the browser has zero CRDT logic, same pattern this
   repo has used before for Gambit/Formulate/Unify), live network
   activity log, adjustable chaos knobs, partition/reconnect buttons.
6. **CRDT-native per-site undo/redo** (`skein/undo.py`) — addressed
   entirely by id/origin rather than position, so it stays correct
   under arbitrary remote interleaving; honestly documented where redo
   can't guarantee restoring the *exact* original position once
   concurrent inserts have happened at that spot (ids are never
   resurrected in a CRDT — redo mints a fresh one).

**Not shipped:** a causal/op-DAG visualizer (planned stretch feature
7 in PLAN.md) — deliberately dropped in favor of fully polishing and
verifying the two shipped stretch features and the web playground,
rather than spreading effort across a third feature and a review pass
too thin to catch what mattered. See PLAN.md and REVIEW.md.

## Why this, today

This repo has built consensus before (Quorum, 2026-06-15 — a Raft
simulator), search engines, SAT solvers, and half a dozen from-scratch
language models, but never the *other* major distributed-systems
answer to "how do multiple writers agree on shared state": no leader,
no quorum, no vote — replicas that simply guarantee convergence by
construction. Raft's minority partition can't make progress at all;
an RGA replica that's been offline for a week can keep editing freely
and will still converge the instant it reconnects. That's a genuinely
different idea worth its own build, not a variation on Quorum — and it
comes with a naturally great interactive demo: watching independent
panes diverge under adversarial network chaos and then converge anyway,
live, in a browser.

## Where a human could take this next

- **Tombstone garbage collection.** Deleted characters live forever
  right now — real systems garbage-collect tombstones behind a
  causal-stability watermark (once every replica has definitely seen a
  delete, it's safe to forget). A good next project on its own.
- **A proper per-parent data structure.** `_sorted_insert_desc` and the
  oracle's `_reindex_from` are O(n) per op — fine at this project's
  scale, but an order-statistics tree per parent would make Skein a
  sequence CRDT that scales to real documents.
- **Grapheme-cluster-aware editing.** `InsertOp` requires exactly one
  Python codepoint; a flag emoji or ZWJ sequence needs several ops.
  Segmenting by grapheme cluster instead would make multi-codepoint
  "characters" atomic.
- **A real transport.** The simulated network is intentionally
  in-memory and single-process, which is what makes the chaos harness
  fast and deterministic — swapping in real WebSockets between actual
  browser tabs (keeping the exact same `RGA`/`Site` core) would turn
  this from a simulator into an actual multi-user editor.
- **Rich text, not just plain text.** The RGA only orders characters;
  formatting (bold, headings, embedded images) is a whole additional
  CRDT layer real editors like Yjs build on top of a sequence type
  like this one.

## Development record

- [PLAN.md](./PLAN.md) — architecture and the full feature plan.
- [REVIEW.md](./REVIEW.md) — the adversarial review: 4 real bugs found
  and fixed across Phases 3–4 (a `RecursionError` a straight-typed
  document delivered in reverse order would reliably trigger, a
  network-partition isolation leak, CLI crashes on invalid input, and a
  non-atomic delete API that silently wiped every replica's document on
  a "failed" call), plus deliberate tradeoffs considered and kept.
- `tests/` — 83 unit tests, including a regression test for every bug
  in REVIEW.md.
- `demo.sh` — runs the unit suite, every CLI feature, and a live HTTP
  smoke test of the playground end-to-end; exits non-zero on failure.
