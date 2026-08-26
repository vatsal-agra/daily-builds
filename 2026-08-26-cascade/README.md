# Cascade

A from-scratch HTML/CSS layout and rendering engine. See [PLAN.md](PLAN.md)
for the concept, architecture, and full feature list.

**Status: Phase 2 (core build) complete.** All four required features work
end-to-end:

1. HTML parser (`cascade/html_parser.py`) — tokenizer + tree-construction
   with implicit tag closing and malformed-markup recovery.
2. CSS parser + cascade (`cascade/css_parser.py`, `cascade/cascade.py`) —
   real selector grammar, specificity, `!important`, inheritance.
3. Layout engine (`cascade/layout.py`) — box model, block formatting
   context with margin collapsing, inline formatting context with line
   breaking, text-align, and float layout.
4. Paint (`cascade/paint.py`) — SVG renderer with backgrounds, per-side
   borders, and positioned text.

## Try it

```
python3 cli.py render testpages/01_box_model.html -o /tmp/out.svg
python3 cli.py dump-boxes testpages/04_floats.html
```

## Differential verification against real Chromium

This sandbox has headless Chromium pre-installed. `oracle/run_diff.py`
renders every `testpages/*.html` fixture with Cascade's own engine *and*
with real Chromium (via `oracle/diff.cjs` + Playwright), then diffs every
element's `getBoundingClientRect()`-equivalent geometry:

```
python3 oracle/run_diff.py testpages
```

Current result: **7/7 test pages, 0 mismatches** against real Chromium
(box model, margin collapsing, text wrapping/alignment, floats + clear,
inline-block shrink-to-fit, cascade/specificity, and margin:auto
centering).

**Status: Phase 4 (stretch + polish) complete.** All three planned
stretch features are implemented (not just the required one):

- **Float layout** — `float: left/right`, `clear`, real "shelf" placement.
- **Chromium differential oracle** — `oracle/run_diff.py`, 7/7 test pages
  match real headless Chromium.
- **Interactive server-backed playground** — `python3 server.py`, then
  open http://127.0.0.1:8420/. Edit HTML/CSS live, hover any rendered box
  to see its real margin/border/padding/content edges and exact pixel
  dimensions (a Chrome-DevTools-style box-model inspector), all computed
  by the real engine server-side — the browser client holds zero layout
  logic, same pattern as this repo's Gambit/Formulate/Trove.

Polish this phase: fixed a `#zzz`-style malformed-color crash, a raw
Python traceback on a missing CLI file, and quiet `BrokenPipeError`
handling when piped into e.g. `head`.

Adversarial review found and fixed 8 real bugs, including one
consequential one: whitespace-only text between block siblings (i.e.
completely normal indented HTML) was silently blocking margin
collapsing. Full findings, fixes, and the deliberate scope cuts that are
*not* bugs: [REVIEW.md](REVIEW.md).

```
python3 -m unittest discover -s tests   # 60/60 pass
python3 oracle/run_diff.py testpages    # 7/7 pages, 0 mismatches vs. Chromium
python3 server.py                       # interactive playground on :8420
```

Next: full verification pass (Phase 5), ship (Phase 6).
