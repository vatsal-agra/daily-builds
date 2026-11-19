package dot

import (
	"fmt"
	"strconv"
	"strings"

	"tier/layout"
)

const (
	charW = 7.4
	lineH = 17.0
)

func labelLines(s string) []string {
	s = strings.ReplaceAll(s, `\n`, "\n")
	return strings.Split(s, "\n")
}

func atoiAttr(m map[string]string, key string, def int) (int, error) {
	v, ok := m[key]
	if !ok {
		return def, nil
	}
	f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
	if err != nil || f != float64(int(f)) {
		return 0, fmt.Errorf("attribute %s=%q must be an integer", key, v)
	}
	return int(f), nil
}

func floatAttr(m map[string]string, key string) (float64, bool, error) {
	v, ok := m[key]
	if !ok {
		return 0, false, nil
	}
	f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
	if err != nil || f < 0 {
		return 0, false, fmt.Errorf("attribute %s=%q must be a non-negative number", key, v)
	}
	return f, true, nil
}

// ToLayout converts a parsed graph into layout input. Graph attributes
// rankdir, nodesep and ranksep (points) are folded into the returned options
// unless already set on base.
func (g *Graph) ToLayout(base layout.Options) (layout.Graph, layout.Options, error) {
	opts := base
	if v, ok := g.Attrs["rankdir"]; ok && opts.RankDir == "" {
		switch strings.ToUpper(v) {
		case "TB", "TD":
			opts.RankDir = "TB"
		case "LR":
			opts.RankDir = "LR"
		default:
			return layout.Graph{}, opts, fmt.Errorf("rankdir=%q unsupported (use TB or LR)", v)
		}
	}
	if f, ok, err := floatAttr(g.Attrs, "nodesep"); err != nil {
		return layout.Graph{}, opts, err
	} else if ok && opts.NodeSep == 0 {
		opts.NodeSep = f
	}
	if f, ok, err := floatAttr(g.Attrs, "ranksep"); err != nil {
		return layout.Graph{}, opts, err
	} else if ok && opts.RankSep == 0 {
		opts.RankSep = f
	}
	idx := map[string]int{}
	var lg layout.Graph
	for i, n := range g.Nodes {
		idx[n.ID] = i
		label := n.ID
		if l, ok := n.Attrs["label"]; ok {
			label = strings.ReplaceAll(l, `\N`, n.ID)
		}
		shape := strings.ToLower(n.Attrs["shape"])
		switch shape {
		case "", "box", "rect", "rectangle", "square":
			shape = "box"
		case "ellipse", "oval", "circle":
			shape = "ellipse"
		default:
			return layout.Graph{}, opts, fmt.Errorf("node %q: unsupported shape %q (box, ellipse)", n.ID, n.Attrs["shape"])
		}
		maxc := 0
		lines := labelLines(label)
		for _, ln := range lines {
			if c := len([]rune(ln)); c > maxc {
				maxc = c
			}
		}
		w := float64(maxc)*charW + 24
		h := float64(len(lines))*lineH + 14
		if shape == "ellipse" {
			w, h = w*1.3, h*1.25
		}
		if w < 36 {
			w = 36
		}
		if v, ok, err := floatAttr(n.Attrs, "width"); err != nil {
			return layout.Graph{}, opts, fmt.Errorf("node %q: %w", n.ID, err)
		} else if ok && v > w {
			w = v
		}
		if v, ok, err := floatAttr(n.Attrs, "height"); err != nil {
			return layout.Graph{}, opts, fmt.Errorf("node %q: %w", n.ID, err)
		} else if ok && v > h {
			h = v
		}
		lg.Nodes = append(lg.Nodes, layout.InNode{ID: n.ID, Label: label, W: w, H: h, Shape: shape})
	}
	for _, e := range g.Edges {
		wt, err := atoiAttr(e.Attrs, "weight", 1)
		if err != nil {
			return layout.Graph{}, opts, fmt.Errorf("edge %s->%s: %w", e.From, e.To, err)
		}
		ml, err := atoiAttr(e.Attrs, "minlen", 1)
		if err != nil {
			return layout.Graph{}, opts, fmt.Errorf("edge %s->%s: %w", e.From, e.To, err)
		}
		if wt < 1 || ml < 1 {
			return layout.Graph{}, opts, fmt.Errorf("edge %s->%s: weight and minlen must be >= 1", e.From, e.To)
		}
		lg.Edges = append(lg.Edges, layout.InEdge{From: idx[e.From], To: idx[e.To], Weight: wt, MinLen: ml, Label: e.Attrs["label"]})
	}
	return lg, opts, nil
}
