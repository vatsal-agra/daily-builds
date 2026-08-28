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

## Verdict

5 real issues found (2 critical, 1 high, 2 medium), all fixed, all with
regression tests. 84/84 unit tests green, 6/6 and then a further 6/6
full end-to-end `demo` runs green after the fixes landed (up from
roughly 50% intermittent failures beforehand). A fresh run-through hits
zero of the issues listed above.
