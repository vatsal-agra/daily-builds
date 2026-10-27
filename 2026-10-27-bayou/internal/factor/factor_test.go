package factor

import (
	"math"
	"math/rand"
	"testing"
)

func randFactor(rng *rand.Rand, vars []int, card map[int]int) *Factor {
	cs := make([]int, len(vars))
	n := 1
	for i, v := range vars {
		cs[i] = card[v]
		n *= cs[i]
	}
	vals := make([]float64, n)
	for i := range vals {
		if rng.Float64() < 0.2 {
			continue // exact zeros
		}
		vals[i] = rng.Float64() * math.Pow(10, float64(rng.Intn(9)-4))
	}
	return New(vars, cs, vals)
}

// naive evaluation by explicit assignment maps
func allAssignments(vars []int, card map[int]int) []map[int]int {
	out := []map[int]int{{}}
	for _, v := range vars {
		var next []map[int]int
		for _, a := range out {
			for s := 0; s < card[v]; s++ {
				b := map[int]int{}
				for k, x := range a {
					b[k] = x
				}
				b[v] = s
				next = append(next, b)
			}
		}
		out = next
	}
	return out
}

func rel(a, b float64) bool {
	if a == b {
		return true
	}
	return math.Abs(a-b) <= 1e-12*math.Max(math.Abs(a), math.Abs(b))
}

func TestProductSumMaxReduceAgainstNaive(t *testing.T) {
	rng := rand.New(rand.NewSource(5))
	card := map[int]int{0: 2, 1: 3, 2: 2, 3: 4, 4: 3}
	pick := func() []int {
		var vs []int
		for v := 0; v < 5; v++ {
			if rng.Float64() < 0.55 {
				vs = append(vs, v)
			}
		}
		return vs
	}
	for trial := 0; trial < 300; trial++ {
		a, b := randFactor(rng, pick(), card), randFactor(rng, pick(), card)
		p := Product(a, b)
		for _, asg := range allAssignments(p.Vars, card) {
			if want, got := a.At(asg)*b.At(asg), p.At(asg); !rel(want, got) {
				t.Fatalf("product mismatch %g vs %g", want, got)
			}
		}
		if len(p.Vars) == 0 {
			continue
		}
		v := p.Vars[rng.Intn(len(p.Vars))]
		rest := []int{}
		for _, u := range p.Vars {
			if u != v {
				rest = append(rest, u)
			}
		}
		sum := p.SumOut(v)
		arg := map[int]*Factor{}
		mx := p.MaxOut(arg, v)
		for _, asg := range allAssignments(rest, card) {
			s, best := 0.0, 0.0
			bs := -1
			for x := 0; x < card[v]; x++ {
				asg[v] = x
				val := p.At(asg)
				s += val
				if val > best {
					best, bs = val, x
				}
			}
			delete(asg, v)
			if !rel(s, sum.At(asg)) {
				t.Fatalf("sum mismatch %g vs %g", s, sum.At(asg))
			}
			if !rel(best, mx.At(asg)) {
				t.Fatalf("max mismatch %g vs %g", best, mx.At(asg))
			}
			if best > 0 {
				// argmax table must point at a maximiser
				idx, stride := 0, 1
				am := arg[v]
				for k := len(am.Vars) - 1; k >= 0; k-- {
					idx += asg[am.Vars[k]] * stride
					stride *= am.Card[k]
				}
				asg[v] = int(am.Val[idx])
				if !rel(p.At(asg), best) {
					t.Fatalf("argmax points at non-maximiser (state %d, bs %d)", int(am.Val[idx]), bs)
				}
				delete(asg, v)
			}
			// reduce
			asg[v] = rng.Intn(card[v])
			r := p.Reduce(v, asg[v])
			if !rel(r.At(asg), p.At(asg)) {
				t.Fatalf("reduce mismatch")
			}
			delete(asg, v)
		}
	}
}

func TestScaleSurvivesUnderflow(t *testing.T) {
	f := Scalar(1)
	for i := 0; i < 5000; i++ { // product of 5000 tiny numbers: 1e-4000 underflows float64
		f = Product(f, Scalar(1e-4))
	}
	if f.Impossible() {
		t.Fatal("underflow turned a positive factor into 'impossible'")
	}
	if got, want := f.LogTotal(), 5000*math.Log(1e-4); math.Abs(got-want) > 1e-6 {
		t.Fatalf("log total %g want %g", got, want)
	}
}

func TestZeroFactorsAreImpossibleAndAbsorbing(t *testing.T) {
	z := Scalar(0)
	if !z.Impossible() || !math.IsInf(z.LogTotal(), -1) {
		t.Fatal("zero scalar must be impossible")
	}
	f := New([]int{0}, []int{2}, []float64{0.3, 0.7})
	if p := Product(f, z); !p.Impossible() {
		t.Fatal("product with an impossible factor must be impossible")
	}
	if _, ok := z.Normalized(); ok {
		t.Fatal("cannot normalise an impossible factor")
	}
	// reducing onto an all-zero slice
	g := New([]int{0, 1}, []int{2, 2}, []float64{0, 0, 0.5, 0.5})
	if r := g.Reduce(0, 0); !r.Impossible() {
		t.Fatal("reduce onto zeros must be impossible")
	}
}

func TestNewSortsVariables(t *testing.T) {
	// values are given in sorted-variable order regardless of argument order
	f := New([]int{5, 2}, []int{3, 2}, []float64{1, 2, 3, 4, 5, 6})
	if f.Vars[0] != 2 || f.Vars[1] != 5 || f.Card[0] != 2 || f.Card[1] != 3 {
		t.Fatalf("not sorted: %v %v", f.Vars, f.Card)
	}
}

func TestTooLargeIsATypedPanic(t *testing.T) {
	defer func() {
		r := recover()
		if _, ok := r.(*TooLargeError); !ok {
			t.Fatalf("expected *TooLargeError, got %v", r)
		}
	}()
	vars := make([]int, 40)
	card := make([]int, 40)
	for i := range vars {
		vars[i], card[i] = i, 2
	}
	New(vars, card, nil)
}

func TestEntropyAndMarginal(t *testing.T) {
	f := New([]int{0, 1}, []int{2, 2}, []float64{0.25, 0.25, 0.25, 0.25})
	if h := f.Entropy(); math.Abs(h-math.Log(4)) > 1e-12 {
		t.Fatalf("entropy %g", h)
	}
	m := f.Marginal(1)
	if len(m.Vars) != 1 || m.Vars[0] != 1 {
		t.Fatalf("marginal scope %v", m.Vars)
	}
}
