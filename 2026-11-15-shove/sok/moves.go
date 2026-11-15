package sok

import "fmt"

// Result of replaying a move string.
type Result struct {
	Moves, Pushes int
	Boxes         []int
	Player        int
	Solved        bool
}

func dirOf(c byte) (int, bool) {
	switch c {
	case 'u', 'U':
		return 0, true
	case 'd', 'D':
		return 1, true
	case 'l', 'L':
		return 2, true
	case 'r', 'R':
		return 3, true
	}
	return 0, false
}

// Replay executes an LURD string (case-insensitive; uppercase conventionally marks pushes)
// against the level's start position and reports the end state. It is deliberately
// independent of the solver: it only knows the rules.
func (lv *Level) Replay(moves string) (*Result, error) {
	boxAt := make(map[int]bool, len(lv.Boxes))
	for _, b := range lv.Boxes {
		boxAt[b] = true
	}
	p := lv.Player
	res := &Result{}
	for i := 0; i < len(moves); i++ {
		c := moves[i]
		if c == ' ' || c == '\n' || c == '\r' {
			continue
		}
		d, ok := dirOf(c)
		if !ok {
			return nil, fmt.Errorf("move %d: illegal character %q", i+1, c)
		}
		n := p + delta(d, lv.W)
		if lv.Wall[n] {
			return nil, fmt.Errorf("move %d (%c): walks into a wall", i+1, c)
		}
		if boxAt[n] {
			nn := n + delta(d, lv.W)
			if lv.Wall[nn] || boxAt[nn] {
				return nil, fmt.Errorf("move %d (%c): push blocked", i+1, c)
			}
			delete(boxAt, n)
			boxAt[nn] = true
			res.Pushes++
		}
		p = n
		res.Moves++
	}
	for b := range boxAt {
		res.Boxes = append(res.Boxes, b)
	}
	sortInts(res.Boxes)
	res.Player = p
	res.Solved = lv.Solved(res.Boxes)
	return res, nil
}

func sortInts(a []int) {
	for i := 1; i < len(a); i++ {
		for j := i; j > 0 && a[j] < a[j-1]; j-- {
			a[j], a[j-1] = a[j-1], a[j]
		}
	}
}

// Verify returns nil only if moves are legal and end with all boxes on goals.
func (lv *Level) Verify(moves string) (*Result, error) {
	r, err := lv.Replay(moves)
	if err != nil {
		return nil, err
	}
	if !r.Solved {
		return r, fmt.Errorf("legal, but ends unsolved (%d/%d boxes on goals)", countOn(lv, r.Boxes), len(r.Boxes))
	}
	return r, nil
}

func countOn(lv *Level, boxes []int) int {
	n := 0
	for _, b := range boxes {
		if lv.Goal[b] {
			n++
		}
	}
	return n
}
