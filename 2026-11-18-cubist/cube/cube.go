// Package cube implements a Rubik's Cube: cubie model, notation, facelets,
// a Kociemba two-phase solver and an independent physical simulation.
package cube

import (
	"fmt"
	"strings"
)

// Corner and edge piece names (Kociemba convention).
const (
	URF = iota
	UFL
	ULB
	UBR
	DFR
	DLF
	DBL
	DRB
)
const (
	UR = iota
	UF
	UL
	UB
	DR
	DF
	DL
	DB
	FR
	FL
	BL
	BR
)

// Faces in move-index order.
const (
	U = iota
	R
	F
	D
	L
	B
)

// Cube is the cubie-level state. CP[i] is the corner currently at position i,
// CO[i] its twist (0..2); EP/EO likewise for edges (flip 0..1).
type Cube struct {
	CP [8]uint8
	CO [8]uint8
	EP [12]uint8
	EO [12]uint8
}

// Solved returns the identity cube.
func Solved() Cube {
	var c Cube
	for i := range c.CP {
		c.CP[i] = uint8(i)
	}
	for i := range c.EP {
		c.EP[i] = uint8(i)
	}
	return c
}

// Mul returns the state after applying b to a (a, then b).
func (a Cube) Mul(b Cube) Cube {
	var r Cube
	for i := 0; i < 8; i++ {
		r.CP[i] = a.CP[b.CP[i]]
		r.CO[i] = (a.CO[b.CP[i]] + b.CO[i]) % 3
	}
	for i := 0; i < 12; i++ {
		r.EP[i] = a.EP[b.EP[i]]
		r.EO[i] = (a.EO[b.EP[i]] + b.EO[i]) % 2
	}
	return r
}

// Inverse returns the cube c' with c.Mul(c') == Solved().
func (a Cube) Inverse() Cube {
	var r Cube
	for i := 0; i < 8; i++ {
		r.CP[a.CP[i]] = uint8(i)
	}
	for i := 0; i < 8; i++ {
		r.CO[i] = (3 - a.CO[r.CP[i]]) % 3
	}
	for i := 0; i < 12; i++ {
		r.EP[a.EP[i]] = uint8(i)
	}
	for i := 0; i < 12; i++ {
		r.EO[i] = a.EO[r.EP[i]]
	}
	return r
}

// IsSolved reports whether c is the identity.
func (a Cube) IsSolved() bool { return a == Solved() }

var baseMoves = [6]Cube{
	U: {CP: [8]uint8{UBR, URF, UFL, ULB, DFR, DLF, DBL, DRB},
		EP: [12]uint8{UB, UR, UF, UL, DR, DF, DL, DB, FR, FL, BL, BR}},
	R: {CP: [8]uint8{DFR, UFL, ULB, URF, DRB, DLF, DBL, UBR}, CO: [8]uint8{2, 0, 0, 1, 1, 0, 0, 2},
		EP: [12]uint8{FR, UF, UL, UB, BR, DF, DL, DB, DR, FL, BL, UR}},
	F: {CP: [8]uint8{UFL, DLF, ULB, UBR, URF, DFR, DBL, DRB}, CO: [8]uint8{1, 2, 0, 0, 2, 1, 0, 0},
		EP: [12]uint8{UR, FL, UL, UB, DR, FR, DL, DB, UF, DF, BL, BR}, EO: [12]uint8{0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0}},
	D: {CP: [8]uint8{URF, UFL, ULB, UBR, DLF, DBL, DRB, DFR},
		EP: [12]uint8{UR, UF, UL, UB, DF, DL, DB, DR, FR, FL, BL, BR}},
	L: {CP: [8]uint8{URF, ULB, DBL, UBR, DFR, UFL, DLF, DRB}, CO: [8]uint8{0, 1, 2, 0, 0, 2, 1, 0},
		EP: [12]uint8{UR, UF, BL, UB, DR, DF, FL, DB, FR, UL, DL, BR}},
	B: {CP: [8]uint8{URF, UFL, UBR, DRB, DFR, DLF, ULB, DBL}, CO: [8]uint8{0, 0, 1, 2, 0, 0, 2, 1},
		EP: [12]uint8{UR, UF, UL, BR, DR, DF, DL, BL, FR, FL, UB, DB}, EO: [12]uint8{0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1}},
}

// MoveCube[m] is the cube transformation of move m = face*3 + (turns-1).
var MoveCube [18]Cube

