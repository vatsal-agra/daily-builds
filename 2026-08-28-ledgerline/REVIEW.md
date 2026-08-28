# Phase 3 — Adversarial Review

Attacking the Phase 2 build as a hostile reviewer: a malicious peer
crafting messages, a wallet with a fat-fingered address, a node that just
got unlucky in a race. Every issue below was found, then fixed, then
covered by a regression test before this phase closed.

## Findings

### 1. CRITICAL — negative `TxOut.amount` lets a transaction mint money

`chain.py`'s validation only ever checked `sum(inputs) >= sum(outputs)`.
Nothing stopped an individual output's `amount` from being negative. A
transaction with two outputs — `+1,000,000` to the attacker and
`-999,000` as a second "output" — sums to `total_output() == 1,000`, so
it sails past the sufficiency check with almost no real input. But
`_apply()` still creates a real UTXO entry for *every* output at its
literal amount, including the huge positive one — so the attacker walks
away with 1,000,000 coins backed by essentially nothing. This is real
theft-from-thin-air, not a display quirk.

**Fix:** `TxOut.__post_init__` now rejects any non-negative-integer
amount (also catching `bool`, since `isinstance(True, int)` is true in
Python) at construction — the one place every `TxOut`, wire-deserialized
or not, passes through. Covered by
`tests/test_transaction.py::TestTxOutValidation` (5 cases, including one
built via `TxOut.from_dict` to prove a malicious peer's JSON is caught
too).

### 2. CRITICAL — a losing double-spend (or a self-rejected block) permanently poisons a node's own mining

