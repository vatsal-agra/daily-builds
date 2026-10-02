// Package data loads tabular datasets and generates the physics benchmarks.
package data

import (
	"encoding/csv"
	"fmt"
	"io"
	"math"
	"math/rand"
	"os"
	"strconv"
	"strings"
)

// Dataset is rows of inputs X (len = len(Names)) and a target Y.
type Dataset struct {
	Names  []string // input variable names
	Target string
	X      [][]float64
	Y      []float64
}

func (d *Dataset) N() int { return len(d.Y) }

// ReadCSV parses a CSV with a header row. target names the output column; if
// empty the last column is used. Blank lines/ragged rows/non-numeric cells are
// reported with line numbers rather than silently skipped.
func ReadCSV(r io.Reader, target string) (*Dataset, error) {
	cr := csv.NewReader(r)
	cr.TrimLeadingSpace = true
	cr.FieldsPerRecord = -1
	cr.Comment = '#'
	recs, err := cr.ReadAll()
	if err != nil {
		return nil, fmt.Errorf("csv: %w", err)
	}
	if len(recs) < 2 {
		return nil, fmt.Errorf("csv: need a header and at least one data row")
	}
	head := recs[0]
	for i := range head {
		head[i] = strings.TrimSpace(head[i])
		if head[i] == "" {
			return nil, fmt.Errorf("csv: empty column name in column %d", i+1)
		}
	}
	if len(head) < 2 {
		return nil, fmt.Errorf("csv: need at least one input column and a target column")
	}
	ti := len(head) - 1
	if target != "" {
		ti = -1
		for i, h := range head {
			if h == target {
				ti = i
			}
		}
		if ti < 0 {
			return nil, fmt.Errorf("csv: target column %q not found (columns: %s)", target, strings.Join(head, ", "))
		}
	}
	d := &Dataset{Target: head[ti]}
	for i, h := range head {
		if i != ti {
			if !validIdent(h) {
				return nil, fmt.Errorf("csv: column name %q is not a valid identifier (letters, digits, _)", h)
			}
			d.Names = append(d.Names, h)
		}
	}
	for ln, rec := range recs[1:] {
		line := ln + 2
		if len(rec) == 1 && strings.TrimSpace(rec[0]) == "" {
			continue
		}
		if len(rec) != len(head) {
			return nil, fmt.Errorf("csv: row %d has %d fields, expected %d", line, len(rec), len(head))
		}
		row := make([]float64, 0, len(head)-1)
		var y float64
		for i, cell := range rec {
			v, err := strconv.ParseFloat(strings.TrimSpace(cell), 64)
			if err != nil || math.IsNaN(v) || math.IsInf(v, 0) {
				return nil, fmt.Errorf("csv: row %d column %q: %q is not a finite number", line, head[i], cell)
			}
			if i == ti {
				y = v
			} else {
				row = append(row, v)
			}
		}
		d.X = append(d.X, row)
		d.Y = append(d.Y, y)
	}
	if d.N() < 5 {
		return nil, fmt.Errorf("csv: only %d data rows; need at least 5", d.N())
	}
	return d, nil
}

func validIdent(s string) bool {
	for i, c := range s {
		if !(c == '_' || c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || (i > 0 && c >= '0' && c <= '9')) {
			return false
		}
	}
	return s != "" && s != "pi" && s != "e"
}

func LoadCSV(path, target string) (*Dataset, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return ReadCSV(f, target)
}

// WriteCSV serialises a dataset.
func (d *Dataset) WriteCSV(w io.Writer) error {
	cw := csv.NewWriter(w)
	cw.Write(append(append([]string{}, d.Names...), d.Target))
	for i := range d.Y {
		rec := make([]string, 0, len(d.Names)+1)
		for _, v := range d.X[i] {
			rec = append(rec, strconv.FormatFloat(v, 'g', 10, 64))
		}
		rec = append(rec, strconv.FormatFloat(d.Y[i], 'g', 10, 64))
		cw.Write(rec)
	}
	cw.Flush()
	return cw.Error()
}

