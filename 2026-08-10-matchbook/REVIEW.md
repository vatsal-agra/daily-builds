# Adversarial Review

Went through the engine, simulator, and visualizer as a hostile reviewer
looking to break invariants, find lazy shortcuts, and find ugly UX. Each
finding below was reproduced before being fixed; every fix was re-checked
afterward.

## Findings

### 1. (Correctness) Engine allows self-trades — CONFIRMED, FIXED

Two agents' resting and incoming orders can share the same owner (e.g. a
noise trader's earlier resting order gets matched against that same
trader's later crossing order). Reproduced directly from a real 3000-tick
session:

```
noise.acme.2 traded with noise.acme.2 — ts=2221, price=100.22, qty=5
noise.acme.1 traded with noise.acme.1 — ts=2857, price=100.54, qty=6
```

This doesn't corrupt P&L bookkeeping (the buy and sell legs net to
exactly zero cash and inventory change), but it's a real correctness gap
against how every serious matching engine behaves — self-trade
prevention (STP) is standard exchange behavior, and a wash trade quietly
inflating the "trades so far" counter and cluttering the trade tape with
an agent "trading with itself" is exactly the kind of thing a real venue
would reject. **Fix:** `book.py` now implements a cancel-resting STP
policy — if the resting order at the front of a price level shares an
owner with the incoming order, it is pulled off the book (as if
cancelled) without generating a trade, and matching continues against
the next order in the queue.

### 2. (Correctness) No price validation on LIMIT/IOC/FOK orders — CONFIRMED, FIXED

`OrderBook.submit()` validated `qty > 0` but never validated that a
supplied `price` is positive. A price of `0` or a negative price would
have been silently accepted and would corrupt every downstream P&L and
depth calculation. No agent currently produces this, but the engine is
also a public API for the stat-arb/pluggable-strategy SDK (stretch
feature 6) — a buggy third-party strategy computing a bad price is
exactly the case this needs to guard against. **Fix:** `submit()` now
rejects any supplied price `<= 0` with `RejectedOrder`.

### 3. (Robustness) A malformed agent action crashes the whole session — CONFIRMED, FIXED

`MarketSimulator._apply_action` called `book.submit(...)` directly. Since
`submit()` raises `RejectedOrder` for bad input (see #2, and pre-existing
`qty<=0` validation), a single buggy custom strategy — exactly the kind
the pluggable Agent SDK (stretch feature 6) explicitly invites — would
throw an uncaught exception and kill the entire multi-thousand-tick
simulation, discarding every other agent's session. Reproduced by
registering a deliberately broken agent that emits `qty=0`. **Fix:**
`_apply_action` now catches `RejectedOrder`, drops only that one action,
and the session continues; a running counter of rejected actions is
included in the session JSON so a real bug in a custom strategy is still
visible, just not fatal.

### 4. (Data completeness) First depth snapshot always misses tick 0 — CONFIRMED, FIXED

`DepthRecorder.maybe_record` only fires on `t % every_n_ticks == 0`, but
the simulator increments `self.t` to `1` before the first tick runs, so
`t` is never `0` and the seeded starting book (before any agent has
acted) was never captured. Scrubbing the visualizer all the way to the
start showed "no book yet" even though the book was, in fact, already
seeded with liquidity. **Fix:** the simulator now records one snapshot of
the just-seeded book for every symbol at construction time, before the
first tick runs.

### 5. (Robustness) Fragile falsy-zero check in `NoiseTrader` — CONFIRMED, FIXED

