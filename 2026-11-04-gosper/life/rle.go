package life

import (
	"bufio"
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// Pattern is a parsed pattern file: cells plus metadata.
type Pattern struct {
	Name     string
	Comments []string
	Rule     Rule
	HasRule  bool
	Cells    []Point
	Gen      uint64 // from Macrocell #G, otherwise 0
}

// ParsePattern sniffs the format (Macrocell, RLE or plaintext) and parses it.
func ParsePattern(text string) (*Pattern, error) {
	t := strings.TrimLeft(strings.TrimPrefix(text, "\xef\xbb\xbf"), " \t\r\n")
	switch {
	case strings.HasPrefix(t, "[M2]"):
		return nil, fmt.Errorf("macrocell data must be loaded with Sim.LoadMacrocell")
	case strings.HasPrefix(t, "!"):
		return ParseCells(text)
	}
	// RLE has either a header line "x = ..." or only #-comments + body.
	for _, ln := range strings.Split(t, "\n") {
		ln = strings.TrimSpace(ln)
		if ln == "" || strings.HasPrefix(ln, "#") {
			continue
		}
		if strings.HasPrefix(ln, "x") || strings.HasPrefix(ln, "X") || strings.HasSuffix(ln, "!") {
			return ParseRLE(text)
		}
		if strings.ContainsAny(ln, ".O*") && !strings.ContainsAny(ln, "bo$0123456789") {
			return ParseCells(text)
		}
		break
	}
	return ParseRLE(text)
}

// ParseRLE parses Run Length Encoded patterns.
func ParseRLE(text string) (*Pattern, error) {
	p := &Pattern{}
	var body strings.Builder
	headerSeen := false
	sc := bufio.NewScanner(strings.NewReader(text))
	sc.Buffer(make([]byte, 1<<20), 1<<28)
	for sc.Scan() {
		ln := strings.TrimSpace(sc.Text())
		if ln == "" {
			continue
		}
		if ln[0] == '#' {
			switch {
			case strings.HasPrefix(ln, "#N"):
				p.Name = strings.TrimSpace(ln[2:])
			case strings.HasPrefix(ln, "#C"), strings.HasPrefix(ln, "#c"), strings.HasPrefix(ln, "#O"):
				p.Comments = append(p.Comments, strings.TrimSpace(ln[2:]))
			case strings.HasPrefix(ln, "#r"):
				if r, err := ParseRule(strings.TrimSpace(ln[2:])); err == nil {
					p.Rule, p.HasRule = r, true
				}
			}
			continue
		}
		if !headerSeen && (ln[0] == 'x' || ln[0] == 'X') {
			headerSeen = true
			for _, f := range strings.Split(ln, ",") {
				kv := strings.SplitN(f, "=", 2)
				if len(kv) == 2 && strings.EqualFold(strings.TrimSpace(kv[0]), "rule") {
					r, err := ParseRule(strings.TrimSpace(kv[1]))
					if err != nil {
						return nil, fmt.Errorf("rle header: %w", err)
					}
					p.Rule, p.HasRule = r, true
				}
			}
			continue
		}
		body.WriteString(ln)
		if strings.Contains(ln, "!") {
			break
		}
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	b := body.String()
	if b == "" {
		return nil, fmt.Errorf("rle: no pattern data")
	}
	var x, y int64
	run := int64(-1)
	terminated := false
loop:
	for i := 0; i < len(b); i++ {
		c := b[i]
		switch {
		case c >= '0' && c <= '9':
			if run < 0 {
				run = 0
			}
			run = run*10 + int64(c-'0')
			if run > 1<<40 {
				return nil, fmt.Errorf("rle: run length too large")
			}
		case c == 'b' || c == 'B' || c == '.':
			x += max(run, 1)
			run = -1
		case c == 'o' || c == 'O':
			n := max(run, 1)
			if n > 50_000_000 || int64(len(p.Cells))+n > 100_000_000 {
				return nil, fmt.Errorf("rle: pattern has too many cells")
			}
			for k := int64(0); k < n; k++ {
				p.Cells = append(p.Cells, Point{x + k, y})
			}
			x += n
			run = -1
		case c == '$':
			y += max(run, 1)
			x = 0
			run = -1
		case c == '!':
			terminated = true
			break loop
		case c == ' ' || c == '\t' || c == '\r' || c == '\n':
		default:
			return nil, fmt.Errorf("rle: unexpected character %q (only two-state patterns are supported)", string(c))
		}
	}
	if !terminated {
		return nil, fmt.Errorf("rle: missing terminating '!'")
	}
	return p, nil
}

// ParseCells parses the plaintext ".cells" format.
func ParseCells(text string) (*Pattern, error) {
	p := &Pattern{}
	var y int64
	for _, raw := range strings.Split(text, "\n") {
		ln := strings.TrimRight(raw, "\r \t")
		if strings.HasPrefix(ln, "!") {
			c := strings.TrimSpace(ln[1:])
			if strings.HasPrefix(c, "Name:") {
				p.Name = strings.TrimSpace(c[5:])
			} else if c != "" {
				p.Comments = append(p.Comments, c)
			}
			continue
		}
		for x, c := range ln {
			switch c {
			case 'O', '*', 'o':
				p.Cells = append(p.Cells, Point{int64(x), y})
			case '.', ' ':
			default:
				return nil, fmt.Errorf("cells: unexpected character %q on row %d", string(c), y)
			}
		}
		y++
	}
	return p, nil
}

// EncodeRLE writes cells as RLE with the given rule, wrapped at 70 columns.
func EncodeRLE(pts []Point, rule Rule, name string) string {
	var sb strings.Builder
	if name != "" {
		sb.WriteString("#N " + name + "\n")
	}
	if len(pts) == 0 {
		fmt.Fprintf(&sb, "x = 0, y = 0, rule = %s\n!\n", rule)
		return sb.String()
	}
	pts = append([]Point(nil), pts...)
	sort.Slice(pts, func(i, j int) bool {
		if pts[i].Y != pts[j].Y {
			return pts[i].Y < pts[j].Y
		}
		return pts[i].X < pts[j].X
	})
	x0, y0, x1, y1 := boundsOf(pts)
	fmt.Fprintf(&sb, "x = %d, y = %d, rule = %s\n", x1-x0+1, y1-y0+1, rule)
	var data strings.Builder
	emit := func(n int64, c byte) {
		if n <= 0 {
			return
		}
		if n > 1 {
			data.WriteString(strconv.FormatInt(n, 10))
		}
		data.WriteByte(c)
	}
	curY, curX := y0, x0
	pendingRows := int64(0)
	for i := 0; i < len(pts); {
		p := pts[i]
		if p.Y != curY {
			pendingRows += p.Y - curY
			curY, curX = p.Y, x0
		}
		if pendingRows > 0 {
			emit(pendingRows, '$')
			pendingRows = 0
		}
		emit(p.X-curX, 'b')
		j := i
		for j+1 < len(pts) && pts[j+1].Y == p.Y && pts[j+1].X == pts[j].X+1 {
			j++
		}
		emit(int64(j-i+1), 'o')
		curX = pts[j].X + 1
		i = j + 1
	}
	data.WriteByte('!')
	s := data.String()
	for len(s) > 70 {
		cut := 70
		// do not split a number from its tag
		for cut > 0 && s[cut-1] >= '0' && s[cut-1] <= '9' {
			cut--
		}
		sb.WriteString(s[:cut] + "\n")
		s = s[cut:]
	}
	sb.WriteString(s + "\n")
	return sb.String()
}

// EncodeCells writes the plaintext format.
func EncodeCells(pts []Point, name string) string {
	var sb strings.Builder
	if name != "" {
		sb.WriteString("!Name: " + name + "\n")
	}
	if len(pts) == 0 {
		return sb.String()
	}
	x0, y0, x1, y1 := boundsOf(pts)
	grid := make([][]byte, y1-y0+1)
	for i := range grid {
		grid[i] = []byte(strings.Repeat(".", int(x1-x0+1)))
	}
	for _, p := range pts {
		grid[p.Y-y0][p.X-x0] = 'O'
	}
	for _, r := range grid {
		sb.Write(r)
		sb.WriteByte('\n')
	}
	return sb.String()
}

// ---------------------------------------------------------------- Macrocell

// WriteMacrocell serialises the quadtree (Golly's MC format): each distinct
// subtree is written once, so huge sparse/regular patterns stay tiny.
func (s *Sim) WriteMacrocell() string {
	var sb strings.Builder
	sb.WriteString("[M2] (gosper)\n#R " + s.U.Rule.String() + "\n")
	fmt.Fprintf(&sb, "#G %d\n", s.Gen)
	idx := map[*Node]int{}
	next := 0
	var emit func(n *Node) int
	emit = func(n *Node) int {
		if n.pop == 0 {
			return 0
		}
		if i, ok := idx[n]; ok {
			return i
		}
		if n.level == 3 {
			var rows []string
			for r := 0; r < 8; r++ {
				var row strings.Builder
				for c := 0; c < 8; c++ {
					if cellAt(n, c, r) {
						row.WriteByte('*')
					} else {
						row.WriteByte('.')
					}
				}
				rows = append(rows, strings.TrimRight(row.String(), "."))
			}
			sb.WriteString(strings.Join(rows, "$") + "$\n")
		} else {
			a, b, c, d := emit(n.nw), emit(n.ne), emit(n.sw), emit(n.se)
			fmt.Fprintf(&sb, "%d %d %d %d %d\n", n.level, a, b, c, d)
		}
		next++
		idx[n] = next
		return next
	}
	emit(s.Root)
	return sb.String()
}

func cellAt(n *Node, x, y int) bool {
	for n.level > 0 {
		h := 1 << uint(n.level-1)
		switch {
		case x < h && y < h:
			n = n.nw
		case x >= h && y < h:
			n, x = n.ne, x-h
		case x < h:
			n, y = n.sw, y-h
		default:
			n, x, y = n.se, x-h, y-h
		}
	}
	return n.pop == 1
}

// LoadMacrocell reads an MC file into a fresh Sim. The rule is taken from the
// file unless it has none, in which case def is used.
func LoadMacrocell(text string, def Rule) (*Sim, error) {
	rule := def
	var gen uint64
	var lines []string
	for _, raw := range strings.Split(text, "\n") {
		ln := strings.TrimSpace(raw)
		if ln == "" || strings.HasPrefix(ln, "[") {
			continue
		}
		if ln[0] == '#' {
			switch {
			case strings.HasPrefix(ln, "#R"):
				r, err := ParseRule(strings.TrimSpace(ln[2:]))
				if err != nil {
					return nil, err
				}
				rule = r
			case strings.HasPrefix(ln, "#G"):
				g, err := strconv.ParseUint(strings.TrimSpace(ln[2:]), 10, 64)
				if err != nil {
					return nil, fmt.Errorf("macrocell: bad #G line")
				}
				gen = g
			}
			continue
		}
		lines = append(lines, ln)
	}
	if len(lines) == 0 {
		return nil, fmt.Errorf("macrocell: no nodes")
	}
	s := NewSim(rule)
	u := s.U
	nodes := make([]*Node, 1, len(lines)+1) // index 0 = empty (level-dependent)
	get := func(i, level int) (*Node, error) {
		if i == 0 {
			return u.Empty(level), nil
		}
		if i < 0 || i >= len(nodes) {
			return nil, fmt.Errorf("macrocell: node reference %d out of range", i)
		}
		if nodes[i].level != level {
			return nil, fmt.Errorf("macrocell: node %d has level %d, expected %d", i, nodes[i].level, level)
		}
		return nodes[i], nil
	}
	for _, ln := range lines {
		if ln[0] >= '0' && ln[0] <= '9' {
			f := strings.Fields(ln)
			if len(f) != 5 {
				return nil, fmt.Errorf("macrocell: bad node line %q", ln)
			}
			v := make([]int, 5)
			for i := range f {
				n, err := strconv.Atoi(f[i])
				if err != nil {
					return nil, fmt.Errorf("macrocell: bad number in %q", ln)
				}
				v[i] = n
			}
			lv := v[0]
			if lv < 4 || lv > MaxLevel-6 {
				return nil, fmt.Errorf("macrocell: bad node level %d", lv)
			}
			var ch [4]*Node
			for i := 0; i < 4; i++ {
				c, err := get(v[i+1], lv-1)
				if err != nil {
					return nil, err
				}
				ch[i] = c
			}
			nodes = append(nodes, u.join(ch[0], ch[1], ch[2], ch[3]))
			continue
		}
		var pts []Point
		x, y := int64(0), int64(0)
		for _, c := range ln {
			switch c {
			case '.':
				x++
			case '*':
				pts = append(pts, Point{x, y})
				x++
			case '$':
				x, y = 0, y+1
			default:
				return nil, fmt.Errorf("macrocell: bad leaf character %q", string(c))
			}
			if x > 8 || y > 8 {
				return nil, fmt.Errorf("macrocell: leaf larger than 8x8")
			}
		}
		nodes = append(nodes, u.build(pts, 3, 0, 0))
	}
	s.Root = nodes[len(nodes)-1]
	if s.Root.level < 3 {
		s.Root = u.Empty(3)
	}
	s.Gen = gen
	return s, nil
}
