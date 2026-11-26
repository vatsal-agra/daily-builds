package main

import (
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
)

// The 169 starting-hand classes sit in a 13x13 grid: pairs on the diagonal, suited above it,
// offsuit below it. Cell (r,c) has high rank 12-r on the row and 12-c on the column.
const nClass = 169

func classRanks(id int) (hi, lo int, suited bool) {
	a, b := 12-id/13, 12-id%13
	switch {
	case a == b:
		return a, a, false
	case a > b: // row rank higher => column further right => suited (upper triangle)
		return a, b, true
	}
	return b, a, false
}

// ClassName renders e.g. "AKs", "77", "T9o".
func ClassName(id int) string {
	hi, lo, su := classRanks(id)
	n := string(rankChars[hi]) + string(rankChars[lo])
	switch {
	case hi == lo:
		return n
	case su:
		return n + "s"
	}
	return n + "o"
}

// ClassID finds the class of a hand name such as "AKs", "72o", "TT".
func ClassID(name string) (int, error) {
	c, err := parseClass(name)
	if err != nil {
		return 0, fmt.Errorf("bad hand class %q", name)
	}
	if c.hi != c.lo && c.suited == c.offsuit {
		return 0, fmt.Errorf("hand class %q needs an s or o suffix", name)
	}
	r := 12 - c.hi
	col := 12 - c.lo
	if c.hi == c.lo {
		return r*13 + col, nil
	}
	if c.suited {
		return r*13 + col, nil
	}
	return (12-c.lo)*13 + (12 - c.hi), nil
}

func classComboList(id int) []Combo {
	hi, lo, su := classRanks(id)
	return classCombos(hi, lo, su, !su)
}

// EqMatrix holds preflop all-in equity for every class vs class matchup and the exact
// number of non-conflicting combo pairs for each matchup (card removal included).
type EqMatrix struct {
	Eq      [nClass][nClass]float64
	W       [nClass][nClass]float64
	Samples int
}

func computeWeights(m *EqMatrix) {
	var combos [nClass][]Combo
	for i := range combos {
		combos[i] = classComboList(i)
	}
	for i := 0; i < nClass; i++ {
		for j := 0; j < nClass; j++ {
			n := 0
			for _, a := range combos[i] {
				for _, b := range combos[j] {
					if a.mask()&b.mask() == 0 {
						n++
					}
				}
			}
			m.W[i][j] = float64(n)
		}
	}
}

func cachePath(samples int, seed int64) string {
	d, err := os.UserCacheDir()
	if err != nil {
		return ""
	}
	return filepath.Join(d, "bluff", fmt.Sprintf("eq-v1-%d-%d.bin", samples, seed))
}