func init() {
	for f := 0; f < 6; f++ {
		c := baseMoves[f]
		MoveCube[f*3] = c
		c = c.Mul(baseMoves[f])
		MoveCube[f*3+1] = c
		c = c.Mul(baseMoves[f])
		MoveCube[f*3+2] = c
	}
}

// Move is an index 0..17: face*3 + (quarter turns clockwise − 1).
type Move int

const faceLetters = "URFDLB"

func (m Move) Face() int  { return int(m) / 3 }
func (m Move) Turns() int { return int(m)%3 + 1 }

func (m Move) String() string {
	s := string(faceLetters[m.Face()])
	switch m.Turns() {
	case 2:
		return s + "2"
	case 3:
		return s + "'"
	}
	return s
}

// Inverse of a move (R <-> R', R2 <-> R2).
func (m Move) Inverse() Move { return Move(m.Face()*3 + (4 - m.Turns()) - 1) }

// Apply returns c with move m applied.
func (a Cube) Apply(m Move) Cube { return a.Mul(MoveCube[m]) }

// ApplySeq applies a sequence of moves.
func (a Cube) ApplySeq(ms []Move) Cube {
	for _, m := range ms {
		a = a.Apply(m)
	}
	return a
}

// ParseMoves parses standard face-turn notation: U R F D L B with optional 2, ', 3.
// Whitespace separated or run together ("RUR'U'"). Slice/wide/rotation moves are rejected.
func ParseMoves(s string) ([]Move, error) {
	s = strings.NewReplacer("’", "'", "‘", "'", "`", "'").Replace(s)
	var out []Move
	rs := []rune(s)
	for i := 0; i < len(rs); {
		ch := rs[i]
		switch {
		case ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' || ch == ',':
			i++
			continue
		case ch == '(' || ch == ')':
			i++
			continue
		}
		f := strings.IndexRune(faceLetters, ch)
		if f < 0 {
			if strings.ContainsRune("MESxyzudrlfbmesXYZ", ch) {
				return nil, fmt.Errorf("unsupported move %q at position %d (only face turns U R F D L B are supported)", string(ch), i+1)
			}
			return nil, fmt.Errorf("unexpected character %q at position %d", string(ch), i+1)
		}
		i++
		turns := 1
		for i < len(rs) {
			switch rs[i] {
			case '2':
				turns = (turns * 2) % 4
				i++
				continue
			case '\'':
				turns = (turns * 3) % 4
				i++
				continue
			case '3':
				turns = (turns * 3) % 4
				i++
				continue
			case 'w':
				return nil, fmt.Errorf("wide moves are not supported (position %d)", i+1)
			}
			break
		}
		if turns == 0 {
			continue // e.g. R2' ... R4 style no-op
		}
		out = append(out, Move(f*3+turns-1))
	}
	return out, nil
}

// FormatMoves renders a move list.
func FormatMoves(ms []Move) string {
	parts := make([]string, len(ms))
	for i, m := range ms {
		parts[i] = m.String()
	}
	return strings.Join(parts, " ")
}

// InvertSeq returns the sequence that undoes ms.
func InvertSeq(ms []Move) []Move {
	out := make([]Move, len(ms))
	for i, m := range ms {
		out[len(ms)-1-i] = m.Inverse()
	}
	return out
}

// Simplify merges adjacent turns of the same face, also across commuting opposite faces
// (R L R' -> L), and drops cancelled moves.
func Simplify(ms []Move) []Move {
	var out []Move
	for _, m := range ms {
		f := m.Face()
		placed := false
		for j := len(out) - 1; j >= 0; j-- {
			fj := out[j].Face()
			if fj == f {
				t := (out[j].Turns() + m.Turns()) % 4
				if t == 0 {
					out = append(out[:j], out[j+1:]...)
				} else {
					out[j] = Move(f*3 + t - 1)
				}
				placed = true
				break
			}
			if fj == (f+3)%6 {
				continue
			}
			break
		}
		if !placed {
			out = append(out, m)
		}
	}
	return out
}

// Scramble returns the solved cube with ms applied.
func FromMoves(ms []Move) Cube { return Solved().ApplySeq(ms) }

func parity(p []uint8) int {
	n := 0
	for i := 0; i < len(p); i++ {
		for j := i + 1; j < len(p); j++ {
			if p[i] > p[j] {
				n++
			}
		}
	}
	return n & 1
}
