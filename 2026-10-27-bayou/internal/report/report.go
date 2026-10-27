// Package report renders a network as one self-contained, interactive HTML page:
// a layered graph whose nodes show live posterior bars, with click-to-observe
// evidence, an in-browser exact inference engine (engine.js, a port of the Go
// variable elimination), CPT inspection and d-separation highlighting.
package report

import (
	"encoding/json"
	"fmt"
	"html"
	"sort"
	"strings"

	_ "embed"

	"bayou/internal/bn"
	"bayou/internal/graph"
)

//go:embed engine.js
var engineJS string

//go:embed template.html
var pageHTML string

// Engine returns the JavaScript inference engine source (also used by the tests).
func Engine() string { return engineJS }

// Box is a node's rectangle in layout coordinates.
type Box struct{ X, Y, W, H float64 }

const (
	nodeW   = 176.0
	hGap    = 40.0
	vGap    = 84.0
	headerH = 30.0
	rowH    = 21.0
	padB    = 8.0
)

// NodeHeight is the card height for a variable with the given number of states.
func NodeHeight(states int) float64 { return headerH + rowH*float64(states) + padB }

// Layout places variables in layers (longest-path depth from the roots) and
// orders each layer by the barycentre of its neighbours to reduce crossings.
func Layout(n *bn.Network) []Box {
	nv := len(n.Vars)
	depth := make([]int, nv)
	for _, v := range n.TopoOrder() {
		for _, p := range n.Vars[v].Parents {
			if depth[p]+1 > depth[v] {
				depth[v] = depth[p] + 1
			}
		}
	}
	maxD := 0
	for _, d := range depth {
		if d > maxD {
			maxD = d
		}
	}
	layers := make([][]int, maxD+1)
	for v := 0; v < nv; v++ {
		layers[depth[v]] = append(layers[depth[v]], v)
	}
	children := n.Children()
	pos := make([]float64, nv)
	for _, l := range layers {
		for i, v := range l {
			pos[v] = float64(i)
		}
	}
	bary := func(v int, nbrs []int) float64 {
		if len(nbrs) == 0 {
			return pos[v]
		}
		s := 0.0
		for _, u := range nbrs {
			s += pos[u]
		}
		return s / float64(len(nbrs))
	}
	for sweep := 0; sweep < 6; sweep++ {
		for d := 1; d <= maxD; d++ { // down: order by parents
			l := layers[d]
			sort.SliceStable(l, func(i, j int) bool { return bary(l[i], n.Vars[l[i]].Parents) < bary(l[j], n.Vars[l[j]].Parents) })
			for i, v := range l {
				pos[v] = float64(i)
			}
		}
		for d := maxD - 1; d >= 0; d-- { // up: order by children
			l := layers[d]
			sort.SliceStable(l, func(i, j int) bool { return bary(l[i], children[l[i]]) < bary(l[j], children[l[j]]) })
			for i, v := range l {
				pos[v] = float64(i)
			}
		}
	}
	boxes := make([]Box, nv)
	widest := 0.0
	for _, l := range layers {
		if w := float64(len(l))*(nodeW+hGap) - hGap; w > widest {
			widest = w
		}
	}
	y := 0.0
	for _, l := range layers {
		rowW := float64(len(l))*(nodeW+hGap) - hGap
		x := (widest - rowW) / 2
		tallest := 0.0
		for _, v := range l {
			h := NodeHeight(n.Card(v))
			boxes[v] = Box{x, y, nodeW, h}
			x += nodeW + hGap
			if h > tallest {
				tallest = h
			}
		}
		y += tallest + vGap
	}
	return boxes
}

type jsVar struct {
	Name    string    `json:"name"`
	States  []string  `json:"states"`
	Parents []int     `json:"parents"`
	CPT     []float64 `json:"cpt"`
}

type jsData struct {
	Name      string      `json:"name"`
	Vars      []jsVar     `json:"vars"`
	Boxes     []Box       `json:"boxes"`
	Evidence  map[int]int `json:"evidence"`
	Width     float64     `json:"width"`
	Height    float64     `json:"height"`
	Treewidth int         `json:"treewidth"`
}

// MaxVars bounds the size of a report (the in-browser engine re-runs on every click).
const MaxVars = 120

// Build renders the page. ev is the initial evidence.
func Build(n *bn.Network, ev bn.Evidence) (string, error) {
	if len(n.Vars) > MaxVars {
		return "", fmt.Errorf("report supports at most %d variables (network has %d)", MaxVars, len(n.Vars))
	}
	an := graph.Analyze(n, graph.MinFill)
	if an.Log2States > 20 {
		return "", fmt.Errorf("network too densely connected for in-browser inference (largest table ≈ 2^%.0f); reduce it or use `bayou approx`", an.Log2States)
	}
	d := jsData{Name: n.Name, Boxes: Layout(n), Evidence: map[int]int(ev), Treewidth: an.Width}
	if d.Evidence == nil {
		d.Evidence = map[int]int{}
	}
	for _, v := range n.Vars {
		d.Vars = append(d.Vars, jsVar{v.Name, v.States, nonNil(v.Parents), v.CPT})
	}
	for _, b := range d.Boxes {
		d.Width = max(d.Width, b.X+b.W)
		d.Height = max(d.Height, b.Y+b.H)
	}
	raw, err := json.Marshal(d)
	if err != nil {
		return "", err
	}
	page := pageHTML
	page = strings.Replace(page, "{{TITLE}}", html.EscapeString(n.Name), 1)
	page = strings.Replace(page, "/*{{ENGINE}}*/", strings.ReplaceAll(engineJS, "</script", `<\/script`), 1)
	page = strings.Replace(page, "{{DATA}}", jsonForScript(raw), 1)
	return page, nil
}

func nonNil(a []int) []int {
	if a == nil {
		return []int{}
	}
	return a
}

// jsonForScript makes JSON safe inside an inline <script type="application/json">.
func jsonForScript(b []byte) string {
	s := string(b)
	s = strings.ReplaceAll(s, "<", `<`)
	s = strings.ReplaceAll(s, ">", `>`)
	s = strings.ReplaceAll(s, "&", `&`)
	s = strings.ReplaceAll(s, " ", ` `)
	s = strings.ReplaceAll(s, " ", ` `)
	return s
}