// BuildEqMatrix estimates class-vs-class equities with Monte Carlo: for each unordered matchup
// it samples `samples` random non-conflicting deals. Work is parallel but seeded per matchup,
// so the result does not depend on the number of CPUs. Results are cached on disk.
func BuildEqMatrix(samples int, seed int64, progress io.Writer) (*EqMatrix, error) {
	if samples < 10 {
		return nil, fmt.Errorf("need at least 10 samples per matchup")
	}
	m := &EqMatrix{Samples: samples}
	computeWeights(m)
	cp := cachePath(samples, seed)
	if cp != "" {
		if f, err := os.Open(cp); err == nil {
			var flat [nClass * nClass]float32
			err = binary.Read(f, binary.LittleEndian, &flat)
			f.Close()
			if err == nil {
				for i := 0; i < nClass; i++ {
					for j := 0; j < nClass; j++ {
						m.Eq[i][j] = float64(flat[i*nClass+j])
					}
				}
				return m, nil
			}
		}
	}
	if progress != nil {
		fmt.Fprintf(progress, "building 169x169 equity matrix (%d samples/matchup)…\n", samples)
	}
	var combos [nClass][]Combo
	for i := range combos {
		combos[i] = classComboList(i)
	}
	type job struct{ i, j int }
	jobs := make(chan job, 256)
	var wg sync.WaitGroup
	for w := 0; w < runtime.NumCPU(); w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			cards := make([]int, 0, 7)
			rest := make([]int, 0, 52)
			for jb := range jobs {
				rng := rand.New(rand.NewSource(seed*7919 + int64(jb.i*nClass+jb.j)))
				ci, cj := combos[jb.i], combos[jb.j]
				var sum float64
				n := 0
				for n < samples {
					a, b := ci[rng.Intn(len(ci))], cj[rng.Intn(len(cj))]
					if a.mask()&b.mask() != 0 {
						continue
					}
					used := a.mask() | b.mask()
					rest = rest[:0]
					for c := 0; c < 52; c++ {
						if used>>uint(c)&1 == 0 {
							rest = append(rest, c)
						}
					}
					for k := 0; k < 5; k++ {
						j := k + rng.Intn(len(rest)-k)
						rest[k], rest[j] = rest[j], rest[k]
					}
					cards = append(cards[:0], rest[:5]...)
					cards = append(cards, a.A, a.B)
					sa := Eval(cards)
					cards = append(cards[:5], b.A, b.B)
					sb := Eval(cards)
					switch {
					case sa > sb:
						sum++
					case sa == sb:
						sum += 0.5
					}
					n++
				}
				e := sum / float64(samples)
				m.Eq[jb.i][jb.j] = e
				m.Eq[jb.j][jb.i] = 1 - e
			}
		}()
	}
	for i := 0; i < nClass; i++ {
		m.Eq[i][i] = 0.5
		for j := i + 1; j < nClass; j++ {
			jobs <- job{i, j}
		}
	}
	close(jobs)
	wg.Wait()
	if cp != "" {
		var flat [nClass * nClass]float32
		for i := 0; i < nClass; i++ {
			for j := 0; j < nClass; j++ {
				flat[i*nClass+j] = float32(m.Eq[i][j])
			}
		}
		if os.MkdirAll(filepath.Dir(cp), 0o755) == nil {
			if f, err := os.Create(cp); err == nil {
				binary.Write(f, binary.LittleEndian, &flat)
				f.Close()
			}
		}
	}
	return m, nil
}

// PushFold is a heads-up shove/fold Nash equilibrium for one effective stack.
type PushFold struct {
	Stack    float64
	Shove    [nClass]float64 // small blind: probability of shoving each class
	Call     [nClass]float64 // big blind: probability of calling a shove with each class
	SBValue  float64         // small blind's expected result per hand, in bb
	Gap      float64         // exploitability (bb/hand); 0 is exact Nash
	Iters    int
	ShovePct float64 // % of all starting hands the SB shoves
	CallPct  float64 // % of hands the BB calls with (given a shove)
}

func payoffSB(m *EqMatrix, stack float64, i, j int) float64 { return stack * (2*m.Eq[i][j] - 1) }

// sbValue is the SB's expected result when SB shoves with shove[] and BB calls with call[].
func sbValue(m *EqMatrix, stack float64, shove, call *[nClass]float64) float64 {
	var tot, wsum float64
	for i := 0; i < nClass; i++ {
		for j := 0; j < nClass; j++ {
			w := m.W[i][j]
			wsum += w
			v := -0.5
			if shove[i] > 0 {
				push := (1-call[j])*1 + call[j]*payoffSB(m, stack, i, j)
				v = shove[i]*push + (1-shove[i])*-0.5
			}
			tot += w * v
		}
	}
	return tot / wsum
}

