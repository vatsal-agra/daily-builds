# Adversarial review (Phase 3)

Approach: read every code path as a hostile user trying to break it --
malformed queries, missing properties, boundary values, type confusion,
and the specific crash-timing windows a WAL/checkpoint design opens up --
then fix every real issue found and pin it down with a regression test.
9 real issues found (8 in Phase 3's review pass, 1 more in Phase 5 while
actually executing this project's own README quickstart verbatim), all
fixed below; a fresh run of `demo.sh` and the full test suite hits zero of
them.

## 1. CRITICAL -- reusing a variable as both a node and a relationship
silently corrupted results

`MATCH (a)-[a:KNOWS]->(b) RETURN a` parsed and ran with **no error**, but
`RETURN a` returned the *relationship*, not the node: `compute_var_kinds`
built `{var: kind}` by scanning pattern positions in order and let a later
assignment silently overwrite an earlier one, and the chain matcher used
the same binding-dict key (`a`) for both the node id and the edge id --
the edge id overwrote the node id in the very same dict slot with no
signal anything had gone wrong. This is the "silent wrong answer" class
of bug this repo's other builds have flagged as the worst kind: it runs,
it returns a plausible-looking non-empty result, and it's wrong.
**Fix:** `compute_var_kinds` now raises a clear `SkeinError` the moment a
variable is bound to two different kinds. Regression:
`test_variable_reused_as_node_and_relationship_raises`.

## 2. Arithmetic/comparison on missing or mismatched-type properties
leaked raw Python exceptions

`RETURN a.nickname + 1` where `nickname` doesn't exist raised an uncaught
`TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'`;
`RETURN 1 / 0` raised a raw `ZeroDivisionError`; `RETURN -a.name` raised a
raw `TypeError` from negating a string; `WHERE a.name > a.age` raised a
raw `TypeError` comparing `str` to `int`. All four are ordinary query
mistakes a real user would make, and none of them were caught anywhere
between `eval_expr` and the CLI's `main()`, which only catches
`SkeinError`/`TransactionError`/`ParseError`/`LexError` -- so a plain
`python -m skein.cli query` would dump a Python traceback for a typo.
**Fix:** binary operators route through a new `_safe_binop` that catches
`TypeError`/`ZeroDivisionError` and re-raises as `SkeinError` with a
message naming the operands; unary `-` gets the same treatment. Regression:
`test_arithmetic_on_missing_property_raises_clean_error`,
`test_division_by_zero_raises_clean_error`,
`test_negating_a_string_raises_clean_error`,
`test_comparing_incompatible_types_raises_clean_error`.

## 3. `labels()`/`type()`/`id()` called with the wrong arity or on the
wrong kind of variable crashed or silently misread their argument

`labels()` (no args) raised a raw `IndexError: list index out of range`
(so did `type()`). Worse: `labels(a.name)` -- a `PropAccess`, not a plain
variable -- did **not** error at all; the function implementation blindly
read `expr.args[0].var`, which happens to exist on a `PropAccess` node too
(it's the variable part of `a.name`), so `labels(a.name)` silently ran as
if it had been written `labels(a)` and returned real-looking labels for
the wrong expression. `type(a)` called on a node (not a relationship)
would have raised a raw `AttributeError` (`Node` has no `.type`).
**Fix:** every function now validates its argument is a single bare
variable reference of the right kind (node for `labels`, relationship for
`type`) via a shared `_single_var_arg` helper, raising `SkeinError`
otherwise. Regression: `test_function_call_arity_and_type_validated`.

## 4. `count(*)` mixed with other RETURN items silently returned the
literal `1` per row instead of a real count -- a fake feature

`RETURN count(*), a.name` and `RETURN count(a)` both parsed and ran
without error, returning `count(*): 1` on *every* row -- not a crash, not
an aggregate, just the literal placeholder value the (unfinished) function
implementation happened to return, indistinguishable at a glance from a
real per-group count of 1. This is exactly the "looks like it works but
doesn't" class of bug Galley's review caught in this repo's history (a
`looseness` parameter that silently did nothing). Full `GROUP BY` was
explicitly out of scope for this build (documented in PLAN.md/README.md),
but shipping a function that *pretends* to aggregate is worse than not
having it. **Fix:** `count(*)` alone as the sole top-level RETURN
expression remains the one supported, real, tested aggregate path (handled
by `execute()` before per-row projection); every other use of `count(...)`
now raises `SkeinError` naming the restriction instead of returning a
placeholder. Regression: `test_count_star_mixed_with_other_columns_refused_not_faked`.

## 5. Property-map equality could disagree between an index-backed match
and a full scan

`MATCH (p:Person {active: 1})` matched **both** a node with `active: true`
and one with `active: 1` under a full scan (Python's `True == 1`), but
matched **only** the literal `1` once a `(Person, active)` index existed
(`PropertyIndex` deliberately keeps bool and number in separate rank
groups so a real numeric range index isn't polluted by booleans). That's
precisely the property the query planner promises never to violate
("index vs. scan return identical results") -- silently broken for any
boolean-vs-integer property. **Fix:** added `index.values_equal()` (the
same rank-based equality `PropertyIndex` already uses internally) and
switched `node_matches`/`rel_matches`'s property-map filtering to use it
instead of Python's native `!=`, so a scan and an index now agree by
construction; this also fixed a related latent bug where a property-map
filter for `null` matched nodes *missing* the property entirely (via
`dict.get` defaulting to `None`) rather than only nodes explicitly holding
`null`. Regression: `test_index_and_scan_agree_on_bool_vs_int`.

## 6. `--top` accepted a negative value and silently returned "all but the
last N" via Python's negative-slice trap

`skein algo pagerank db --top -1` didn't error -- it returned every row
except the last one, because `ranked[:-1]` is a valid (if nonsensical
here) Python slice. This is the same class of footgun this repo's other
CLI-fronted builds (Trove's `--top -1`, Glean's `--top-k -1`) have hit and
fixed before; it slipped through here despite knowing the pattern, which
is itself the lesson -- every new integer CLI flag needs this check, not
just the ones a past postmortem happened to name. **Fix:**
`cmd_algo_pagerank` now rejects `--top <= 0` with a clean `SkeinError`
before running anything. Regression: `test_pagerank_rejects_negative_top`.

## 7. `PropertyIndex.add` wasn't idempotent -- a crash between a
checkpoint's snapshot write and its WAL truncation could double an index

`checkpoint()` writes a full snapshot (atomically, via `os.replace`) and
*then* truncates the WAL. Those are two separate durable operations, not
one transaction: a crash landing between them leaves a WAL on disk that
still contains transactions the just-written snapshot *already* reflects.
On the next open, `_load()` loads the snapshot and then replays that
stale WAL on top of it, re-applying the same `create_node`/`set_prop`/
`create_index` ops a second time. Every other piece of state tolerates
this by construction (dict assignment and set membership are naturally
idempotent), but `PropertyIndex.add` used a bare `bisect.insort`, which
would happily insert the same `(value, node_id)` entry twice -- silently
turning one node into two entries in the index, so `MATCH` on that
property would return the same node id twice. Found by static reasoning
about the checkpoint's two-write sequence, not by observing a failure --
the crash window is real but narrow enough that a live test couldn't
reliably hit it. **Fix:** `PropertyIndex.add` now checks for an existing
identical entry before inserting. Regression:
`test_property_index_survives_double_apply_of_same_op` (directly re-applies
the same op twice, reproducing exactly what a stale-WAL replay would do).

## 8. Minor: a delete-clause row that matches the same node twice (a
node reachable via more than one path in the same MATCH) used to be safe
only by luck

`MATCH (a:Person {name:'Alice'})-[:KNOWS]->(b:Person) DETACH DELETE a`
matches Alice once per outgoing edge, so the delete loop processes the
same node id more than once. This turned out to already be guarded
correctly (`if vid in graph.nodes: ...` before each delete/detach call),
but it wasn't covered by a test proving it, so a future refactor could
break it silently. Added a positive test
(`test_delete_requires_detach_for_connected_node` in
`tests/test_query.py`, extended, plus a dedicated multi-match check run
during this review) rather than leaving it implicit.

## Scope limitations documented rather than "fixed"

Two things noticed during review are deliberate scope boundaries, not
bugs, and are called out in README.md rather than silently left for
someone to discover: SkeinQL matches one connected path pattern per
`MATCH` (no comma-separated multi-pattern/cartesian-product matches), and
CSV import's `_parse_value` type-sniffing will turn a leading-zero string
like `"007"` into the integer `7` (the same behavior most CSV-to-typed
importers, including `pandas.read_csv`, have by default) -- a real
tradeoff for a bulk-import tool doing automatic type inference, not an
oversight.

## 9. CRITICAL, found during Phase 5 verification -- a second `CREATE`
clause silently discarded the first

Actually running this README's own quickstart commands verbatim (rather
than trusting the hand-picked examples already in the test suite) surfaced
a bug none of the above caught: `CREATE (a:Person {name: 'Alice'}) CREATE
(a)-[:KNOWS]->(b:Person {name: 'Bob'})` -- two `CREATE` clauses in one
statement, an entirely ordinary thing to write -- ran with no error but
produced a labelless, propless ghost node instead of a real, named Alice
connected to Bob. `Statement.create` was a single `Optional[PathPattern]`
field, so the parser's clause loop simply overwrote it on the second
`CREATE`, discarding the first pattern (and the labels/properties on `a`
it carried) entirely; `apply_create` then found `a` unbound and created a
brand-new, bare node for it instead of reusing the one the (silently
dropped) first clause was supposed to create. Same failure class as
finding #1: it runs, it looks plausible, it's wrong -- and this one shipped
in the project's own documented quickstart, caught only by actually
executing every command in README.md rather than trusting it. **Fix:**
`Statement.create` is now a list of patterns, applied in order against a
shared binding dict (so a variable bound by an earlier `CREATE` clause is
correctly reused, not re-created, by a later one); `compute_var_kinds`
updated to scan the whole list. Regression:
`test_multiple_create_clauses_share_bindings_not_overwrite`.

## Verification

All 9 fixes are covered by dedicated regression tests (in
`tests/test_query.py::TestAdversarialReviewRegressions`,
`tests/test_storage.py`, and `tests/test_cli.py`). Full suite: 93/93
green. `demo.sh` green end-to-end after every fix, including a real
headless-Chromium pass over the visualizer and 5 rounds of a real
`kill -9` mid-transaction against the crash-demo database.
