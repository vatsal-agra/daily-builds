# Cascade

A browser layout engine built entirely from scratch: an HTML parser, a CSS
parser with the real cascade (specificity/inheritance/`!important`), a
layout engine implementing the actual box model plus block/inline
formatting contexts with margin collapsing, a flexbox subset, and a
from-scratch PNG rasterizer with a hand-rolled bitmap font — no browser, no
HTML/CSS library, no imaging library anywhere in the pipeline.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end: HTML parsing, CSS parsing + cascade, layout, and rendering to a
real PNG. The flexbox stretch feature is also already working. See
`PLAN.md` for the full concept and feature list.

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

121/121 tests passing as of Phase 2.
