# Tier — PLAN

## Concept
**Tier** is a from-scratch **layered (Sugiyama) graph-drawing engine**: it reads a graph in a DOT subset and produces a hierarchical drawing as SVG/HTML, implementing every classic stage itself — cycle removal, optimal layering via **network simplex**, **crossing minimisation**, **Brandes–Köpf** coordinate assignment, and edge routing.

## Why it's interesting
Graph layout is a pipeline of NP-hard problems (feedback arc set, crossing minimisation) each solved by a well-known heuristic or an exact polynomial algorithm (network simplex for layering). Quality is *measurable* (edge length, crossings, width) so correctness is verifiable by oracles rather than by eye. No earlier entry does graph drawing.

## Architecture
```
DOT text --parse--> Graph --cycle removal--> DAG --network simplex--> ranks
  --insert virtual nodes--> proper layered graph --crossing min--> orders
  --Brandes-Köpf--> x coords --route--> polylines/splines --render--> SVG / HTML
```
Packages: `dot/` (lexer+parser), `layout/` (graph, acyclic, rank, order, coord, route, metrics), `render/` (SVG, HTML), `cmd/tier` (CLI), `verify.sh`.

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | DOT-subset parser (digraph/graph, node/edge attrs, `->` chains, subgraph-free, quoted ids, comments) with positioned errors | **required** |
| 2 | Cycle removal (DFS + greedy Eades–Lin–Smyth feedback arc set) with reversed-edge restoration; self-loops, multi-edges | **required** |
| 3 | Optimal layering by **network simplex** (min Σ weight·length, feasible tree, cut values, tight-tree) with min-length attr | **required** |
| 4 | Crossing minimisation (weighted-median/barycenter sweeps + transpose) and **Brandes–Köpf** x-coordinates + SVG output | **required** |
| 5 | Edge routing: smooth Bézier splines through virtual-node chains (+ arrowheads, reversed edges, self-loops) | stretch |
| 6 | Layout metrics + HTML report comparing strategies (longest-path vs network simplex; no-ordering vs sweeps) | stretch |
| 7 | Left-to-right orientation (`rankdir=LR`) and node shapes/labels sized from text | stretch |
| 8 | Optimal-crossings brute-force oracle for small graphs to measure heuristic gap | stretch |
