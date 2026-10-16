// Package report renders a self-contained HTML explorer of a compilation: the CFG of every function
// after every optimisation pass, with dominator tree, loop nesting and per-pass IR diffs.
package report

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"html"
	"sort"
	"strings"

	"dominion/backend"
	"dominion/front"
	"dominion/ir"
	"dominion/opt"
)

//go:embed template.html
var template string

type node struct {
	Name   string   `json:"name"`
	Lines  []string `json:"lines"`
	X      float64  `json:"x"`
	Y      float64  `json:"y"`
	W      float64  `json:"w"`
	H      float64  `json:"h"`
	Idom   string   `json:"idom"`
	Depth  int      `json:"depth"`
	Header bool     `json:"header"`
}

type edge struct {
	From string `json:"from"`
	To   string `json:"to"`
	Back bool   `json:"back"`
	Kind string `json:"kind"` // "", "t", "f"
}

type fnView struct {
	Name   string  `json:"name"`
	Nodes  []node  `json:"nodes"`
	Edges  []edge  `json:"edges"`
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
	Text   string  `json:"text"`
	Instrs int     `json:"instrs"`
}

type stage struct {
	Label   string   `json:"label"`
	Changes int      `json:"changes"`
	Funcs   []fnView `json:"funcs"`
}

type bench struct {
	Level  int   `json:"level"`
	Cycles int64 `json:"cycles"`
	Instrs int64 `json:"instrs"`
	Ok     bool  `json:"ok"`
}

type payload struct {
	Title  string  `json:"title"`
	Source string  `json:"source"`
	Level  int     `json:"level"`
	Stages []stage `json:"stages"`
	Bench  []bench `json:"bench"`
	Result string  `json:"result"`
	Asm    string  `json:"asm"`
}

const (
	charW  = 7.3
	lineH  = 15.0
	padX   = 12.0
	padY   = 10.0
	titleH = 22.0
	gapX   = 36.0
	gapY   = 46.0
)

func snapshotFunc(f *ir.Func) fnView {
	dom := ir.ComputeDom(f)
	loops := opt.FindLoops(f, dom)
	depth := map[*ir.Block]int{}
	headers := map[*ir.Block]bool{}
	for _, l := range loops {
		headers[l.Header] = true
		for b := range l.Blocks {
			depth[b]++
		}
	}
	text := f.String()
	fv := fnView{Name: f.Name, Text: text}
	// layering over forward edges
	rpo := dom.RPO
	idx := map[*ir.Block]int{}
	for i, b := range rpo {
		idx[b] = i
	}
	isBack := func(from, to *ir.Block) bool { return dom.Dominates(to, from) }
	layer := map[*ir.Block]int{}
	for _, b := range rpo {
		for _, p := range b.Preds {
			if _, ok := idx[p]; ok && !isBack(p, b) && layer[p]+1 > layer[b] {
				layer[b] = layer[p] + 1
			}
		}
	}
	nl := 0
	for _, b := range rpo {
		if layer[b] > nl {
			nl = layer[b]
		}
	}
	rows := make([][]*ir.Block, nl+1)
	for _, b := range rpo {
		rows[layer[b]] = append(rows[layer[b]], b)
	}
	// barycentre ordering, two sweeps
	pos := map[*ir.Block]float64{}
	for r := range rows {
		for i, b := range rows[r] {
			pos[b] = float64(i)
		}
	}
	for sweep := 0; sweep < 3; sweep++ {
		for r := 1; r <= nl; r++ {
			bc := map[*ir.Block]float64{}
			for _, b := range rows[r] {
				s, n := 0.0, 0
				for _, p := range b.Preds {
					if _, ok := idx[p]; ok && !isBack(p, b) {
						s += pos[p]
						n++
					}
				}
				bc[b] = pos[b]
				if n > 0 {
					bc[b] = s / float64(n)
				}
			}
			sort.SliceStable(rows[r], func(i, j int) bool { return bc[rows[r][i]] < bc[rows[r][j]] })
			for i, b := range rows[r] {
				pos[b] = float64(i)
			}
		}
	}
	// geometry
	n := map[*ir.Block]*node{}
	var all []*node
	bl := blockLines(f)
	for _, b := range rpo {
		lines := bl[b.Name]
		w := 0
		for _, l := range lines {
			if len(l) > w {
				w = len(l)
			}
		}
		if len(b.Name)+2 > w {
			w = len(b.Name) + 2
		}
		idom := ""
		if d := dom.Idom[b]; d != nil {
			idom = d.Name
		}
		nd := &node{Name: b.Name, Lines: lines, W: float64(w)*charW + 2*padX, H: titleH + float64(len(lines))*lineH + padY,
			Idom: idom, Depth: depth[b], Header: headers[b]}
		n[b] = nd
		all = append(all, nd)
	}
	rowW := make([]float64, nl+1)
	rowH := make([]float64, nl+1)
	maxW := 0.0
	for r := range rows {
		for _, b := range rows[r] {
			rowW[r] += n[b].W + gapX
			if n[b].H > rowH[r] {
				rowH[r] = n[b].H
			}
		}
		rowW[r] -= gapX
		if rowW[r] > maxW {
			maxW = rowW[r]
		}
	}
	y := 20.0
	for r := range rows {
		x := 20 + (maxW-rowW[r])/2
		for _, b := range rows[r] {
			n[b].X, n[b].Y = x, y
			x += n[b].W + gapX
		}
		y += rowH[r] + gapY
	}
	fv.Width, fv.Height = maxW+40+60, y
	for _, nd := range all {
		fv.Nodes = append(fv.Nodes, *nd)
	}
	for _, b := range rpo {
		for i, s := range b.Succs {
			e := edge{From: b.Name, To: s.Name, Back: isBack(b, s)}
			if b.Term == ir.TermCondBr {
				e.Kind = []string{"t", "f"}[i]
			}
			fv.Edges = append(fv.Edges, e)
		}
	}
	for _, b := range f.Blocks {
		fv.Instrs += len(b.Phis) + len(b.Instrs) + 1
	}
	return fv
}

