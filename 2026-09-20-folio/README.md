# Folio

A from-scratch HTML/CSS layout & rendering engine — a toy browser engine.
Parses real HTML into a DOM, real CSS into a cascade, runs a real block/
inline box-model layout algorithm, and paints the result to both an
independently-decodable PNG and an interactive DOM/box-model inspector.

**Status: Phase 1 (plan) complete.** See [PLAN.md](PLAN.md) for the full
architecture, feature list, and verification strategy. Implementation
starts in Phase 2.

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

Not yet runnable — this is the plan-only commit. Instructions will be
filled in as each phase lands.