// SolvePushFold runs regret matching (CFR+) on the two-player shove/call game.
func SolvePushFold(m *EqMatrix, stack float64, iters int) (*PushFold, error) {
	if stack < 1 || stack > 1000 || stack != stack {
		return nil, fmt.Errorf("stack must be between 1 and 1000 big blinds")
	}
	if iters < 1 {
		return nil, fmt.Errorf("iters must be ≥ 1")
	}
	var rSB, rBB [nClass][2]float64 // [shove|call, fold]
	var sumSB, sumBB [nClass][2]float64
	var shove, call [nClass]float64
	var Wi [nClass]float64
	for i := 0; i < nClass; i++ {
		for j := 0; j < nClass; j++ {
			Wi[i] += m.W[i][j]
		}
	}
	strat := func(r [2]float64) float64 {
		a, b := math.Max(r[0], 0), math.Max(r[1], 0)
		if a+b == 0 {
			return 0.5
		}
		return a / (a + b)
	}
	for t := 1; t <= iters; t++ {
		for i := 0; i < nClass; i++ {
			shove[i] = strat(rSB[i])
			call[i] = strat(rBB[i])
		}
		var evS [nClass]float64
		for i := 0; i < nClass; i++ {
			s := 0.0
			for j := 0; j < nClass; j++ {
				s += m.W[i][j] * ((1 - call[j]) + call[j]*payoffSB(m, stack, i, j))
			}
			evS[i] = s / Wi[i]
		}
		for i := 0; i < nClass; i++ {
			v := shove[i]*evS[i] + (1-shove[i])*-0.5
			rSB[i][0] = math.Max(rSB[i][0]+evS[i]-v, 0)
			rSB[i][1] = math.Max(rSB[i][1]+(-0.5)-v, 0)
			sumSB[i][0] += float64(t) * shove[i]
			sumSB[i][1] += float64(t) * (1 - shove[i])
		}
		for j := 0; j < nClass; j++ {
			var num, pi float64
			for i := 0; i < nClass; i++ {
				w := m.W[i][j] * shove[i]
				pi += w
				num += w * -payoffSB(m, stack, i, j)
			}
			if pi == 0 {
				continue
			}
			evC := num / pi
			v := call[j]*evC + (1-call[j])*-1
			rBB[j][0] = math.Max(rBB[j][0]+pi*(evC-v), 0)
			rBB[j][1] = math.Max(rBB[j][1]+pi*(-1-v), 0)
			sumBB[j][0] += float64(t) * pi * call[j]
			sumBB[j][1] += float64(t) * pi * (1 - call[j])
		}
	}
	pf := &PushFold{Stack: stack, Iters: iters}
	for i := 0; i < nClass; i++ {
		if s := sumSB[i][0] + sumSB[i][1]; s > 0 {
			pf.Shove[i] = sumSB[i][0] / s
		}
		if s := sumBB[i][0] + sumBB[i][1]; s > 0 {
			pf.Call[i] = sumBB[i][0] / s
		} else {
			// never faced a shove: report the best reply to the final SB strategy
			pf.Call[i] = 0
		}
	}
	pf.SBValue = sbValue(m, stack, &pf.Shove, &pf.Call)
	// exploitability: best responses to the averaged strategies
	var brS, brC [nClass]float64
	for i := 0; i < nClass; i++ {
		s := 0.0
		for j := 0; j < nClass; j++ {
			s += m.W[i][j] * ((1 - pf.Call[j]) + pf.Call[j]*payoffSB(m, stack, i, j))
		}
		if s/Wi[i] > -0.5 {
			brS[i] = 1
		}
	}
	for j := 0; j < nClass; j++ {
		var num, pi float64
		for i := 0; i < nClass; i++ {
			w := m.W[i][j] * pf.Shove[i]
			pi += w
			num += w * -payoffSB(m, stack, i, j)
		}
		if pi > 0 && num/pi > -1 {
			brC[j] = 1
		}
	}
	vSBbr := sbValue(m, stack, &brS, &pf.Call) // SB best-responds
	vBBbr := sbValue(m, stack, &pf.Shove, &brC)
	pf.Gap = (vSBbr - vBBbr) / 2
	// summary percentages
	var wtot, ws, wc, wcs float64
	for i := 0; i < nClass; i++ {
		var wi float64
		for j := 0; j < nClass; j++ {
			wi += m.W[i][j]
		}
		wtot += wi
		ws += wi * pf.Shove[i]
	}
	pf.ShovePct = 100 * ws / wtot
	for j := 0; j < nClass; j++ {
		var wj float64
		for i := 0; i < nClass; i++ {
			wj += m.W[i][j] * pf.Shove[i]
		}
		wc += wj * pf.Call[j]
		wcs += wj
	}
	if wcs > 0 {
		pf.CallPct = 100 * wc / wcs
	}
	return pf, nil
}

