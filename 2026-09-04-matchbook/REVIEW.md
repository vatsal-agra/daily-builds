# Phase 3 — Adversarial Review

Attacking Matchbook as a hostile reviewer: reading every module for
correctness, then actively trying to break the CLI with malformed,
degenerate, and adversarial input.

## Findings

### 1. [CRITICAL] `OrderBook.modify()` destroys the original order before validating the replacement — silent order loss

`modify()` was implemented as "cancel the old order, then construct and
submit a replacement." But it never validated the *prospective* replacement
before cancelling: `Order.__post_init__` raises `ValidationError` for a
non-positive quantity or price, and that constructor call happened *after*
`self.cancel(order_id)` had already removed the original from the book.

```python
>>> book.modify(1, new_qty=0)
ValidationError: order 1 qty must be positive, got 0
>>> book.total_resting_qty()
0          # the original order is just gone. No trade. No cancel record.
```

A caller passing `new_qty=0` (a very natural way to try to "cancel down to
nothing") destroys a live resting order with zero audit trail and an
uncaught exception. This is a real, silent data-loss bug, not a cosmetic
one — a `MarketMaker` or a future feature calling `modify()` with a bad
value would corrupt live book state.

**Fix:** validate the prospective new price/qty *before* touching the
original order. If validation fails, the original order is left completely
untouched and a clear `ValidationError` is raised.

### 2. [BUG] `matchbook viz`/`crash-demo` crash the browser instead of erroring cleanly on `--ticks 0`

`matchbook run --ticks 0` correctly rejects the input (`error: --ticks must
be positive`, exit code 2) — but `matchbook viz --ticks 0` silently "succeeds,"
writing a broken HTML file. Opening it throws immediately:

```
Cannot read properties of undefined (reading 'tick')
```

because `DATA.history` is empty, so `scrubber.max` becomes `-1` and
`DATA.history[tick]` is `undefined` from the very first render. The two
subcommands run the exact same simulation but only one validates its input.

**Fix:** apply the same `--ticks > 0` validation to `cmd_viz` and
`cmd_crash_demo`, and make the front-end itself defensive (render a plain
"no session data" message instead of indexing into an empty array), so a
degenerate session is a friendly no-op rather than a JS exception either way.

### 3. [BUG] `matchbook replay` surfaces a raw, unhelpful `KeyError` on a symbol mismatch

Replaying a journal with the wrong `--symbols` list crashes with:

```
error: 'ACME'
```

— just the missing dict key, no context. This happens because
`Exchange.replay()` re-applies each journaled order via
`self.books[order.symbol]`, and if the journal was recorded for a symbol
that isn't in the replay's (mistyped) symbol list, that's a bare `KeyError`
propagating out of `_apply_submit`.

**Fix:** validate up front that the journal's referenced symbols are a
subset of the ones the replay was told about, and raise a clear,
actionable `ValueError` naming the missing symbol(s) and how to fix the
command.

### 4. [DESIGN FLAW] Dead, misleading risk-limit flags on `matchbook replay`

`replay` accepted `--position-limit`, `--fat-finger-pct`, and
`--max-order-qty` and threaded them into `Exchange.replay()`'s
`RiskEngine`. But replay *never actually re-runs the risk engine*: a
journaled `SUBMIT` either carries `rejected_pretrade: true` (in which case
replay just re-records the historical rejection verbatim) or it doesn't (in
which case replay applies it to the book directly, with no risk re-check at
all — correctly, since risk decisions are already baked into what got
journaled). The result: those three CLI flags looked configurable but had
*zero effect* on the reconstructed state, which could mislead someone into
thinking they can retroactively change risk policy during playback.

**Fix:** removed the dead parameter from `Exchange.replay()` and the three
flags from the `replay` subcommand, with a comment explaining why. Kept
`--no-stp` / `self_trade_prevention`, since self-trade prevention *is*
genuinely re-evaluated live during replay (it's a matching-time decision
re-derived by re-running the deterministic match against the reconstructed
book, not something the journal records in advance) — that one must be
passed consistently with the original live session, which is now the only
replay flag that matters and is documented as such.

### 5. [BUG] Duplicate symbols in `--symbols` silently produce a broken-looking UI

`matchbook viz --symbols ACME,ACME` doesn't error, but the rendered page's
symbol dropdown lists "ACME" twice (cosmetically broken, and wasteful —
every per-symbol computation runs twice for the same market).

**Fix:** `_parse_symbols` now dedupes while preserving order.

### 6. [MINOR] `OrderBook.cancel()` doesn't prune emptied price levels, unlike `_match()`

When a match empties a price level, `_match()` removes it from the
`bid_levels`/`ask_levels` dict immediately. `cancel()` didn't do the same
when a cancellation was what emptied the level — the entry just sits there
(with an empty deque) until it happens to reach the top of its heap. Not a
correctness bug (both `best_bid`/`best_ask` and `depth()` already correctly
skip empty levels), but an inconsistency that lets a long-running book with
many transient price levels accumulate stale dict entries indefinitely.

**Fix:** `cancel()` now prunes an emptied level immediately, matching
`_match()`'s behavior.

### 7. [MINOR] Dead `ExchangeConfig` dataclass

A leftover from early design that was never actually wired into `Exchange.__init__`
or used by any caller. Removed.

## Verification

Every fix above has a regression test (see `tests/test_book.py::TestModifyValidation`,
`tests/test_cli.py`, and the updated `tests/test_engine.py`). Re-running the
full adversarial pass after the fixes:

- `book.modify(order_id, new_qty=0)` now raises cleanly with the original
  order fully intact and still resting.
- `matchbook viz --ticks 0` and `matchbook crash-demo --ticks 0` now fail
  with the same clean `error: --ticks must be positive` as `run`.
- `matchbook replay` with a wrong `--symbols` list now fails with a message
  that names the missing symbol and tells you to fix `--symbols`.
- `matchbook replay --help` no longer advertises risk-limit flags that did
  nothing.
- `--symbols ACME,ACME` now behaves identically to `--symbols ACME`.

No other issues found across a targeted re-read of `book.py` (price/time
priority, FOK atomicity, self-trade prevention), `engine.py` (position/cash
conservation, journal ordering), `journal.py` (CRC/torn-write handling), and
`risk.py` (boundary conditions) beyond what the Phase 2 test suite already
covers -- see `tests/` for the property-based checks (price-time priority
and share conservation over random sessions, replay-fingerprint equality,
determinism under a fixed seed) that back that up.
