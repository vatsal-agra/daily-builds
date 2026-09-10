# Cascade

A browser layout engine built entirely from scratch: an HTML parser, a CSS
parser with the real cascade (specificity/inheritance/`!important`), a
layout engine implementing the actual box model plus block/inline
formatting contexts with margin collapsing, a flexbox subset, and a
from-scratch PNG rasterizer with a hand-rolled bitmap font — no browser, no
HTML/CSS library, no imaging library anywhere in the pipeline.

**Status: Phase 5 (verification) complete.** All 4 required features and
all 3 stretch features are shipped and verified — including a Chromium
differential oracle that renders the same pages in real headless Chromium
and finds Cascade's layout **pixel-identical** across box model, margin
collapsing, percentages, and flexbox. See `PLAN.md` for the full
concept/feature list and `REVIEW.md` for the adversarial review.

Run `./demo.sh` for a single command that exercises every feature end to
end and reports pass/fail (15/15 as of this commit, exits 0).

## Try it

```
cd src
python3 cli.py render ../examples/cards.html --width 900 --out out.png     # -> real PNG
python3 cli.py layout ../examples/article.html --width 720                 # dump the box tree
python3 cli.py viz ../examples/cards.html --width 900 --out inspector.html # interactive box inspector
python3 cli.py demo                                                        # render every example
```

## Tests

```
cd tests
python3 -m unittest discover -s . -p "test_*.py" -v
```

153/153 tests passing (unit tests for every stage + a Chromium
differential oracle + headless-browser UI smoke tests). The Chromium/
Playwright-backed tests (`test_diff_oracle.py`, `test_viz_ui.py`) skip
themselves cleanly if the oracle isn't set up; to enable them:

```
cd tools/oracle && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
```

(Chromium itself is already present in this environment at
`/opt/pw-browsers/chromium` — only the `playwright` npm package needs
installing, hence the skip-download flag.)

## Layout

```
src/
  html_tokenizer.py, html_parser.py, dom.py   HTML -> DOM tree
  css_tokenizer.py, css_parser.py, selector.py CSS -> rules + selectors
  cascade.py, css_values.py                    the cascade -> computed style
  layout.py, flexbox.py, font.py               computed style -> box tree
  png_encoder.py, paint.py                     box tree -> real PNG pixels
  viz.py                                       box tree -> interactive HTML inspector
  cli.py                                       the `cascade` command
tests/          unit tests + the Chromium differential oracle + UI tests
tools/oracle/   Node/Playwright harness the oracle tests drive
examples/       example pages rendered by `cascade demo`
renders/        their committed PNG/HTML output
```
