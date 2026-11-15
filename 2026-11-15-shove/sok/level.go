// Package sok implements Sokoban: parsing, simulation, deadlock detection,
// an optimal solver, and a reverse-play level generator.
package sok

import (
	"fmt"
	"sort"
	"strings"
)

// Level is the static part of a puzzle (walls + goals) plus its start state.
type Level struct {
	W, H   int
	Wall   []bool
	Goal   []bool
	Boxes  []int // start box cells (sorted)
	Player int   // start player cell
	Name   string
}

// Dir indexes: U D L R
var dirName = [4]byte{'u', 'd', 'l', 'r'}

// Delta returns the cell-index offset for direction d on a level of width w.
func delta(d, w int) int {
	switch d {
	case 0:
		return -w
	case 1:
		return w
	case 2:
		return -1
	}
	return 1
}

// ParseError carries a line number.
type ParseError struct {
	Line int
	Msg  string
}

func (e *ParseError) Error() string { return fmt.Sprintf("line %d: %s", e.Line, e.Msg) }

// Parse reads one level in XSB format:  # wall, @ player, + player on goal,
// $ box, * box on goal, . goal, space/_/- floor.
func Parse(text string) (*Level, error) {
	raw := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	var rows []string
	name := ""
	first := -1
	for i, l := range raw {
		t := strings.TrimRight(l, " \t")
		if strings.HasPrefix(strings.TrimSpace(t), ";") {
			if name == "" {
				name = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(t), ";"))
			}
			continue
		}
		if strings.TrimSpace(t) == "" {
			if len(rows) > 0 {
				break // blank line ends the level
			}
			continue
		}
		if first < 0 {
			first = i + 1
		}
		rows = append(rows, t)
	}
	if len(rows) == 0 {
		return nil, &ParseError{1, "empty level"}
	}
	w := 0
	for _, r := range rows {
		if len(r) > w {
			w = len(r)
		}
	}
	lv := &Level{W: w, H: len(rows), Name: name, Player: -1}
	lv.Wall = make([]bool, w*lv.H)
	lv.Goal = make([]bool, w*lv.H)
	players := 0
	for y, r := range rows {
		for x := 0; x < w; x++ {
			c := byte(' ')
			if x < len(r) {
				c = r[x]
			}
			i := y*w + x
			switch c {
			case '#':
				lv.Wall[i] = true
			case '@':
				lv.Player = i
				players++
			case '+':
				lv.Player = i
				lv.Goal[i] = true
				players++
			case '$':
				lv.Boxes = append(lv.Boxes, i)
			case '*':
				lv.Boxes = append(lv.Boxes, i)
				lv.Goal[i] = true
			case '.':
				lv.Goal[i] = true
			case ' ', '_', '-':
			default:
				return nil, &ParseError{first + y, fmt.Sprintf("illegal character %q at column %d", c, x+1)}
			}
		}
	}
	if players != 1 {
		return nil, &ParseError{first, fmt.Sprintf("need exactly one player, found %d", players)}
	}
	ng := 0
	for _, g := range lv.Goal {
		if g {
			ng++
		}
	}
	if len(lv.Boxes) == 0 {
		return nil, &ParseError{first, "level has no boxes"}
	}
	if len(lv.Boxes) != ng {
		return nil, &ParseError{first, fmt.Sprintf("%d boxes but %d goals", len(lv.Boxes), ng)}
	}
	sort.Ints(lv.Boxes)
	for i := range lv.Goal {
		x, y := i%w, i/w
		if (x == 0 || y == 0 || x == w-1 || y == lv.H-1) && !lv.Wall[i] {
			isBox := false
			for _, b := range lv.Boxes {
				isBox = isBox || b == i
			}
			if lv.Goal[i] || isBox {
				return nil, &ParseError{first + y, fmt.Sprintf("box or goal on the grid edge at column %d (surround the level with walls)", x+1)}
			}
		}
	}
	if err := lv.checkEnclosed(first); err != nil {
		return nil, err
	}
	return lv, nil
}

// checkEnclosed makes sure the player's region cannot escape the grid.
func (lv *Level) checkEnclosed(line int) error {
	seen := make([]bool, lv.W*lv.H)
	stack := []int{lv.Player}
	seen[lv.Player] = true
	for len(stack) > 0 {
		c := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		x, y := c%lv.W, c/lv.W
		if x == 0 || y == 0 || x == lv.W-1 || y == lv.H-1 {
			return &ParseError{line + y, "level is not enclosed by walls (player area touches the edge)"}
		}
		for d := 0; d < 4; d++ {
			n := c + delta(d, lv.W)
			if !lv.Wall[n] && !seen[n] {
				seen[n] = true
				stack = append(stack, n)
			}
		}
	}
	return nil
}

// ParsePack splits a text file with several levels (blank-line separated,
// optional ";name" comments) into levels.
func ParsePack(text string) ([]*Level, error) {
	var out []*Level
	var cur []string
	flush := func(startLine int) error {
		if len(cur) == 0 {
			return nil
		}
		hasMap := false
		for _, l := range cur {
			if !strings.HasPrefix(strings.TrimSpace(l), ";") {
				hasMap = true
			}
		}
		if hasMap {
			lv, err := Parse(strings.Join(cur, "\n"))
			if err != nil {
				pe := err.(*ParseError)
				return &ParseError{startLine + pe.Line - 1, fmt.Sprintf("level %d: %s", len(out)+1, pe.Msg)}
			}
			if lv.Name == "" {
				lv.Name = fmt.Sprintf("Level %d", len(out)+1)
			}
			out = append(out, lv)
		}
		cur = nil
		return nil
	}
	start := 1
	for i, l := range strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n") {
		if strings.TrimSpace(l) == "" {
			// A blank line separates levels (comment-only chunks attach to the next map).
			onlyComments := len(cur) > 0
			for _, c := range cur {
				if !strings.HasPrefix(strings.TrimSpace(c), ";") {
					onlyComments = false
				}
			}
			if onlyComments {
				continue
			}
			if err := flush(start); err != nil {
				return nil, err
			}
			start = i + 2
			continue
		}
		if len(cur) == 0 {
			start = i + 1
		}
		cur = append(cur, l)
	}
	if err := flush(start); err != nil {
		return nil, err
	}
	if len(out) == 0 {
		return nil, &ParseError{1, "no levels found"}
	}
	return out, nil
}

// Format renders a level (with the given boxes/player) back to XSB.
func (lv *Level) Format(boxes []int, player int) string {
	isBox := map[int]bool{}
	for _, b := range boxes {
		isBox[b] = true
	}
	var sb strings.Builder
	for y := 0; y < lv.H; y++ {
		line := make([]byte, lv.W)
		for x := 0; x < lv.W; x++ {
			i := y*lv.W + x
			c := byte(' ')
			switch {
			case lv.Wall[i]:
				c = '#'
			case isBox[i] && lv.Goal[i]:
				c = '*'
			case isBox[i]:
				c = '$'
			case i == player && lv.Goal[i]:
				c = '+'
			case i == player:
				c = '@'
			case lv.Goal[i]:
				c = '.'
			}
			line[x] = c
		}
		sb.WriteString(strings.TrimRight(string(line), " "))
		sb.WriteByte('\n')
	}
	return sb.String()
}

// String formats the start position.
func (lv *Level) String() string { return lv.Format(lv.Boxes, lv.Player) }

// Solved reports whether every box sits on a goal.
func (lv *Level) Solved(boxes []int) bool {
	for _, b := range boxes {
		if !lv.Goal[b] {
			return false
		}
	}
	return true
}
