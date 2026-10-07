// Package model holds an LP/MIP model with exact rational data.
package model

import (
	"fmt"
	"math/big"
	"sort"
	"strings"
)

// Var is a decision variable. Lo/Hi nil mean -inf / +inf.
type Var struct {
	Name   string
	Lo, Hi *big.Rat
	Int    bool
	Obj    *big.Rat
}

// Entry is one nonzero coefficient of a row.
type Entry struct {
	J int
	V *big.Rat
}

// Row is Lo <= sum Entry <= Hi (nil = infinite).
type Row struct {
	Name    string
	Entries []Entry
	Lo, Hi  *big.Rat
}

// Model is a linear program, possibly with integer variables.
type Model struct {
	Maximize bool
	ObjName  string
	ObjConst *big.Rat
	Vars     []Var
	Rows     []Row
	index    map[string]int
}

// New returns an empty model.
func New() *Model {
	return &Model{ObjConst: new(big.Rat), index: map[string]int{}}
}

// VarIndex returns the index of a named variable, or -1.
func (m *Model) VarIndex(name string) int {
	if i, ok := m.index[name]; ok {
		return i
	}
	return -1
}

// AddVar adds a variable with default bounds [0, +inf).
func (m *Model) AddVar(name string) int {
	if i, ok := m.index[name]; ok {
		return i
	}
	m.Vars = append(m.Vars, Var{Name: name, Lo: new(big.Rat), Obj: new(big.Rat)})
	m.index[name] = len(m.Vars) - 1
	return len(m.Vars) - 1
}

// NumVars / NumRows are convenience accessors.
func (m *Model) NumVars() int { return len(m.Vars) }
func (m *Model) NumRows() int { return len(m.Rows) }

// Clone makes a deep copy.
func (m *Model) Clone() *Model {
	c := New()
	c.Maximize, c.ObjName = m.Maximize, m.ObjName
	c.ObjConst = cp(m.ObjConst)
	for _, v := range m.Vars {
		c.Vars = append(c.Vars, Var{v.Name, cp(v.Lo), cp(v.Hi), v.Int, cp(v.Obj)})
		c.index[v.Name] = len(c.Vars) - 1
	}
	for _, r := range m.Rows {
		nr := Row{Name: r.Name, Lo: cp(r.Lo), Hi: cp(r.Hi)}
		for _, e := range r.Entries {
			nr.Entries = append(nr.Entries, Entry{e.J, cp(e.V)})
		}
		c.Rows = append(c.Rows, nr)
	}
	return c
}

func cp(r *big.Rat) *big.Rat {
	if r == nil {
		return nil
	}
	return new(big.Rat).Set(r)
}

// MinCost returns the objective vector in minimisation orientation.
func (m *Model) MinCost() []*big.Rat {
	c := make([]*big.Rat, len(m.Vars))
	for j, v := range m.Vars {
		if m.Maximize {
			c[j] = new(big.Rat).Neg(v.Obj)
		} else {
			c[j] = new(big.Rat).Set(v.Obj)
		}
	}
	return c
}

// ObjIsIntegral reports whether c.x is provably an integer for every
// integer-feasible x (all costed variables are integer with integer cost).
func (m *Model) ObjIsIntegral() bool {
	for _, v := range m.Vars {
		if v.Obj.Sign() == 0 {
			continue
		}
		if !v.Int || !v.Obj.IsInt() {
			return false
		}
	}
	return true
}

// HasInts reports whether any variable is integer.
func (m *Model) HasInts() bool {
	for _, v := range m.Vars {
		if v.Int {
			return true
		}
	}
	return false
}

// Validate checks structural sanity (bounds ordering, indices).
func (m *Model) Validate() error {
	for _, v := range m.Vars {
		if v.Lo != nil && v.Hi != nil && v.Lo.Cmp(v.Hi) > 0 {
			return fmt.Errorf("variable %s has lower bound %s > upper bound %s", v.Name, v.Lo.RatString(), v.Hi.RatString())
		}
	}
	for _, r := range m.Rows {
		if r.Lo != nil && r.Hi != nil && r.Lo.Cmp(r.Hi) > 0 {
			return fmt.Errorf("row %s has empty range [%s, %s]", r.Name, r.Lo.RatString(), r.Hi.RatString())
		}
		seen := map[int]bool{}
		for _, e := range r.Entries {
			if e.J < 0 || e.J >= len(m.Vars) {
				return fmt.Errorf("row %s references unknown variable %d", r.Name, e.J)
			}
			if seen[e.J] {
				return fmt.Errorf("row %s lists variable %s twice", r.Name, m.Vars[e.J].Name)
			}
			seen[e.J] = true
		}
	}
	return nil
}

// RatStr prints a rational compactly: integers plain, else p/q.
func RatStr(r *big.Rat) string {
	if r == nil {
		return "inf"
	}
	if r.IsInt() {
		return r.Num().String()
	}
	return r.RatString()
}

// Float converts a rational to float64.
func Float(r *big.Rat) float64 {
	f, _ := r.Float64()
	return f
}

// DecStr prints a rational as a decimal with up to 10 significant decimals.
func DecStr(r *big.Rat) string {
	if r.IsInt() {
		return r.Num().String()
	}
	s := r.FloatString(10)
	s = strings.TrimRight(s, "0")
	return strings.TrimRight(s, ".")
}

// SortedEntries returns row entries ordered by variable index.
func SortedEntries(es []Entry) []Entry {
	out := append([]Entry(nil), es...)
	sort.Slice(out, func(a, b int) bool { return out[a].J < out[b].J })
	return out
}
