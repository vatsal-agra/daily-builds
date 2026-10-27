// Package factor implements discrete factor algebra: the arithmetic every
// exact inference algorithm in Bayou is built from.
//
// A Factor is a non-negative table over a set of variables. To stay safe from
// underflow on long chains and large networks every factor carries a separate
// log-scale: the real value of entry i is Val[i]*exp(LogScale). Operations
// renormalise Val so that its maximum is 1 and push the magnitude into LogScale.
// A factor whose every entry is zero has LogScale = -Inf (an impossible event).
package factor

import (
	"fmt"
	"math"
	"sort"
)

// Factor is a table over Vars (strictly ascending variable ids).
// Val is laid out with Vars[0] slowest and the last variable fastest.
type Factor struct {
	Vars     []int
	Card     []int
	Val      []float64
	LogScale float64
}

// New builds a factor over the given variables (any order; they are sorted).
// vals must be indexed in the *sorted* variable order. A nil vals gives all ones.
func New(vars, card []int, vals []float64) *Factor {
	type vc struct{ v, c int }
	ps := make([]vc, len(vars))
	for i := range vars {
		ps[i] = vc{vars[i], card[i]}
	}
	sort.Slice(ps, func(i, j int) bool { return ps[i].v < ps[j].v })
	f := &Factor{Vars: make([]int, len(ps)), Card: make([]int, len(ps))}
	n := 1
	for i, p := range ps {
		if i > 0 && ps[i-1].v == p.v {
			panic(fmt.Sprintf("factor.New: duplicate variable %d", p.v))
		}
		f.Vars[i], f.Card[i] = p.v, p.c
		n *= p.c
	}
	f.Val = make([]float64, n)
	if vals == nil {
		for i := range f.Val {
			f.Val[i] = 1
		}
	} else {
		if len(vals) != n {
			panic(fmt.Sprintf("factor.New: %d values for table of size %d", len(vals), n))
		}
		copy(f.Val, vals)
	}
	f.rescale()
	return f
}

// Scalar returns a factor over no variables with the given real value.
func Scalar(x float64) *Factor {
	f := &Factor{Val: []float64{x}}
	f.rescale()
	return f
}

// Size is the number of table entries.
func (f *Factor) Size() int { return len(f.Val) }

func (f *Factor) strides() []int {
	s := make([]int, len(f.Vars))
	acc := 1
	for i := len(f.Vars) - 1; i >= 0; i-- {
		s[i] = acc
		acc *= f.Card[i]
	}
	return s
}

// rescale makes max(Val)=1 (moving magnitude into LogScale) or marks the
// factor impossible if everything is zero.
func (f *Factor) rescale() {
	mx := 0.0
	for _, x := range f.Val {
		if x > mx {
			mx = x
		}
	}
	if mx == 0 {
		f.LogScale = math.Inf(-1)
		return
	}
	if math.IsInf(f.LogScale, -1) { // was impossible, now has mass (e.g. constructed anew)
		f.LogScale = 0
	}
	if mx != 1 {
		inv := 1 / mx
		for i := range f.Val {
			f.Val[i] *= inv
		}
		f.LogScale += math.Log(mx)
	}
}

// Impossible reports whether the factor is identically zero.
func (f *Factor) Impossible() bool { return math.IsInf(f.LogScale, -1) }

// Clone deep-copies the factor.
func (f *Factor) Clone() *Factor {
	g := &Factor{Vars: append([]int(nil), f.Vars...), Card: append([]int(nil), f.Card...),
		Val: append([]float64(nil), f.Val...), LogScale: f.LogScale}
	return g
}

// Has reports whether v is in the scope.
func (f *Factor) Has(v int) bool { return f.pos(v) >= 0 }

func (f *Factor) pos(v int) int {
	i := sort.SearchInts(f.Vars, v)
	if i < len(f.Vars) && f.Vars[i] == v {
		return i
	}
	return -1
}

// At returns the real (unscaled) value at the assignment given by a map var->state.
func (f *Factor) At(assign map[int]int) float64 {
	idx := 0
	st := f.strides()
	for i, v := range f.Vars {
		idx += assign[v] * st[i]
	}
	if f.Impossible() {
		return 0
	}
	return f.Val[idx] * math.Exp(f.LogScale)
}

