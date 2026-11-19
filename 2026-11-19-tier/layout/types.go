// Package layout implements a layered (Sugiyama-style) graph drawing pipeline:
// cycle removal, network-simplex layering, crossing minimisation,
// Brandes–Köpf coordinate assignment and edge routing.
package layout

import "fmt"

// Input graph -------------------------------------------------------------

// InNode is a node to lay out. W/H are the drawn size (before orientation).
type InNode struct {
	ID    string
	Label string
	W, H  float64
	Shape string // "box" | "ellipse"
}

// InEdge is a directed edge between node indices.
type InEdge struct {
	From, To int
	Weight   int // >=1, higher = shorter & straighter
	MinLen   int // minimum rank span, >=1 (0 allowed => same-rank not supported, coerced to 1)
	Label    string
}

// Graph is the layout input.
type Graph struct {
	Nodes []InNode
	Edges []InEdge
}

// Options selects strategies; zero value = best defaults.
type Options struct {
	RankDir string  // "TB" (default) or "LR"
	NodeSep float64 // gap between neighbours in a layer (default 24)
	RankSep float64 // gap between layers (default 56)
	Acyclic string  // "greedy" (default) | "dfs"
	Ranker  string  // "simplex" (default) | "longest"
	Order   string  // "sweep" (default) | "none"
	Coord   string  // "bk" (default) | "packed"
	Sweeps  int     // max crossing-min iterations (default 24)
}

func (o *Options) defaults() error {
	if o.RankDir == "" {
		o.RankDir = "TB"
	}
	if o.RankDir != "TB" && o.RankDir != "LR" {
		return fmt.Errorf("rankdir must be TB or LR, got %q", o.RankDir)
	}
	if o.NodeSep <= 0 {
		o.NodeSep = 24
	}
	if o.RankSep <= 0 {
		o.RankSep = 56
	}
	if o.Acyclic == "" {
		o.Acyclic = "greedy"
	}
	if o.Acyclic != "greedy" && o.Acyclic != "dfs" {
		return fmt.Errorf("unknown acyclic strategy %q", o.Acyclic)
	}
	if o.Ranker == "" {
		o.Ranker = "simplex"
	}
	if o.Ranker != "simplex" && o.Ranker != "longest" {
		return fmt.Errorf("unknown ranker %q", o.Ranker)
	}
	if o.Order == "" {
		o.Order = "sweep"
	}
	if o.Order != "sweep" && o.Order != "none" {
		return fmt.Errorf("unknown order strategy %q", o.Order)
	}
	if o.Coord == "" {
		o.Coord = "bk"
	}
	if o.Coord != "bk" && o.Coord != "packed" {
		return fmt.Errorf("unknown coord strategy %q", o.Coord)
	}
	if o.Sweeps <= 0 {
		o.Sweeps = 24
	}
	return nil
}

// Output ------------------------------------------------------------------

// Pt is a 2-D point.
type Pt struct{ X, Y float64 }

// NodeBox is a placed node (centre coordinates).
type NodeBox struct {
	InNode
	X, Y  float64
	Rank  int
	Order int
}

// EdgeRoute is a routed edge. Points run From -> To (arrow at the end) and
// include the border points. Reversed marks edges flipped to break a cycle.
type EdgeRoute struct {
	InEdge
	Points   []Pt
	Reversed bool
	SelfLoop bool
}

// Metrics quantify layout quality.
type Metrics struct {
	Crossings  int     // edge crossings in the proper layered graph
	EdgeLength float64 // sum of weight*rank span over edges
	Reversed   int     // edges reversed to break cycles
	Bends      int     // lateral direction changes along edges
	Layers     int
	MaxLayer   int // widest layer, in nodes (incl. dummies)
	Dummies    int
	Width      float64
	Height     float64
}

// Result is a finished layout.
type Result struct {
	Nodes   []NodeBox
	Edges   []EdgeRoute
	Width   float64
	Height  float64
	Metrics Metrics
	Opts    Options
}
