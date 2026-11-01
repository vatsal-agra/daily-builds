// Package viz renders planner traces into a single self-contained HTML replay viewer.
package viz

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"

	"wayfinder/grid"
	"wayfinder/plan"
)

//go:embed template.html
var template string

type algoJSON struct {
	Name      string   `json:"name"`
	Found     bool     `json:"found"`
	Cost      float64  `json:"cost"`
	Expanded  int      `json:"expanded"`
	Generated int      `json:"generated"`
	Micros    int64    `json:"micros"`
	Path      [][2]int `json:"path"`
	Order     []int32  `json:"order"`
	Note      string   `json:"note,omitempty"`
}

type eventJSON struct {
	Step    int      `json:"step"`
	Pos     [2]int   `json:"pos"`
	Changed int      `json:"changed"`
	DStar   int      `json:"dstar"`
	AStar   int      `json:"astar"`
	Cost    *float64 `json:"cost"`
	Order   []int32  `json:"order"`
	Plan    [][2]int `json:"plan"`
	Found   [][2]int `json:"found"`
}

type exploreJSON struct {
	Radius     int         `json:"radius"`
	Reached    bool        `json:"reached"`
	Stuck      bool        `json:"stuck"`
	Trail      [][2]int    `json:"trail"`
	Travelled  float64     `json:"travelled"`
	Events     []eventJSON `json:"events"`
	DStarTotal int         `json:"dstarTotal"`
	AStarTotal int         `json:"astarTotal"`
}

type pageJSON struct {
	Title   string       `json:"title"`
	W       int          `json:"w"`
	H       int          `json:"h"`
	Cost    string       `json:"cost"` // one digit per cell, '0' = wall
	Start   [2]int       `json:"start"`
	Goal    [2]int       `json:"goal"`
	Algos   []algoJSON   `json:"algos"`
	Explore *exploreJSON `json:"explore,omitempty"`
}

func pts(p []grid.Point) [][2]int {
	out := make([][2]int, len(p))
	for i, q := range p {
		out[i] = [2]int{q.X, q.Y}
	}
	return out
}

// Page builds the HTML document. results may be empty; ex may be nil.
func Page(title string, g *grid.Grid, results []*plan.Result, ex *plan.Exploration) (string, error) {
	var sb strings.Builder
	for _, c := range g.Cost {
		sb.WriteByte('0' + c)
	}
	pj := pageJSON{Title: title, W: g.W, H: g.H, Cost: sb.String(),
		Start: [2]int{g.Start.X, g.Start.Y}, Goal: [2]int{g.Goal.X, g.Goal.Y}}
	for _, r := range results {
		a := algoJSON{Name: r.Algo, Found: r.Found, Cost: r.Cost, Expanded: r.Expanded,
			Generated: r.Generated, Micros: r.Dur.Microseconds(), Path: pts(r.Path), Order: r.Order}
		if a.Order == nil {
			a.Order = []int32{}
		}
		pj.Algos = append(pj.Algos, a)
	}
	if ex != nil {
		e := &exploreJSON{Radius: ex.Radius, Reached: ex.Reached, Stuck: ex.Stuck, Trail: pts(ex.Trail),
			Travelled: ex.Travelled, DStarTotal: ex.DStarTotal, AStarTotal: ex.AStarTotal}
		for _, ev := range ex.Events {
			ej := eventJSON{Step: ev.Step, Pos: [2]int{ev.Pos.X, ev.Pos.Y}, Changed: ev.Changed, DStar: ev.DStarExp,
				AStar: ev.AStarExp, Order: ev.Order, Plan: pts(ev.Plan), Found: pts(ev.Discovered)}
			if ej.Order == nil {
				ej.Order = []int32{}
			}
			if ev.PlanCost < 1e300 {
				c := ev.PlanCost
				ej.Cost = &c
			}
			e.Events = append(e.Events, ej)
		}
		pj.Explore = e
	}
	data, err := json.Marshal(pj)
	if err != nil {
		return "", fmt.Errorf("encode page data: %w", err)
	}
	safe := strings.ReplaceAll(string(data), "</", "<\\/") // keep JSON from closing the script tag
	out := strings.Replace(template, "/*__DATA__*/null", safe, 1)
	out = strings.ReplaceAll(out, "__TITLE__", htmlEscape(title))
	return out, nil
}

func htmlEscape(s string) string {
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;").Replace(s)
}
