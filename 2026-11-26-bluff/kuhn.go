package main

// Kuhn poker: 3 cards (J<Q<K), 1 ante each, one bet of 1, one betting round.
type Kuhn struct{}

func (Kuhn) Name() string { return "kuhn" }
func (Kuhn) Root() Node   { return kuhnNode{c: [2]int{-1, -1}} }

var kuhnCards = [3]string{"J", "Q", "K"}

type kuhnNode struct {
	c    [2]int
	hist string // p = pass(check/fold), b = bet(bet/call)
}

func (n kuhnNode) dealt() bool { return n.c[0] >= 0 }

func (n kuhnNode) Terminal() bool {
	if !n.dealt() {
		return false
	}
	switch n.hist {
	case "pp", "bp", "bb", "pbp", "pbb":
		return true
	}
	return false
}

func (n kuhnNode) Utility() float64 {
	hi := 1.0
	if n.c[1] > n.c[0] {
		hi = -1
	}
	switch n.hist {
	case "pp":
		return hi
	case "bp":
		return 1
	case "pbp":
		return -1
	default: // bb, pbb
		return 2 * hi
	}
}

func (n kuhnNode) Player() int {
	if !n.dealt() {
		return -1
	}
	return len(n.hist) % 2
}

func (n kuhnNode) Actions() []string {
	if !n.dealt() {
		return []string{"J|Q", "J|K", "Q|J", "Q|K", "K|J", "K|Q"}
	}
	if len(n.hist) > 0 && n.hist[len(n.hist)-1] == 'b' {
		return []string{"fold", "call"}
	}
	return []string{"check", "bet"}
}

var kuhnDeals = [6][2]int{{0, 1}, {0, 2}, {1, 0}, {1, 2}, {2, 0}, {2, 1}}

func (n kuhnNode) Child(i int) Node {
	if !n.dealt() {
		return kuhnNode{c: kuhnDeals[i]}
	}
	n.hist += string("pb"[i])
	return n
}

func (n kuhnNode) ChanceProb(int) float64 { return 1.0 / 6 }

func (n kuhnNode) InfoSet() string {
	p := n.Player()
	return string(rune('0'+p)) + kuhnCards[n.c[p]] + ":" + n.hist
}
