package aig

import (
	"fmt"
	"sort"
)

// PathStep is one gate (or terminal) on a timing path.
type PathStep struct {
	Level int
	Node  uint32
	Neg   bool   // edge into the next step is complemented
	Label string // best human-readable name for the net, if any
}

// Path is a longest (unit-delay) combinational path.
type Path struct {
	Endpoint string // output bit or register input the path ends at
	Depth    int
	Steps    []PathStep // from the launching input/register to the endpoint
}

// Labels maps node ids to a readable net name (inputs, registers, named signals).
func (g *AIG) Labels() map[uint32]string {
	lab := map[uint32]string{}
	for _, pi := range g.PIs {
		if p := g.FindInput(pi.Port); p != nil && len(p.Bits) > 1 {
			lab[pi.Node] = fmt.Sprintf("%s[%d]", pi.Port, pi.Bit)
		} else {
			lab[pi.Node] = pi.Port
		}
	}
	for _, l := range g.Latches {
		lab[l.Q] = l.Name
	}
	// named internal nets, shortest hierarchical name wins
	names := append([]string(nil), g.NameOrder...)
	sort.SliceStable(names, func(i, j int) bool { return len(names[i]) < len(names[j]) })
	for _, n := range names {
		bits := g.Names[n]
		for i, b := range bits {
			if b == Undef || b.ID() == 0 || b.Neg() {
				continue
			}
			if _, ok := lab[b.ID()]; ok {
				continue
			}
			if len(bits) > 1 {
				lab[b.ID()] = fmt.Sprintf("%s[%d]", n, i)
			} else {
				lab[b.ID()] = n
			}
		}
	}
	return lab
}

// CriticalPath returns the deepest path to any output bit, register input or property.
func (g *AIG) CriticalPath() Path {
	lv := g.Levels()
	live := g.LiveLatches()
	type ep struct {
		name string
		lit  Lit
	}
	var eps []ep
	for _, p := range g.Outputs {
		for i, b := range p.Bits {
			nm := p.Name
			if len(p.Bits) > 1 {
				nm = fmt.Sprintf("%s[%d]", p.Name, i)
			}
			eps = append(eps, ep{"output " + nm, b})
		}
	}
	for i, l := range g.Latches {
		if live[i] {
			eps = append(eps, ep{"register " + l.Name + " (D)", l.D})
		}
	}
	for _, p := range g.Asserts {
		eps = append(eps, ep{"assert " + p.Name, p.Lit})
	}
	best := -1
	var bestEp ep
	for _, e := range eps {
		if e.lit == Undef {
			continue
		}
		if d := lv[e.lit.ID()]; d > best {
			best, bestEp = d, e
		}
	}
	if best < 0 {
		return Path{}
	}
	lab := g.Labels()
	var rev []PathStep
	cur := bestEp.lit
	for {
		id := cur.ID()
		rev = append(rev, PathStep{Level: lv[id], Node: id, Neg: cur.Neg(), Label: lab[id]})
		n := g.Nodes[id]
		if n.Kind != KAnd {
			break
		}
		if lv[n.A.ID()] >= lv[n.B.ID()] {
			cur = n.A
		} else {
			cur = n.B
		}
	}
	steps := make([]PathStep, len(rev))
	for i, s := range rev {
		steps[len(rev)-1-i] = s
	}
	return Path{Endpoint: bestEp.name, Depth: best, Steps: steps}
}
