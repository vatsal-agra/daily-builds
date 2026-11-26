package main

import "strings"

// Leduc Hold'em: deck J,J,Q,Q,K,K. Each player antes 1 and gets one private card.
// Round 1: bet size 2; a public board card is dealt; round 2: bet size 4.
// At most two raises per round. Showdown: pairing the board beats everything, else high card.
type Leduc struct{}

func (Leduc) Name() string { return "leduc" }
func (Leduc) Root() Node {
	return leducNode{board: -1, hole: [2]int{-1, -1}, fold: -1, contrib: [2]int{1, 1}}
}

var leducRanks = [3]string{"J", "Q", "K"}

type leducNode struct {
	hole    [2]int // card ids 0..5, rank = id/2
	board   int    // card id or -1
	round   int
	player  int
	raises  int
	acts    int
	contrib [2]int
	hist    string
	fold    int // -1 none, else folder
	stage   int // 0 = deal hole, 1 = betting, 2 = deal board, 3 = showdown/terminal
}

func newLeducBetting(n leducNode) leducNode {
	n.stage = 1
	n.player, n.raises, n.acts = 0, 0, 0
	return n
}

func (n leducNode) Terminal() bool { return n.stage == 3 }

func (n leducNode) Player() int {
	if n.stage == 0 || n.stage == 2 {
		return -1
	}
	return n.player
}

func (n leducNode) facing() bool { return n.contrib[0] != n.contrib[1] }

func (n leducNode) Actions() []string {
	switch n.stage {
	case 0:
		var out []string
		for a := 0; a < 6; a++ {
			for b := 0; b < 6; b++ {
				if a != b {
					out = append(out, leducRanks[a/2]+"|"+leducRanks[b/2])
				}
			}
		}
		return out
	case 2:
		var out []string
		for c := 0; c < 6; c++ {
			if c != n.hole[0] && c != n.hole[1] {
				out = append(out, leducRanks[c/2])
			}
		}
		return out
	}
	if n.facing() {
		if n.raises < 2 {
			return []string{"fold", "call", "raise"}
		}
		return []string{"fold", "call"}
	}
	return []string{"check", "bet"}
}

func (n leducNode) ChanceProb(int) float64 {
	if n.stage == 0 {
		return 1.0 / 30
	}
	return 1.0 / 4
}

func (n leducNode) betSize() int {
	if n.round == 0 {
		return 2
	}
	return 4
}

func (n leducNode) Child(i int) Node {
	switch n.stage {
	case 0:
		k := 0
		for a := 0; a < 6; a++ {
			for b := 0; b < 6; b++ {
				if a != b {
					if k == i {
						n.hole = [2]int{a, b}
						return newLeducBetting(n)
					}
					k++
				}
			}
		}
	case 2:
		k := 0
		for c := 0; c < 6; c++ {
			if c != n.hole[0] && c != n.hole[1] {
				if k == i {
					n.board = c
					n.round = 1
					n.hist += "/"
					return newLeducBetting(n)
				}
				k++
			}
		}
	}
	acts := n.Actions()
	name := acts[i]
	p := n.player
	n.acts++
	switch name {
	case "fold":
		n.hist += "f"
		n.fold = p
		n.stage = 3
		return n
	case "check":
		n.hist += "c"
		if n.acts >= 2 {
			return n.endRound()
		}
	case "call":
		n.hist += "c"
		n.contrib[p] = n.contrib[1-p]
		return n.endRound()
	case "bet", "raise":
		n.hist += "r"
		n.contrib[p] = n.contrib[1-p] + n.betSize()
		n.raises++
	}
	n.player = 1 - p
	return n
}

func (n leducNode) endRound() leducNode {
	if n.round == 0 {
		n.stage = 2
	} else {
		n.stage = 3
		n.fold = -1
	}
	return n
}

func (n leducNode) Utility() float64 {
	if n.fold == 0 {
		return -float64(n.contrib[0])
	}
	if n.fold == 1 {
		return float64(n.contrib[1])
	}
	br := n.board / 2
	s := [2]int{}
	for p := 0; p < 2; p++ {
		r := n.hole[p] / 2
		s[p] = r
		if r == br {
			s[p] = 10
		}
	}
	switch {
	case s[0] > s[1]:
		return float64(n.contrib[1])
	case s[0] < s[1]:
		return -float64(n.contrib[0])
	}
	return 0
}

func (n leducNode) InfoSet() string {
	p := n.player
	var sb strings.Builder
	sb.WriteByte(byte('0' + p))
	sb.WriteString(leducRanks[n.hole[p]/2])
	sb.WriteByte('|')
	if n.board >= 0 {
		sb.WriteString(leducRanks[n.board/2])
	} else {
		sb.WriteByte('-')
	}
	sb.WriteByte(':')
	sb.WriteString(n.hist)
	return sb.String()
}
