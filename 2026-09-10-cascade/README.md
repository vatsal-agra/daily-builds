# Cascade

A browser layout engine built entirely from scratch: an HTML parser, a CSS
parser with the real cascade (specificity/inheritance/`!important`), a
layout engine implementing the actual box model plus block/inline
formatting contexts with margin collapsing, a flexbox subset, and a
from-scratch PNG rasterizer with a hand-rolled bitmap font — no browser, no
HTML/CSS library, no imaging library anywhere in the pipeline.

**Status: Phase 3 (adversarial review) complete.** All 4 required features
work end-to-end: HTML parsing, CSS parsing + cascade, layout, and
rendering to a real PNG. The flexbox stretch feature is also already
working. See `PLAN.md` for the full concept and feature list, and
`REVIEW.md` for the adversarial review's findings and fixes (7 real bugs
found and fixed, including a critical percentage-height bug and a
`:not()` selector that silently matched nothing).

## Try it

```
cd src
python3 cli.py render ../examples/cards.html --width 900 --out out.png
python3 cli.py layout ../examples/article.html --width 720   # dump the box tree
python3 cli.py demo                                          # render every example
```

## Tests

```
cd tests
python3 -m unittest discover -s . -p "test_*.py" -v
```

133/133 tests passing as of Phase 3.