// Split deterministically shuffles and splits into train / holdout.
func (d *Dataset) Split(frac float64, seed int64) (train, hold *Dataset) {
	rng := rand.New(rand.NewSource(seed))
	idx := rng.Perm(d.N())
	nh := int(float64(d.N()) * frac)
	if nh < 1 {
		nh = 1
	}
	if nh > d.N()-3 {
		nh = d.N() - 3
	}
	mk := func(ix []int) *Dataset {
		o := &Dataset{Names: d.Names, Target: d.Target}
		for _, i := range ix {
			o.X = append(o.X, d.X[i])
			o.Y = append(o.Y, d.Y[i])
		}
		return o
	}
	return mk(idx[nh:]), mk(idx[:nh])
}

// Benchmark describes a law with known ground truth.
type Benchmark struct {
	Name   string
	Desc   string
	Truth  string // formula in expr syntax
	Names  []string
	Target string
	Ranges [][2]float64
	Fn     func(x []float64) float64
	Noise  float64 // relative gaussian noise on y
}

const G = 6.674e-11

// Benchmarks are real physical laws; data is sampled from the true formula
// (+ optional measurement noise), which is how symbolic regression is evaluated.
var Benchmarks = []Benchmark{
	{"kepler", "Kepler's 3rd law: orbital period (years) vs semi-major axis (AU)",
		"a^1.5", []string{"a"}, "T", [][2]float64{{0.3, 30}},
		func(x []float64) float64 { return math.Pow(x[0], 1.5) }, 0.0},
	{"pendulum", "Pendulum period T = 2*pi*sqrt(L/g)",
		"2*pi*sqrt(L/g)", []string{"L", "g"}, "T", [][2]float64{{0.1, 5}, {1, 20}},
		func(x []float64) float64 { return 2 * math.Pi * math.Sqrt(x[0]/x[1]) }, 0.0},
	{"kinetic", "Kinetic energy E = m*v^2/2",
		"0.5*m*v^2", []string{"m", "v"}, "E", [][2]float64{{0.5, 10}, {0.5, 12}},
		func(x []float64) float64 { return 0.5 * x[0] * x[1] * x[1] }, 0.0},
	{"gravity", "Newtonian gravitational force F = G*m1*m2/r^2 (G scaled to 1e-11 units)",
		"6.674*m1*m2/r^2", []string{"m1", "m2", "r"}, "F", [][2]float64{{1, 10}, {1, 10}, {1, 8}},
		func(x []float64) float64 { return 6.674 * x[0] * x[1] / (x[2] * x[2]) }, 0.0},
	{"decay", "Radioactive decay N = N0*exp(-0.3 t) with 1% measurement noise",
		"100*exp(-0.3*t)", []string{"t"}, "N", [][2]float64{{0, 10}},
		func(x []float64) float64 { return 100 * math.Exp(-0.3*x[0]) }, 0.01},
	{"wave", "Damped oscillation y = 5*exp(-0.2 t)*cos(2 t)",
		"5*exp(-0.2*t)*cos(2*t)", []string{"t"}, "y", [][2]float64{{0, 8}},
		func(x []float64) float64 { return 5 * math.Exp(-0.2*x[0]) * math.Cos(2*x[0]) }, 0.0},
	{"idealgas", "Ideal gas pressure P = n*R*T/V (R=8.314)",
		"8.314*n*T/V", []string{"n", "T", "V"}, "P", [][2]float64{{0.5, 5}, {200, 500}, {1, 10}},
		func(x []float64) float64 { return 8.314 * x[0] * x[1] / x[2] }, 0.0},
}

func Find(name string) (*Benchmark, bool) {
	for i := range Benchmarks {
		if Benchmarks[i].Name == name {
			return &Benchmarks[i], true
		}
	}
	return nil, false
}

// Generate samples n points uniformly from the benchmark's ranges.
func (b *Benchmark) Generate(n int, seed int64) *Dataset {
	rng := rand.New(rand.NewSource(seed))
	d := &Dataset{Names: b.Names, Target: b.Target}
	for i := 0; i < n; i++ {
		x := make([]float64, len(b.Names))
		for j := range x {
			lo, hi := b.Ranges[j][0], b.Ranges[j][1]
			x[j] = lo + rng.Float64()*(hi-lo)
		}
		y := b.Fn(x)
		if b.Noise > 0 {
			y *= 1 + b.Noise*rng.NormFloat64()
		}
		d.X = append(d.X, x)
		d.Y = append(d.Y, y)
	}
	return d
}