Once a transaction was accepted into a node's mempool, nothing ever
re-validated it against the *current* UTXO set except the two narrow
paths already wired up (reorg disconnect/connect). Concretely: if
transaction T2 conflicts with T1 (same input, different output) and T1
gets confirmed by *any* block T2 was never part of, T2 sits in the
mempool forever. Every subsequent mining attempt on that node
re-selects T2 (it's still "in the mempool"), builds a whole block
around it, mines it (real, wasted CPU), and `chain.add_block` rejects
the *entire block* for the one bad tx — including any other, perfectly
valid transactions bundled alongside it. T2 is never removed by the
rejection path, so this repeats forever: **100% of that node's future
mining work is wasted**, permanently, until a process restart. This is
exactly the failure mode the double-spend/reorg stretch demo (Phase 4)
would have triggered head-on.

**Fix:** added `Node._prune_invalid_mempool_locked()` — re-validates
every mempool transaction against the live UTXO set and drops anything
that no longer holds up. Wired into both places this can happen: (a)
right after `_accept_block` rejects a block for a non-orphan (i.e.
transaction-level) reason, and (b) after every successfully accepted
block, since a confirmed block can invalidate mempool transactions it
never even mentions. Covered by
`tests/test_node.py::TestMempoolHygiene` (both call sites, each with its
own test proving the poisoned tx is gone afterward).

### 3. HIGH — malformed/malicious network messages can kill a peer connection's reader thread

`_handle_message` parses attacker-controlled JSON (hex pubkeys,
signatures, addresses, amounts) with no exception boundary around the
actual dispatch — only the *line-framing* layer (JSON decode, socket
errors) was caught. A single malformed field (bad hex, a missing key, a
non-numeric amount) raises `ValueError`/`KeyError`/`TypeError` straight
out of `_handle_message`, which is *not* one of the caught exception
types in `_reader_loop`/`_inbound_handler` — so it kills the whole
thread, and with it the connection to that peer, over one bad message.
A hostile or just-buggy peer gets an outsized DoS for free.

**Fix:** extracted `_dispatch_message()`, which calls `_handle_message`
inside its own `try/except (ValueError, KeyError, TypeError,
IndexError)`, logging and moving on to the next line instead of dying.
Also tightened the JSON-decode step to skip one bad line rather than
tear down the connection. Covered by
`tests/test_node.py::TestMalformedMessageHandling` (4 cases: a garbage
tx payload, invalid hex, an unknown message type, a missing `data`
field).

### 4. MEDIUM — Base58Check exists to catch address typos, but nothing ever checked it before sending

The whole point of a checksum-encoded address is catching a
mistyped/corrupted recipient *before* funds move. `build_transaction`
never validated `to_address` (or `change_address`) at all — a typo would
still "succeed," silently creating a real UTXO under an address nobody
can ever spend from. Money quietly gone, no error anywhere in the
pipeline.

**Fix:** `build_transaction` now runs both addresses through
`b58check_decode` before doing anything else, raising a clear
`ValueError` naming which address (recipient/change) is bad and why.
The explorer's `/api/send` already wrapped transaction-building in a
broad `except Exception` (verified — this surfaces as a clean `{"ok":
false, "error": ...}` response, not a 500). Covered by
`test_mistyped_recipient_address_rejected`.

### 5. MEDIUM — two demo assertions were racy against the receiver's *own* concurrent mining income

The most time expensive bug in this review, and the one that made
Phase 2's demo intermittently "hang" for 30+ blocks before timing out
(and it *is* a Phase 2 bug — flagged here because catching it took the
adversarial mindset of this phase, not because it slipped past Phase 2's
gate unnoticed forever). `section_transactions` picked `nodes[1]` — an
*active miner* — as the transfer's receiver, then asserted
`nodes[1].chain.balance_of(receiver) == starting_balance + 250` with
strict equality. But node1 keeps earning its own block rewards to the
same address the whole time this section runs. The instant the transfer
actually confirmed, node1's balance may already have moved past the
target (another reward landed in the same window) — permanently missing
an exact-equality check that could now never be satisfied again, timing
out even though the transfer had genuinely succeeded. A second, narrower
version of the same "snapshot-then-assert against still-moving state"
mistake was in `section_fork_resolution`'s final tip-agreement check
(mining never pauses, so the tip can move between "converged" and the
assertion that reads it).

Chasing this down first produced three genuine — if smaller —
concurrency fixes that are worth keeping regardless (see below), before
the real root cause turned out to be the test's own assertion, not the
network:

- **Non-deterministic dual dialing.** Every node dialed every peer, so
  both sides of a pair could race to connect simultaneously; whichever
  socket lost the race for the `conns[addr]` dict slot was silently
  orphaned, leaving that link one-way. Fixed by having only the
  lower-`(host, port)` peer of any pair ever dial — the other just
  accepts.
- **No mempool sync on (re)connect.** A transaction broadcast at the
  exact moment a connection was mid-reconnect could vanish for good —
  nothing else ever re-announced it. Fixed with `_sync_mempool_to()`,
  called on every new/re-established connection.
- **The mining loop cleared its "tip changed" flag *after* already
  reading the (possibly stale) tip**, not before — a narrow window where
  a legitimate abort signal from a concurrently-arriving block could be
  silently discarded, wasting a whole mining attempt on an
  already-superseded parent. Fixed by clearing the flag before the read,
  not after.

**Fix:** both assertions now use `>=` (monotonic-safe against a
mining node's own concurrent income) instead of `==`, and
`section_fork_resolution`'s final check is wrapped in a short
`_wait_until` instead of trusting a single instant. Verified with 20
full end-to-end `demo` runs post-fix, 0 failures (versus roughly half
failing before, isolated with a dedicated repro harness that logged
every mempool add/remove and block-validation event to confirm the
exact mechanism).

## Not fixed — considered and already mitigated

**Merkle-tree duplicate-node malleability (CVE-2012-2459-style).**
`merkle.py` duplicates the last leaf when a level has an odd count,
matching real Bitcoin's construction — which is exactly the construction
that historically let two different transaction lists produce the same
root. This project is already protected: `validate_block_shape` rejects
any block containing a duplicate transaction id outright, which is the
one thing the classic exploit requires. Documented rather than "fixed"
since deviating from the Bitcoin-matching construction would be a
regression against the project's own stated design goal, not an
improvement.

## Verdict (Phase 3)

5 real issues found (2 critical, 1 high, 2 medium), all fixed, all with
regression tests. 84/84 unit tests green, 6/6 and then a further 6/6
full end-to-end `demo` runs green after the fixes landed (up from
roughly 50% intermittent failures beforehand). A fresh run-through hits
zero of the issues listed above.

---

# Phase 4 addendum — 2 more real bugs, found building the stretch features

Building the double-spend/reorg and difficulty-retargeting stretch demos
immediately exercised two code paths nothing before them had ever
touched — multi-input transactions, and a receiver-owned-by-a-miner
double-spend target — and both broke on first real use.

### 6. CRITICAL — multi-input transactions were fundamentally broken

`Transaction._signing_payload()` included every input's `pubkey` in the
signed payload. `sign_input()` sets `txin.pubkey` *before* computing that
payload — so for a transaction with more than one input, signing input 1
changes what input 0's signing payload now contains (input 0's own
pubkey was already set by the time input 1 gets signed), silently
invalidating input 0's already-computed signature the moment a second
input is signed. Every unit test up to this point happened to only ever
build single-input transactions (one large UTXO always covered the
amount), so this was invisible until `section_double_spend_reorg`
(Phase 4) called `build_transaction()` directly with every UTXO a node
held — multiple inputs — and hit `"input 0 signature does not verify"`
on the very first submission.

**Fix:** pubkeys are no longer part of the signed payload at all — they
don't need to be. A signature already cryptographically binds to the
specific pubkey it's checked against (that's what `ecdsa.verify` does),
and UTXO ownership is verified separately elsewhere
(`pubkey_to_address(pubkey) == utxo.address`, in chain.py/node.py). What
actually has to stay in the signed payload is `prev_txid`/`prev_index`
— those never change during signing, and are what stops the input list
itself from being tampered with post-signature. Covered by
`test_multi_input_transaction_signatures_all_verify`, which independently
re-verifies every input's signature against the shared digest, not just
the aggregate `verify_signatures()` result.