// walk calls fn(idxInResult, idxInA, idxInB) for every assignment of the union scope.
func walkUnion(vars, card []int, a, b *Factor, fn func(r, ia, ib int)) {
	n := len(vars)
	sa := make([]int, n)
	sb := make([]int, n)
	ast, bst := a.strides(), b.strides()
	for i, v := range vars {
		if p := a.pos(v); p >= 0 {
			sa[i] = ast[p]
		}
		if p := b.pos(v); p >= 0 {
			sb[i] = bst[p]
		}
	}
	total := 1
	for _, c := range card {
		total *= c
	}
	cnt := make([]int, n)
	ia, ib := 0, 0
	for r := 0; r < total; r++ {
		fn(r, ia, ib)
		for k := n - 1; k >= 0; k-- {
			cnt[k]++
			ia += sa[k]
			ib += sb[k]
			if cnt[k] < card[k] {
				break
			}
			ia -= sa[k] * card[k]
			ib -= sb[k] * card[k]
			cnt[k] = 0
		}
	}
}

func unionScope(a, b *Factor) (vars, card []int) {
	i, j := 0, 0
	for i < len(a.Vars) || j < len(b.Vars) {
		switch {
		case j >= len(b.Vars) || (i < len(a.Vars) && a.Vars[i] < b.Vars[j]):
			vars, card = append(vars, a.Vars[i]), append(card, a.Card[i])
			i++
		case i >= len(a.Vars) || b.Vars[j] < a.Vars[i]:
			vars, card = append(vars, b.Vars[j]), append(card, b.Card[j])
			j++
		default:
			if a.Card[i] != b.Card[j] {
				panic(fmt.Sprintf("factor: variable %d has cardinality %d and %d", a.Vars[i], a.Card[i], b.Card[j]))
			}
			vars, card = append(vars, a.Vars[i]), append(card, a.Card[i])
			i++
			j++
		}
	}
	return
}

func combine(a, b *Factor, op func(x, y float64) float64) *Factor {
	vars, card := unionScope(a, b)
	out := &Factor{Vars: vars, Card: card}
	n := 1
	for _, c := range card {
		n *= c
	}
	out.Val = make([]float64, n)
	walkUnion(vars, card, a, b, func(r, ia, ib int) { out.Val[r] = op(a.Val[ia], b.Val[ib]) })
	out.LogScale = a.LogScale + b.LogScale
	if a.Impossible() || b.Impossible() {
		out.LogScale = math.Inf(-1)
		for i := range out.Val {
			out.Val[i] = 0
		}
		return out
	}
	out.rescale()
	return out
}

// Product returns a*b.
func Product(a, b *Factor) *Factor {
	return combine(a, b, func(x, y float64) float64 { return x * y })
}

// ProductAll multiplies a list of factors (the empty product is the scalar 1).
func ProductAll(fs []*Factor) *Factor {
	if len(fs) == 0 {
		return Scalar(1)
	}
	acc := fs[0]
	for _, f := range fs[1:] {
		acc = Product(acc, f)
	}
	if len(fs) == 1 {
		return fs[0].Clone()
	}
	return acc
}

// SumOut sums the listed variables away.
func (f *Factor) SumOut(vs ...int) *Factor { return f.eliminate(false, nil, vs) }

// MaxOut maximises the listed variables away. If arg is non-nil, for each
// eliminated variable v it receives a factor-shaped argmax table: arg[v] is a
// Factor over the remaining scope whose Val holds the maximising state of v.
func (f *Factor) MaxOut(arg map[int]*Factor, vs ...int) *Factor { return f.eliminate(true, arg, vs) }

func (f *Factor) eliminate(isMax bool, arg map[int]*Factor, vs []int) *Factor {
	drop := map[int]bool{}
	for _, v := range vs {
		if f.pos(v) >= 0 {
			drop[v] = true
		}
	}
	if len(drop) == 0 {
		return f.Clone()
	}
	// Eliminate one variable at a time so argmax tables are per-variable.
	cur := f
	for _, v := range sortedKeys(drop) {
		cur = cur.eliminateOne(v, isMax, arg)
	}
	return cur
}

func sortedKeys(m map[int]bool) []int {
	ks := make([]int, 0, len(m))
	for k := range m {
		ks = append(ks, k)
	}
	sort.Ints(ks)
	return ks
}

