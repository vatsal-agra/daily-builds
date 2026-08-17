# Folio

A browser rendering engine built from scratch in pure Python: HTML parser →
DOM → CSS cascade → computed styles → CSS2.1 box-model layout → paint —
verified against real headless Chromium, not just against itself.

**Status: Phase 5 (verification) complete.** All four required features
plus both stretch features — float layout and an interactive box-model
inspector with a live Chromium oracle-diff panel — are implemented,
hostile-reviewed, and verified green: `demo.sh` runs the full test suite
(138 tests, including a Chromium differential suite) plus a narrated
end-to-end demo and CLI smoke/regression checks, 13/13. See `PLAN.md` for
the architecture/feature list and `REVIEW.md` for the full
adversarial-review writeup (14 real bugs found and fixed).

```bash
bash demo.sh   # full verification: tests + demo + CLI smoke checks
```

## Try the inspector

```bash
python3 cli.py inspect fixtures/sample1.html -o inspect.html --width 600
# open inspect.html in a browser: click any element for its box model
```

## Quick start

```bash
python3 cli.py render fixtures/sample1.html -o out.svg --width 600
python3 cli.py layout fixtures/sample1.html --width 600   # dump the box tree
python3 cli.py cascade fixtures/sample1.html              # dump computed styles
python3 cli.py parse fixtures/sample1.html                 # dump the DOM tree

python3 -m unittest discover -s tests -v
```

The Chromium-oracle half of the test suite needs `playwright` (`pip install
-r requirements-dev.txt`, browser already present at
`/opt/pw-browsers/chromium-1194` in this environment) — without it, that one
test class is skipped and everything else still runs.

More detail (full feature list, verification story, "what's next") lands in
Phase 6.
