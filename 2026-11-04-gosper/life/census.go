package life

import (
	"fmt"
	"math/rand"
	"sort"
	"sync"
)

// CensusOptions configures a random-soup census.
type CensusOptions struct {
	Rule    Rule
	Soups   int
	Size    int     // soups are Size x Size
	Density float64 // initial live fraction
	Gens    uint64  // generations to run before reading the ash
	Seed    int64
	Workers int
}

// CensusResult tallies what the ash of many soups consists of.
type CensusResult struct {
	Opts        CensusOptions
	Objects     map[string]int
	TotalObj    int
	DiedOut     int // soups with no survivors
	TooBig      int // ash too large to classify (> MaxAshCells live cells)
	OverBudget  int // Hashlife node budget exceeded
	SumFinalPop uint64
}

// MaxAshCells bounds the ash size the census will classify.
const MaxAshCells = 20000

type namedObj struct {
	name, rle string
}

var knownObjects = []namedObj{
	{"block", "2o$2o!"}, {"beehive", "b2o$o2bo$b2o!"}, {"loaf", "b2o$o2bo$bobo$2bo!"},
	{"boat", "2o$obo$bo!"}, {"ship", "2o$obo$b2o!"}, {"tub", "bo$obo$bo!"},
	{"pond", "b2o$o2bo$o2bo$b2o!"}, {"blinker", "3o!"}, {"toad", "b3o$3o!"},
	{"beacon", "2o2b$2o2b$2b2o$2b2o!"}, {"glider", "bob$2bo$3o!"}, {"lwss", "bo2bo$o4b$o3bo$4o!"},
	{"pentadecathlon", "2bo4bo$2ob4ob2o$2bo4bo!"},
}

var (
	nameTableOnce sync.Once
	nameTable     map[string]string
)

// phaseKey is the minimum canonical key over one full period of the object:
// identical for every phase, translation and orientation.
func phaseKey(rule Rule, pts []Point, period int) (string, error) {
	s := NewSim(rule)
	if err := s.SetCells(append([]Point(nil), pts...), true); err != nil {
		return "", err
	}
	best := ""
	for t := 0; t < period; t++ {
		cs, _ := s.Cells(0)
		k := canonicalKey(cs)
		if best == "" || k < best {
			best = k
		}
		if err := s.Step(1); err != nil {
			return "", err
		}
	}
	return best, nil
}

func buildNameTable() {
	nameTable = map[string]string{}
	for _, o := range knownObjects {
		p, err := ParseRLE(o.rle)
		if err != nil {
			panic(err)
		}
		pr, err := FindPeriod(Life, p.Cells, 64)
		if err != nil || pr.Period == 0 {
			panic("known object is not periodic: " + o.name)
		}
		k, err := phaseKey(Life, p.Cells, pr.Period)
		if err != nil {
			panic(err)
		}
		nameTable[k] = o.name
	}
}

// Identify names an isolated cluster of cells: a well-known object when the rule
// is Conway's Life, otherwise a descriptive label such as "p3 oscillator (12 cells)".
func Identify(rule Rule, pts []Point) string {
	pr, err := FindPeriod(rule, pts, 64)
	if err != nil {
		return "unclassifiable"
	}
	var shape string
	switch pr.Kind {
	case KindStill:
		shape = fmt.Sprintf("still life, %d cells", len(pts))
	case KindOscillator:
		shape = fmt.Sprintf("p%d oscillator, %d cells", pr.Period, len(pts))
	case KindSpaceship:
		shape = fmt.Sprintf("p%d spaceship (%d,%d)", pr.Period, pr.Dx, pr.Dy)
	case KindDies:
		return "dying debris"
	default:
		return "interacting debris"
	}
	if rule == Life {
		nameTableOnce.Do(buildNameTable)
		if k, err := phaseKey(rule, pts, pr.Period); err == nil {
			if n, ok := nameTable[k]; ok {
				return n
			}
		}
	}
	return shape
}

