package cube

import (
	"errors"
	"fmt"
	"time"
)

// Options tune the two-phase search.
type Options struct {
	Target    int           // stop as soon as a solution this short is found (default 20)
	MaxLen    int           // never return anything longer (default 30)
	TimeLimit time.Duration // keep improving until this long (default 2s); a first solution is always returned
}

// Result is a solved cube's answer.
type Result struct {
	Moves   []Move
	Phase1  int // number of moves in phase 1 (reach <U,D,R2,L2,F2,B2>)
	Elapsed time.Duration
	Nodes   uint64
}

func (o *Options) defaults() {
	if o.Target <= 0 {
		o.Target = 20
	}
	if o.MaxLen <= 0 {
		o.MaxLen = 30
	}
	if o.TimeLimit <= 0 {
		o.TimeLimit = 2 * time.Second
	}
}

type search struct {
	t        *Tables
	start    Cube
	opt      Options
	deadline time.Time
	path     [48]int
	path2    [48]int
	best     []Move
	bestP1   int
	nodes    uint64
	done     bool
}

func (s *search) limit() int {
	l := s.opt.MaxLen
	if s.best != nil && len(s.best)-1 < l {
		l = len(s.best) - 1
	}
	return l
}

// Solve finds a (near-optimal) solution with Kociemba's two-phase algorithm.
func Solve(c Cube, opt Options) (Result, error) {
	if err := c.Check(); err != nil {
		return Result{}, err
	}
	opt.defaults()
	tb := GetTables() // built once; not counted in the solve time
	begin := time.Now()
	s := &search{t: tb, start: c, opt: opt, deadline: begin.Add(opt.TimeLimit)}
	twist, flip, slc := c.twist(), c.flip(), c.slice()
	for d := 0; d <= opt.MaxLen && !s.done; d++ {
		if s.best != nil && d >= len(s.best) {
			break
		}
		s.p1(twist, flip, slc, d, d, -1)
	}
	if s.best == nil {
		return Result{}, errors.New("no solution within MaxLen")
	}
	out := Simplify(s.best)
	if !c.ApplySeq(out).IsSolved() {
		return Result{}, errors.New("internal error: solution does not solve the cube")
	}
	return Result{Moves: out, Phase1: s.bestP1, Elapsed: time.Since(begin), Nodes: s.nodes}, nil
}

func skipFace(face, last int) bool {
	return last >= 0 && (face == last || (last >= 3 && face == last-3))
}

func (s *search) p1(twist, flip, slc, togo, depth, lastFace int) {
	if s.done {
		return
	}
	s.nodes++
	if s.nodes&0x3fff == 0 && s.best != nil && time.Now().After(s.deadline) {
		s.done = true
		return
	}
	t := s.t
	h := t.pruneTS[twist*nSlice+slc]
	if h2 := t.pruneFS[flip*nSlice+slc]; h2 > h {
		h = h2
	}
	if int(h) > togo {
		return
	}
	if togo == 0 {
		// h == 0 here: twist, flip, slice are all solved => cube is in G1.
		if depth > 0 {
			m := s.path[depth-1]
			if f := m / 3; f == U || f == D || m%3 == 1 {
				return // would have been found one move earlier
			}
		}
		s.phase2(depth)
		return
	}
	for m := 0; m < 18; m++ {
		face := m / 3
		if skipFace(face, lastFace) {
			continue
		}
		s.path[depth-togo] = m
		s.p1(int(t.twistMove[twist][m]), int(t.flipMove[flip][m]), int(t.sliceMove[slc][m]), togo-1, depth, face)
		if s.done {
			return
		}
	}
}

func (s *search) phase2(d1 int) {
	c := s.start
	for i := 0; i < d1; i++ {
		c = c.Mul(MoveCube[s.path[i]])
	}
	cp, ud, sp := c.cpRank(), c.udRank(), c.spRank()
	maxD2 := s.limit() - d1
	last := -1
	if d1 > 0 {
		last = s.path[d1-1] / 3
	}
	for d2 := 0; d2 <= maxD2; d2++ {
		if s.p2(cp, ud, sp, d2, 0, last) {
			sol := make([]Move, 0, d1+d2)
			for i := 0; i < d1; i++ {
				sol = append(sol, Move(s.path[i]))
			}
			for i := 0; i < d2; i++ {
				sol = append(sol, Move(s.path2[i]))
			}
			s.best, s.bestP1 = sol, d1
			if len(sol) <= s.opt.Target || time.Now().After(s.deadline) {
				s.done = true
			}
			return
		}
	}
}

func (s *search) p2(cp, ud, sp, togo, depth, lastFace int) bool {
	s.nodes++
	t := s.t
	h := t.pruneCS[cp*nPerm4+sp]
	if h2 := t.pruneUS[ud*nPerm4+sp]; h2 > h {
		h = h2
	}
	if int(h) > togo {
		return false
	}
	if togo == 0 {
		return true
	}
	for j := 0; j < nP2; j++ {
		m := phase2Moves[j]
		face := m / 3
		if skipFace(face, lastFace) {
			continue
		}
		s.path2[depth] = m
		if s.p2(int(t.cpMove[cp][j]), int(t.udMove[ud][j]), int(t.spMove[sp][j]), togo-1, depth+1, face) {
			return true
		}
	}
	return false
}

// SolveFacelets is a convenience: parse, validate and solve a facelet string.
func SolveFacelets(f string, opt Options) (Result, error) {
	c, err := ParseFacelets(f)
	if err != nil {
		return Result{}, fmt.Errorf("invalid cube: %w", err)
	}
	return Solve(c, opt)
}
