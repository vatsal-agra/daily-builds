# Braid

*Status: shipped.*

A real-time collaborative text editor whose consistency guarantee comes
from a **from-scratch CRDT** (Conflict-free Replicated Data Type) — no
operational transform, no central sequencer, no CRDT library (no Yjs, no
Automerge). Every browser tab keeps its own independent, mutable replica
of the document. Typing applies instantly and locally — no round trip to
a server before you see your own keystroke — and when edits from other
peers arrive, in any order, with any delay, duplicated, or after a
network partition, every replica is mathematically guaranteed to
converge to the *same* document without ever coordinating with another.

Open the editor in two browser tabs, type in both at once, click **Go
offline** in one, keep typing in both, go back online, and watch them
converge without either tab "winning."

## Why I built this today

The daily-build ledger already has a deterministic **consensus**
simulator (Quorum's Raft, 2026-06-15) — a family of algorithms whose
whole point is to force a *single, agreed order* onto concurrent
operations. A CRDT is the opposite bet: no agreement, no leader, no
voting, no blocking, and it still provably converges (Strong Eventual
Consistency instead of linearizability). That's a genuinely different
distributed-systems idea that hadn't been built here before, it has an
unusually satisfying live demo, and — as it turned out — it's a much
subtler algorithm to get right than it looks on paper: building it
surfaced two real correctness bugs (documented in [REVIEW.md](./REVIEW.md))
that no naive implementation would have caught without deliberately
adversarial testing.

## Try it

```bash
cd 2026-08-05-braid

# the live collaborative editor -- open http://localhost:8420/ in 2+ tabs
python3 cli.py serve

# headless: a narrated offline-editing + reconnect-merge walkthrough
python3 cli.py scenario

# headless: prove Strong Eventual Consistency across 200 seeded,
# adversarial (latency/reorder/duplicate/loss/partition) network runs
python3 cli.py sweep --count 200

# run everything: 72-test unit suite + CLI walkthroughs + a real
# multi-tab Playwright browser test against a live server
./demo.sh
```

No dependencies beyond the Python 3 standard library for the engine,
CLI, and server. `demo.sh`'s browser test additionally uses Node +
Playwright if available (skips cleanly otherwise — the Python-only
coverage still runs and still proves the CRDT's core guarantee).

## Architecture

```
crdt/rga.py          from-scratch RGA (Replicated Growable Array) CRDT
                      engine — the algorithm. Tombstone-based deletes,
                      Lamport-clock ids, deterministic conflict
                      resolution for concurrent inserts.
crdt/site.py          a Site = a local RGA replica + causal-delivery
                      buffer (an op can't apply until its dependency
                      exists locally) + CRDT-aware undo/redo + an
                      op-log used for anti-entropy gossip.
crdt/network.py        a deterministic, seeded, adversarial network
                      simulator (latency/reorder/duplication/loss/
                      partition) driving Strong-Eventual-Consistency
                      convergence proofs.
static/rga.js           a hand-ported 1:1 mirror of rga.py/site.py in
                      JavaScript — every browser tab is a real,
                      independent CRDT replica, not a dumb terminal.
                      Parity with the Python engine is continuously
                      checked (tests/test_parity.py).
server.py               a deliberately "dumb" stdlib-only relay: it
                      never touches CRDT logic, just keeps an
                      append-only op log (for late-joining tabs to
                      replay) and broadcasts ops live over
                      Server-Sent Events. The safety guarantee is
                      proven entirely by the replicas, exactly like a
                      real P2P deployment would need it to be.
cli.py                   headless multi-peer simulation, convergence
                      sweeps, a scripted offline/reconnect scenario,
                      and the `serve` entrypoint.
static/index.html,        the live multi-tab editor: presence with live
static/app.js,             peer cursors (mirror-div technique over a
static/style.css           plain <textarea>), a network-chaos control
                          panel, and CRDT-aware undo/redo.
tests/, demo.sh              72-test unittest suite + a live multi-tab
                          Playwright browser test, tied together in one
                          script — see PHASE 5 below.
```

## Feature list

**Required (all four work end-to-end):**

1. **From-scratch RGA CRDT engine** — insert/delete, tombstones,
   Lamport-clock-ordered ids, deterministic concurrent-insert tie-break,
   causal-delivery buffering for out-of-order remote ops.
2. **Deterministic adversarial network simulator + convergence proof** —
   seeded latency/reorder/duplication/loss/partition, with anti-entropy
   gossip layered on top (a lossy point-to-point link plus periodic
   full-resync gossip, exactly like real CRDT deployments need). `cli.py
   sweep` runs a wide seed sweep and asserts every replica ends up
   byte-identical.
3. **Real-time multi-peer collaborative web editor** — local-first
   editing (no round trip to see your own keystroke) synced live over
   Server-Sent Events; concurrent edits from multiple tabs converge
   correctly, including through simulated network chaos.
4. **Headless CLI simulation & scripted scenarios** — convergence
   sweeps, single verbose runs, and a narrated "peer goes offline, edits
   diverge, reconnects, merges" scenario, no browser required.

**Stretch (both shipped):**

5. **CRDT-aware local undo/redo** — each site's own undo stack targets
   node **ids**, never document positions, so undoing "my edit from
   before" stays correct even if a remote peer inserted or deleted
   content in the same region in the meantime. Multi-character
   paste/delete-range operations are grouped into a single undo action.
6. **Live presence + network-chaos control panel** — see who else is
   connected and where their cursor is in real time (rendered as
   colored carets directly over the textarea via a mirror-div pixel
   measurement technique), plus a "Go offline" toggle and a simulated-lag
   slider that make the convergence guarantee something you can *watch
   happen* rather than take on faith.

## The adversarial review (Phase 3) — what it actually found

This wasn't a token pass. Building this surfaced **six real bugs**,
documented in full in [REVIEW.md](./REVIEW.md):

1. Delete-after-undo silently dropped on remote replicas (delete/restore
   ops originally reused their target node's id, colliding with dedup).
2. `Site.receive()` never actually buffered an op whose dependency
   hadn't arrived, despite its own docstring — every headless test had
   happened to route around the buggy path; only the live browser UI
   exercised it.
3. **Non-concurrent** inserts could land in the wrong position: id
   tie-breaking used plain per-site counters instead of Lamport clocks,
   so a quieter site's brand-new insert could lose a tie-break to an
   older node purely by counter magnitude — with zero actual
   concurrency to justify it. Fixed with proper Lamport clocks.
4. Astral Unicode characters (most emoji) silently split into two CRDT
   nodes because the JS engine iterated UTF-16 code units instead of
   Unicode code points.
5. The static-file path-traversal guard used a bypassable string-prefix
   check.
6. Invalid CLI arguments and malformed network payloads crashed with
   raw tracebacks or could have corrupted a peer's document instead of
   failing cleanly.

Every one of these was reproduced with a concrete failing test *before*
being fixed, then re-verified — and turned into a permanent regression
test in `tests/`.

## Honest, documented limitations (not hidden)

- RGA does **not** guarantee intention preservation for *genuine*
  concurrency: two peers inserting at the exact same position in the
  same instant, neither having seen the other's edit, can get their
  characters interleaved. This is inherent to the RGA/WOOT CRDT family
  (the same lineage YATA/Yjs improves on) — Strong Eventual Consistency
  is guaranteed; character-level intention preservation under true
  concurrency is not, without a materially more complex algorithm.
- Grapheme clusters aren't segmented — one CRDT node is one Unicode code
  point (matching Python's string model), not one user-perceived
  character, so a multi-codepoint emoji (flag, skin-tone modifier, ZWJ
  sequence) is still several CRDT nodes under the hood.
- The live web editor is a single shared document per server process,
  held only in memory — restarting `serve` loses it. This is a
  deliberate scope choice; the CLI's `simulate`/`sweep`/`scenario`
  commands are what formally prove the CRDT's guarantees, independent
  of this demo server.
- A tab that goes offline and never reconnects loses its queued
  outbound edits (they stay visible in that tab, but never reach anyone
  else) — there's no server-side durability for edits ahead of relay,
  by design (the server is a dumb, in-memory relay, not a database).

## Verification (Phase 5)

```
$ ./demo.sh
...
--- 1/5: Python unit test suite ---            OK  (72 tests)
--- 2/5: CLI convergence sweep ---              OK  (100/100 seeds)
--- 3/5: CLI offline/reconnect scenario ---     OK
--- 4/5: single simulate run ---                OK
--- 5/5: live server + real browser tabs ---    OK
RESULT: 5 passed, 0 failed
```

The 72-test `unittest` suite (`tests/`) covers the engine in isolation
(`test_rga.py`), causal buffering and undo/redo through the site layer
(`test_site.py`), the network simulator and multi-seed convergence
sweeps (`test_network_convergence.py`), the live HTTP server including
the path-traversal fix (`test_server.py`), CLI argument validation
(`test_cli.py`), and Python↔JS engine parity via Node
(`test_parity.py`). `tests/browser_test.js` is a real, permanent
multi-tab Playwright test exercising the live editor in an actual
browser — not a mock.

## Where a human could take this next

- **A refined placement algorithm (YATA/Fugue-style)** to close the
  remaining genuine-concurrency interleaving gap noted above — this is
  exactly the improvement real systems like Yjs made over plain RGA, and
  the network simulator here would make an excellent test bed for
  proving it (run the same seed sweep against both algorithms and diff
  the interleaving rate).
- **Persistence.** The server holds the document only in memory; adding
  a WAL or periodic snapshot (à la Strata's LSM tree, 2026-06-28/07-03)
  would make a restart survivable.
- **Rich text.** The engine is plain-text/character-based; a natural
  extension is a second CRDT (a map or a tree, e.g. an interleaved
  formatting-attribute layer) for bold/italic/headings on top of the
  same sequence.
- **Real P2P**, not a relay. `server.py` is deliberately a dumb SSE
  broadcaster; replacing it with WebRTC data channels between browsers
  would remove the server from the trust/availability path entirely —
  the CRDT algorithm doesn't change at all, since it was already
  designed assuming no central authority.
- **Multi-document support** — the Hub is single-document per process by
  design; keying it by a document id in the URL is a small, mechanical
  change.
- **A visualizer** in the spirit of this repo's other interactive
  builds (Quorum, Conflux, Backjump) — replay a captured op stream and
  show the RGA's internal tombstone-and-origin structure animating as
  peers "type," making the tie-break rule visible rather than implicit.

## Stack

Pure Python 3 standard library for the engine, CLI, and server (no
Flask/FastAPI/websockets — hand-rolled Server-Sent Events over
`http.server`). Vanilla JavaScript for the browser (no framework, no
bundler, no build step) — `static/rga.js` is a direct hand-port of the
Python engine, not a reimplementation from scratch, specifically so the
two stay provably equivalent (`tests/test_parity.py`). Playwright
(pre-installed Chromium) for the one genuinely browser-dependent test.