// Clusters groups cells whose Chebyshev distance is <= reach into connected components.
func Clusters(pts []Point, reach int64) [][]Point {
	idx := make(map[Point]int, len(pts))
	for i, p := range pts {
		idx[p] = i
	}
	parent := make([]int, len(pts))
	for i := range parent {
		parent[i] = i
	}
	var find func(int) int
	find = func(i int) int {
		for parent[i] != i {
			parent[i] = parent[parent[i]]
			i = parent[i]
		}
		return i
	}
	for i, p := range pts {
		for dy := int64(-reach); dy <= reach; dy++ {
			for dx := int64(-reach); dx <= reach; dx++ {
				if j, ok := idx[Point{p.X + dx, p.Y + dy}]; ok && j != i {
					a, b := find(i), find(j)
					if a != b {
						parent[a] = b
					}
				}
			}
		}
	}
	groups := map[int][]Point{}
	for i, p := range pts {
		r := find(i)
		groups[r] = append(groups[r], p)
	}
	out := make([][]Point, 0, len(groups))
	for _, g := range groups {
		out = append(out, g)
	}
	sort.Slice(out, func(i, j int) bool { // deterministic order: by lowest (y,x) cell
		a, b := minCell(out[i]), minCell(out[j])
		return a.Y < b.Y || (a.Y == b.Y && a.X < b.X)
	})
	return out
}

// Census runs many random soups and tallies the objects in their ash. The result
// is deterministic for a given seed regardless of Workers.
func Census(o CensusOptions) (*CensusResult, error) {
	if o.Soups < 1 || o.Size < 1 || o.Density <= 0 || o.Density > 1 {
		return nil, fmt.Errorf("census: need soups>=1, size>=1, 0<density<=1")
	}
	if o.Workers < 1 {
		o.Workers = 1
	}
	nameTableOnce.Do(buildNameTable)
	res := &CensusResult{Opts: o, Objects: map[string]int{}}
	var mu sync.Mutex
	jobs := make(chan int)
	var wg sync.WaitGroup
	var firstErr error
	for w := 0; w < o.Workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			cache := map[string]string{}
			for i := range jobs {
				rng := rand.New(rand.NewSource(o.Seed*1_000_003 + int64(i)))
				var pts []Point
				for y := 0; y < o.Size; y++ {
					for x := 0; x < o.Size; x++ {
						if rng.Float64() < o.Density {
							pts = append(pts, Point{int64(x), int64(y)})
						}
					}
				}
				s := NewSim(o.Rule)
				if err := s.SetCells(pts, true); err != nil {
					mu.Lock()
					firstErr = err
					mu.Unlock()
					continue
				}
				err := s.Step(o.Gens)
				local := map[string]int{}
				var dead, big, over int
				var finalPop uint64
				switch {
				case err == ErrBudget:
					over = 1
				case err != nil:
					mu.Lock()
					firstErr = err
					mu.Unlock()
					continue
				case s.Population() == 0:
					dead = 1
				case s.Population() > MaxAshCells:
					big, finalPop = 1, s.Population()
				default:
					finalPop = s.Population()
					cells, _ := s.Cells(0)
					for _, cl := range Clusters(cells, 2) {
						n, _, _ := normalise(cl)
						key := keyOf(n)
						name, ok := cache[key]
						if !ok {
							name = Identify(o.Rule, cl)
							if len(cache) < 100000 {
								cache[key] = name
							}
						}
						local[name]++
					}
				}
				mu.Lock()
				for k, v := range local {
					res.Objects[k] += v
					res.TotalObj += v
				}
				res.DiedOut += dead
				res.TooBig += big
				res.OverBudget += over
				res.SumFinalPop += finalPop
				mu.Unlock()
			}
		}()
	}
	for i := 0; i < o.Soups; i++ {
		jobs <- i
	}
	close(jobs)
	wg.Wait()
	if firstErr != nil {
		return nil, firstErr
	}
	return res, nil
}

// Row is one line of the census table.
type Row struct {
	Name  string
	Count int
}

// Sorted returns the tally by descending count, ties by name.
func (r *CensusResult) Sorted() []Row {
	rows := make([]Row, 0, len(r.Objects))
	for k, v := range r.Objects {
		rows = append(rows, Row{k, v})
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Count != rows[j].Count {
			return rows[i].Count > rows[j].Count
		}
		return rows[i].Name < rows[j].Name
	})
	return rows
}

func minCell(g []Point) Point {
	m := g[0]
	for _, p := range g[1:] {
		if p.Y < m.Y || (p.Y == m.Y && p.X < m.X) {
			m = p
		}
	}
	return m
}
