package cube

import (
	"fmt"
	"strings"
)

// Cycle is one cycle of pieces of a permutation, with the net orientation change.
type Cycle struct {
	Pieces []string
	Twist  int // net twist (corners, mod 3) or flip (edges, mod 2) accumulated around the cycle
}

// Order is the number of repetitions of a cycle needed to return to the start.
func (c Cycle) order(mod int) int {
	n := len(c.Pieces)
	if c.Twist%mod != 0 {
		n *= mod
	}
	return n
}

// Analysis summarises what an algorithm does to the cube.
type Analysis struct {
	Moves       []Move
	Order       int // repetitions until the cube is solved again (brute-force)
	OrderCycles int // same number computed from cycle structure (cross-check)
	Corners     []Cycle
	Edges       []Cycle
	Parity      string // "even" or "odd" permutation
	Moved       int    // pieces not in their solved place/orientation
	Inverse     []Move
}

func gcd(a, b int) int {
	for b != 0 {
		a, b = b, a%b
	}
	return a
}

func lcm(a, b int) int { return a / gcd(a, b) * b }

// Analyze studies an algorithm applied to a solved cube.
func Analyze(ms []Move) Analysis {
	c := FromMoves(ms)
	a := Analysis{Moves: ms, Inverse: InvertSeq(ms)}
	// brute-force order (the group's exponent is 1260, so this always terminates)
	p := c
	a.Order = 1
	for !p.IsSolved() {
		p = p.Mul(c)
		a.Order++
	}
	// cycles
	seen := [8]bool{}
	for i := 0; i < 8; i++ {
		if seen[i] || (c.CP[i] == uint8(i) && c.CO[i] == 0) {
			seen[i] = true
			continue
		}
		var cy Cycle
		for j := i; !seen[j]; j = int(c.CP[j]) {
			seen[j] = true
			cy.Pieces = append(cy.Pieces, posCornerNames[j])
			cy.Twist += int(c.CO[j])
		}
		a.Corners = append(a.Corners, cy)
	}
	seenE := [12]bool{}
	for i := 0; i < 12; i++ {
		if seenE[i] || (c.EP[i] == uint8(i) && c.EO[i] == 0) {
			seenE[i] = true
			continue
		}
		var cy Cycle
		for j := i; !seenE[j]; j = int(c.EP[j]) {
			seenE[j] = true
			cy.Pieces = append(cy.Pieces, posEdgeNames[j])
			cy.Twist += int(c.EO[j])
		}
		a.Edges = append(a.Edges, cy)
	}
	a.OrderCycles = 1
	for _, cy := range a.Corners {
		a.OrderCycles = lcm(a.OrderCycles, cy.order(3))
	}
	for _, cy := range a.Edges {
		a.OrderCycles = lcm(a.OrderCycles, cy.order(2))
	}
	if parity(c.CP[:]) == 0 {
		a.Parity = "even"
	} else {
		a.Parity = "odd"
	}
	for i := 0; i < 8; i++ {
		if c.CP[i] != uint8(i) || c.CO[i] != 0 {
			a.Moved++
		}
	}
	for i := 0; i < 12; i++ {
		if c.EP[i] != uint8(i) || c.EO[i] != 0 {
			a.Moved++
		}
	}
	return a
}

func (a Analysis) String() string {
	var b strings.Builder
	fmt.Fprintf(&b, "algorithm      %s\n", FormatMoves(a.Moves))
	fmt.Fprintf(&b, "inverse        %s\n", FormatMoves(a.Inverse))
	fmt.Fprintf(&b, "order          %d  (repeat the algorithm %d times to restore the cube)\n", a.Order, a.Order)
	fmt.Fprintf(&b, "permutation    %s\n", a.Parity)
	fmt.Fprintf(&b, "pieces changed %d of 20\n", a.Moved)
	writeCycles := func(name string, cs []Cycle, mod int, what string) {
		if len(cs) == 0 {
			fmt.Fprintf(&b, "%s: none\n", name)
			return
		}
		fmt.Fprintf(&b, "%s:\n", name)
		for _, cy := range cs {
			desc := "pure cycle"
			if len(cy.Pieces) == 1 {
				desc = "in place"
			}
			if cy.Twist%mod != 0 {
				desc += fmt.Sprintf(", net %s %d", what, cy.Twist%mod)
			}
			fmt.Fprintf(&b, "  (%s)  %s\n", strings.Join(cy.Pieces, " "), desc)
		}
	}
	writeCycles("corners", a.Corners, 3, "twist")
	writeCycles("edges  ", a.Edges, 2, "flip")
	return b.String()
}