`mid = view.best_bid and view.best_ask and (view.best_bid + view.best_ask) // 2`
uses Python's `and`-chaining as a `None`-check, but `0` is also falsy —
if a price of exactly `0` ever reached the book this would silently (and
incorrectly) fall through to the "no quotes yet" branch instead of using
the real mid price. Every price path is currently guarded to stay `>= 1`
(and finding #2 now makes that a hard invariant), so this wasn't
reachable today, but it's a landmine for any future change that relaxes
that guard. **Fix:** replaced with explicit `is not None` checks.

### 6. (UX) P&L chart has no legend and reuses colors past 7 agents — CONFIRMED, FIXED

The "Cumulative P&L by agent" chart draws one line per agent from a
7-color palette with no legend at all — with the shipped demo's 10
agents, three lines silently double up on a color already used by an
earlier agent, and *no* line in the chart is ever labeled. It's
decoration, not a chart, if you can't tell one line from another. **Fix:**
palette expanded to 12 visually distinct colors, and a labeled legend
(swatch + agent name, colored to match) now renders under the chart.

### 7. (UX bug) Pausing playback doesn't actually stop immediately — CONFIRMED, FIXED

`playBtn`'s click handler flips the `playing` flag but never calls
`clearTimeout` on the in-flight `playTimer`. The pending timeout still
fires once after pause is clicked, advancing the scrubber one more step
than the user asked for — at 1x speed (240ms) this is a visible,
confusing "why did it still move after I hit pause" glitch, and rapid
play/pause/play clicks could leave two timers racing. **Fix:** pausing
now clears the pending timer immediately, and the timeout callback itself
re-checks `playing` before advancing, so no ghost step can fire.

### 8. (Security/robustness) Unescaped JSON embed is script-injectable via a crafted agent name — CONFIRMED, FIXED

`report_template.py` embeds the session JSON directly inside a
`<script>` tag via plain string substitution. `json.dumps` does not
escape `</`, so an agent registered with a name like
`</script><script>alert(1)</script>` (fully possible through the
pluggable Agent SDK — an agent's `name` is developer-supplied, not
sanitized anywhere) would prematurely close the data `<script>` block and
inject arbitrary markup/script into the generated report. Reproduced:
building a report for an agent named exactly that string produced a
report that executed the injected script when opened. **Fix:** the
embedded payload now escapes `</` to `<\/` before insertion, which is
inert inside a JS string/array literal and neutralizes the injection
without changing the parsed data.

### 9. (Portability) Report file written without explicit encoding

`open(out_path, "w")` relied on the platform's default text encoding.
On a system with a non-UTF-8 default locale, a report containing
non-ASCII agent names could fail to write or round-trip incorrectly.
**Fix:** now opens with `encoding="utf-8"` explicitly.

### 10. (Correctness) `NoiseTrader` never actually crosses the spread — CONFIRMED, FIXED (found writing Phase 5 tests)

The docstring claimed `NoiseTrader` provides "small random limit orders
near the current mid price, occasionally crossing the spread with a
market order," but the implementation only ever submitted `LIMIT`
orders priced as `mid - offset` for buys and `mid + offset` for sells —
by construction, *every* buy prices below mid and *every* sell prices
above mid, so two noise-trader orders (or a noise-trader order and the
static seeded book) can never cross each other. A unit test that
registered a single `NoiseTrader` against a freshly seeded, otherwise
static book to check "one healthy agent isn't disrupted by a broken
peer" caught this directly: **zero trades over 300 ticks**, because
nothing in the scenario was ever capable of crossing the book. In the
full multi-agent demo this was masked — market makers and momentum/
mean-reversion traders generate plenty of real crossing activity — but
the noise trader itself was never contributing the background liquidity-
taking its own docstring claimed. **Fix:** `NoiseTrader` now spends a
configurable fraction of ticks (`cross_prob`, default 12%) submitting a
genuine `MARKET` order instead of a passive limit, actually taking
liquidity the way real uninformed order flow does. Re-running the full
3000-tick demo after the fix roughly doubled total trade volume (from
~1000 to ~13,000 trades across both books) with the book still never
crossing — this is exactly the kind of bug a test suite that only checks
"looks plausible in the big demo" would never have caught, and exactly
why Phase 5 writes isolated single-agent tests, not only end-to-end ones.

## Verified after fixes

Re-ran the full 3000-tick demo session (`python3 demo.py`) plus a fresh
20,000-tick stress run after every fix above: zero self-trades, zero
crossed-book ticks, zero simulator crashes, tick-0 depth snapshot present
for every symbol, and a fresh visual pass in headless Chromium (see
`tests/test_report_rendering.py`) confirms the legend renders and
play/pause no longer ghost-steps. The full automated regression suite
(`tests/`) added in Phase 5 encodes every one of these nine findings as a
permanent test so they cannot silently regress.
