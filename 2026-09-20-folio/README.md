# Folio

A from-scratch HTML/CSS layout & rendering engine — a toy browser engine.
Parses real HTML into a DOM, real CSS into a cascade, runs a real block/
inline box-model layout algorithm, and paints the result to both an
independently-decodable PNG and an interactive DOM/box-model inspector.

**Status: Phase 2 (core build) complete.** All 4 required features work
end to end: HTML parsing to a real DOM, CSS parsing + cascade to computed
styles, block/inline box-model layout with real text wrapping, and paint
to an independently-decodable PNG. See [PLAN.md](PLAN.md) for the full
architecture and feature list.

## Why this project

See "Why this is interesting" in [PLAN.md](PLAN.md) — short version: every
prior build in this repo's history has *used* a browser to render its
visualizer, but none has ever built the HTML/CSS engine that does that
rendering. Folio is that engine, with real headless-Chromium differential
testing as its correctness oracle.

## Planned feature list

1. HTML parser → real DOM tree (required)
2. CSS parser + cascade → computed style per node (required)
3. Block + inline box-model layout engine (required)
4. Paint to an independently-decodable PNG (required)
5. Float layout + clearance (stretch)
6. Interactive DOM/box-model inspector (stretch)

## How to run

```
python3 -m folio.cli render examples/basic.html -o out.png -w 500
python3 -m folio.cli info examples/basic.html
```

`render` runs the full pipeline (HTML → DOM → cascade → layout → paint)
and writes a real PNG, viewable in any image viewer. `info` prints DOM/CSS/
layout stats without writing a file. Try it on `examples/basic.html`, which
exercises the box model, inline styling (bold/italic/links), and list
layout in one page.

Stretch features (float layout, the interactive inspector), tests, and a
`demo.sh` are not implemented yet — see PLAN.md's feature list for what's
still to come.