### 7. MEDIUM — the same receiver-is-an-active-miner equality race from finding #5, again, in new code

`section_double_spend_reorg` used `nodes[1].wallet.address` /
`nodes[2].wallet.address` as the two conflicting recipients — but those
nodes are themselves actively mining the whole section, earning their
own block rewards to those same addresses independent of which side of
the double-spend wins. The final `== loser_starting` check intermittently
failed exactly the way finding #5 already diagnosed, in the one place
that lesson didn't get applied to new code.

**Fix:** the double-spend demo now sends to two dedicated `Wallet()`
instances that never mine — a merchant wallet that receives *only* the
disputed transfer is the only way an exact-equality check against it is
ever safe. General lesson for anyone extending this demo further: never
use a mining node's own address as a balance-equality check target.

## Verdict (Phase 4)

Both stretch features shipped (difficulty retargeting responding to a
real ~4x hashrate change; a live double-spend across a partition
resolved by reorg) plus polish (CLI input validation with clean error
messages instead of tracebacks or silent hangs, an edge case in
`Mempool.select_for_block(max_count<=0)`, help text on every CLI flag,
and `Wallet.save/load` wired into a real `--wallet` flag instead of
sitting unused). 98/98 unit tests green, 5/5 full end-to-end `demo` runs
green (including both new stretch sections) after the two bugs above were
found and fixed.

---

# Phase 6 addendum — the retarget demo's "more hash power" wasn't real hash power

Pre-ship re-validation (running `demo.sh` fresh, several times, as its own
check) caught the retarget section intermittently failing or landing on
the wrong side of neutral — genuinely confusing at first, since the exact
same math is pinned down by 6 passing deterministic unit tests using fake
timestamps. The live section, unlike those tests, depends on *real*
elapsed wall-clock time, and that's where the bug was.

### 8. HIGH — "adding more mining nodes" added threads, not hash power

The original version of `section_difficulty_retarget` added 3 more
`Node`s as in-process **threads** (the same pattern every other section
in this file uses for its nodes) to demonstrate difficulty responding to
increased hash power. But CPython's GIL caps total hashing throughput
across concurrent *threads in one process* to roughly what a single
thread already gets — adding more threads doesn't add parallel CPU work,
it adds contention. Live runs bore this out exactly: difficulty stayed
flat, or even ticked *down* (more threads meant more lock/context-switch
overhead, not more real throughput) after "quadrupling hash power" —
the opposite of what a real hashrate increase should do, and the direct
reason this section's live behavior didn't match its own passing unit
tests.

**Fix:** `network.spawn_mining_process()` starts each additional node in
a genuine separate OS process (`multiprocessing.Process`) instead of a
thread. Nodes already only ever communicate over real TCP sockets, so a
mining node genuinely doesn't care whether a peer lives in this process
or another one — no protocol change needed, just where the extra nodes
actually run. On this 4-core host, 3 additional real processes now
reliably increase difficulty within one retarget window (~35-45s
end-to-end across repeated trials), instead of the multi-window
polling-with-a-generous-timeout workaround the thread-based version
needed just to paper over throughput that fundamentally wasn't there.

### 9. LOW — the explorer verification script itself was flaky, twice

Two more issues turned up in `verify_explorer.js` (not in LedgerLine
itself) during this same pre-ship re-validation: `page.goto` waited for
Playwright's `"networkidle"`, which by definition never fires on a page
that polls `/api/status` forever by design (a live-updating UI) — an
intermittent timeout unrelated to whether the page actually loaded
correctly. And the send-form check used one fixed `waitForTimeout(1500)`
after clicking submit, which occasionally raced a real HTTP response
under genuine mining load (3 threads contending for the GIL can measurably
slow the explorer's own HTTP handler thread). **Fix:** wait for `"load"`
instead of `"networkidle"`, and poll for `#sendMsg` actually containing
text (up to 10s) instead of gambling on a fixed delay being long enough.

## Verdict (Phase 6 / final)

9 real issues found and fixed across Phases 3-6 (3 critical, 2 high, 4
medium/low), every one with a regression test or a repeated live
re-validation proving the fix. `demo.sh` green across repeated full runs
pre-ship, including the corrected retarget section landing reliably and
quickly, and the corrected explorer check no longer racing its own
verification logic.