func (f *Factor) eliminateOne(v int, isMax bool, arg map[int]*Factor) *Factor {
	p := f.pos(v)
	out := &Factor{LogScale: f.LogScale}
	out.Vars = append(append([]int(nil), f.Vars[:p]...), f.Vars[p+1:]...)
	out.Card = append(append([]int(nil), f.Card[:p]...), f.Card[p+1:]...)
	n := 1
	for _, c := range out.Card {
		n *= c
	}
	out.Val = make([]float64, n)
	var am *Factor
	if arg != nil && isMax {
		am = &Factor{Vars: append([]int(nil), out.Vars...), Card: append([]int(nil), out.Card...), Val: make([]float64, n)}
	}
	// inner = product of cards after p; outer = product before p.
	inner := 1
	for _, c := range f.Card[p+1:] {
		inner *= c
	}
	cv := f.Card[p]
	outer := 1
	for _, c := range f.Card[:p] {
		outer *= c
	}
	for o := 0; o < outer; o++ {
		for in := 0; in < inner; in++ {
			best, bs := 0.0, 0
			sum := 0.0
			for s := 0; s < cv; s++ {
				x := f.Val[(o*cv+s)*inner+in]
				sum += x
				if x > best {
					best, bs = x, s
				}
			}
			ri := o*inner + in
			if isMax {
				out.Val[ri] = best
				if am != nil {
					am.Val[ri] = float64(bs)
				}
			} else {
				out.Val[ri] = sum
			}
		}
	}
	if f.Impossible() {
		out.LogScale = math.Inf(-1)
	} else {
		out.rescale()
	}
	if am != nil {
		arg[v] = am
	}
	return out
}

// Reduce conditions the factor on v=state (the variable leaves the scope).
func (f *Factor) Reduce(v, state int) *Factor {
	p := f.pos(v)
	if p < 0 {
		return f.Clone()
	}
	if state < 0 || state >= f.Card[p] {
		panic(fmt.Sprintf("factor.Reduce: state %d out of range for variable %d", state, v))
	}
	out := &Factor{LogScale: f.LogScale}
	out.Vars = append(append([]int(nil), f.Vars[:p]...), f.Vars[p+1:]...)
	out.Card = append(append([]int(nil), f.Card[:p]...), f.Card[p+1:]...)
	inner := 1
	for _, c := range f.Card[p+1:] {
		inner *= c
	}
	cv := f.Card[p]
	outer := 1
	for _, c := range f.Card[:p] {
		outer *= c
	}
	out.Val = make([]float64, outer*inner)
	for o := 0; o < outer; o++ {
		copy(out.Val[o*inner:(o+1)*inner], f.Val[(o*cv+state)*inner:(o*cv+state)*inner+inner])
	}
	if f.Impossible() {
		return out
	}
	out.rescale()
	return out
}

// Total returns log of the sum of all (real) entries.
func (f *Factor) LogTotal() float64 {
	if f.Impossible() {
		return math.Inf(-1)
	}
	s := 0.0
	for _, x := range f.Val {
		s += x
	}
	if s == 0 {
		return math.Inf(-1)
	}
	return math.Log(s) + f.LogScale
}

// Normalized returns a copy whose entries sum to 1 (real values). The second
// result is false if the factor is impossible (cannot be normalised).
func (f *Factor) Normalized() (*Factor, bool) {
	if f.Impossible() {
		return f.Clone(), false
	}
	s := 0.0
	for _, x := range f.Val {
		s += x
	}
	g := f.Clone()
	for i := range g.Val {
		g.Val[i] /= s
	}
	g.LogScale = 0
	return g, true
}

// Probs returns the real values (LogScale applied). Intended for normalised factors.
func (f *Factor) Probs() []float64 {
	out := make([]float64, len(f.Val))
	if f.Impossible() {
		return out
	}
	sc := math.Exp(f.LogScale)
	for i, x := range f.Val {
		out[i] = x * sc
	}
	return out
}

// Marginal sums out everything except keep.
func (f *Factor) Marginal(keep ...int) *Factor {
	k := map[int]bool{}
	for _, v := range keep {
		k[v] = true
	}
	var drop []int
	for _, v := range f.Vars {
		if !k[v] {
			drop = append(drop, v)
		}
	}
	return f.SumOut(drop...)
}

// Entropy of a normalised factor in nats.
func (f *Factor) Entropy() float64 {
	h := 0.0
	for _, p := range f.Probs() {
		if p > 0 {
			h -= p * math.Log(p)
		}
	}
	return h
}