// RangeString lists classes whose frequency is at least minFreq, strongest-first by equity vs random.
func rangeString(freq *[nClass]float64, minFreq float64) string {
	var ids []int
	for i := 0; i < nClass; i++ {
		if freq[i] >= minFreq {
			ids = append(ids, i)
		}
	}
	sort.Slice(ids, func(a, b int) bool {
		ha, la, sa := classRanks(ids[a])
		hb, lb, sb := classRanks(ids[b])
		if ha != hb {
			return ha > hb
		}
		if la != lb {
			return la > lb
		}
		return sa && !sb
	})
	var out []string
	for _, id := range ids {
		n := ClassName(id)
		if freq[id] < 0.995 {
			n += fmt.Sprintf("(%.0f%%)", 100*freq[id])
		}
		out = append(out, n)
	}
	return strings.Join(out, " ")
}

// Grid renders a 13x13 chart of frequencies.
func gridString(freq *[nClass]float64) string {
	var sb strings.Builder
	sb.WriteString("    ")
	for c := 0; c < 13; c++ {
		fmt.Fprintf(&sb, " %c ", rankChars[12-c])
	}
	sb.WriteByte('\n')
	for r := 0; r < 13; r++ {
		fmt.Fprintf(&sb, " %c  ", rankChars[12-r])
		for c := 0; c < 13; c++ {
			f := freq[r*13+c]
			ch := "·"
			switch {
			case f >= 0.95:
				ch = "█"
			case f >= 0.66:
				ch = "▓"
			case f >= 0.33:
				ch = "▒"
			case f >= 0.05:
				ch = "░"
			}
			sb.WriteString(" " + ch + " ")
		}
		sb.WriteByte('\n')
	}
	return sb.String()
}

func cmdPushFold(args []string, out io.Writer) error {
	fs := newFlags("pushfold")
	stack := fs.Float64("stack", 10, "effective stack in big blinds (SB posts 0.5, BB posts 1)")
	samples := fs.Int("samples", 2000, "Monte-Carlo samples per matchup for the equity matrix")
	iters := fs.Int("iters", 3000, "CFR+ iterations")
	seed := fs.Int64("seed", 1, "RNG seed")
	hand := fs.String("hand", "", "show the decision for one hand class, e.g. A5s")
	if _, err := parseInterleaved(fs, args); err != nil {
		return err
	}
	if *stack < 1 || *stack > 1000 {
		return fmt.Errorf("-stack must be between 1 and 1000 big blinds")
	}
	if *iters < 1 {
		return fmt.Errorf("-iters must be ≥ 1")
	}
	hid := -1
	if *hand != "" {
		var err error
		if hid, err = ClassID(*hand); err != nil {
			return err
		}
	}
	m, err := BuildEqMatrix(*samples, *seed, out)
	if err != nil {
		return err
	}
	pf, err := SolvePushFold(m, *stack, *iters)
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "Heads-up push/fold Nash equilibrium, %.1f bb effective\n", pf.Stack)
	fmt.Fprintf(out, "  SB shoves %.1f%% of hands, BB calls %.1f%% of the time it faces a shove\n", pf.ShovePct, pf.CallPct)
	fmt.Fprintf(out, "  SB expected value %+.4f bb/hand,  exploitability %.5f bb/hand\n\n", pf.SBValue, pf.Gap)
	fmt.Fprintf(out, "SB shove range (rows/cols = ranks; above diagonal suited, below offsuit)\n%s\n", gridString(&pf.Shove))
	fmt.Fprintf(out, "BB call range\n%s\n", gridString(&pf.Call))
	fmt.Fprintf(out, "legend: █ ≥95%%  ▓ ≥66%%  ▒ ≥33%%  ░ ≥5%%  · fold\n")
	if hid >= 0 {
		fmt.Fprintf(out, "\n%s: SB shoves %.0f%%, BB calls %.0f%%\n", ClassName(hid), 100*pf.Shove[hid], 100*pf.Call[hid])
	}
	return nil
}