// blockLines splits a function's printed form into per-block instruction lines.
func blockLines(f *ir.Func) map[string][]string {
	out := map[string][]string{}
	cur := ""
	for _, l := range strings.Split(f.String(), "\n") {
		switch {
		case strings.HasPrefix(l, "  "):
			if cur != "" {
				out[cur] = append(out[cur], strings.TrimPrefix(l, "  "))
			}
		case strings.HasSuffix(l, ":") && !strings.Contains(l, " "):
			cur = strings.TrimSuffix(l, ":")
			out[cur] = nil
		default:
			cur = ""
		}
	}
	return out
}

func snapshot(m *ir.Module, label string, changes int) stage {
	st := stage{Label: label, Changes: changes}
	for _, f := range m.Funcs {
		st.Funcs = append(st.Funcs, snapshotFunc(f))
	}
	return st
}

// Build compiles src at the given level and returns the HTML report.
func Build(title, src string, level int, regs int) (string, error) {
	m, err := front.Compile(src)
	if err != nil {
		return "", err
	}
	p := payload{Title: title, Source: src, Level: level}
	p.Stages = append(p.Stages, snapshot(m, "source → IR (-O0)", 0))
	last := stageKey(p.Stages[0])
	_, err = opt.Run(m, opt.Level(level), opt.Options{Verify: true, Hook: func(pass string, mm *ir.Module, n int) {
		s := snapshot(mm, pass, n)
		if k := stageKey(s); k != last {
			p.Stages = append(p.Stages, s)
			last = k
		}
	}})
	if err != nil {
		return "", err
	}
	// benchmark every level and make sure they all agree with the interpreter
	base, _ := front.Compile(src)
	want := base.Run(500_000_000)
	for l := 0; l <= 3; l++ {
		mm, _ := front.Compile(src)
		if _, err := opt.Optimize(mm, l, true); err != nil {
			return "", err
		}
		o, err := backend.Compile(mm, backend.Config{NumRegs: regs})
		if err != nil {
			return "", err
		}
		r, st := o.Prog.Run(500_000_000)
		p.Bench = append(p.Bench, bench{Level: l, Cycles: st.Cycles, Instrs: st.Instrs, Ok: r.Same(want)})
		if l == level {
			p.Asm = o.Prog.Disasm()
		}
	}
	p.Result = want.String()
	js, err := json.Marshal(p)
	if err != nil {
		return "", err
	}
	// "</" inside a script block would terminate it early
	safe := strings.ReplaceAll(string(js), "</", "<\\/")
	out := strings.Replace(template, "/*DATA*/null", safe, 1)
	out = strings.Replace(out, "%TITLE%", html.EscapeString(title), 1)
	return out, nil
}

func stageKey(s stage) string {
	var sb strings.Builder
	for _, f := range s.Funcs {
		sb.WriteString(f.Text)
	}
	return fmt.Sprint(len(sb.String())) + sb.String()
}
