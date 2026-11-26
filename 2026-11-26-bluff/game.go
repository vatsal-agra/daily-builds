package main

import "fmt"

// Node is one state of a two-player zero-sum extensive-form game with chance.
// Utilities are always from player 0's point of view.
type Node interface {
	Terminal() bool
	Utility() float64 // player 0's payoff (terminal only)
	Player() int      // 0, 1, or -1 for chance
	Actions() []string
	Child(i int) Node
	ChanceProb(i int) float64 // chance nodes only
	InfoSet() string          // key of the acting player's information set
}

// Game creates the root node of a game.
type Game interface {
	Name() string
	Root() Node
}

// TNode is a node of the compiled game tree.
type TNode struct {
	Player int // -1 chance, 0, 1; terminals use Terminal=true
	Term   bool
	Util   float64 // player 0 payoff at terminals
	Kids   []int
	Prob   []float64 // chance probabilities
	IS     int       // info-set index for player nodes
}

// ISet is one information set.
type ISet struct {
	Key     string
	Player  int
	Actions []string
	Depth   int // number of this player's decisions on the way here
	Nodes   []int
}

// Tree is a fully expanded game tree with indexed information sets. Compiling once makes
// solving and best-response computation simple array walks.
type Tree struct {
	Game  string
	Nodes []TNode
	Sets  []ISet
	byKey map[string]int
}

// Compile expands a game into a Tree and validates perfect recall/consistency.
func Compile(g Game) (*Tree, error) {
	t := &Tree{Game: g.Name(), byKey: map[string]int{}}
	var walk func(n Node, depth [2]int) (int, error)
	walk = func(n Node, depth [2]int) (int, error) {
		id := len(t.Nodes)
		t.Nodes = append(t.Nodes, TNode{})
		if n.Terminal() {
			t.Nodes[id] = TNode{Player: -2, Term: true, Util: n.Utility()}
			return id, nil
		}
		acts := n.Actions()
		if len(acts) == 0 {
			return 0, fmt.Errorf("non-terminal node with no actions")
		}
		p := n.Player()
		tn := TNode{Player: p, Kids: make([]int, len(acts))}
		if p == -1 {
			tn.Prob = make([]float64, len(acts))
			sum := 0.0
			for i := range acts {
				tn.Prob[i] = n.ChanceProb(i)
				sum += tn.Prob[i]
			}
			if sum < 0.999999 || sum > 1.000001 {
				return 0, fmt.Errorf("chance probabilities sum to %v", sum)
			}
		} else {
			key := n.InfoSet()
			si, ok := t.byKey[key]
			if !ok {
				si = len(t.Sets)
				t.byKey[key] = si
				t.Sets = append(t.Sets, ISet{Key: key, Player: p, Actions: acts, Depth: depth[p]})
			} else {
				s := t.Sets[si]
				if s.Player != p || len(s.Actions) != len(acts) || s.Depth != depth[p] {
					return 0, fmt.Errorf("inconsistent info set %q", key)
				}
			}
			t.Sets[si].Nodes = append(t.Sets[si].Nodes, id)
			tn.IS = si
		}
		t.Nodes[id] = tn
		for i := range acts {
			d := depth
			if p >= 0 {
				d[p]++
			}
			c, err := walk(n.Child(i), d)
			if err != nil {
				return 0, err
			}
			t.Nodes[id].Kids[i] = c
		}
		return id, nil
	}
	if _, err := walk(g.Root(), [2]int{}); err != nil {
		return nil, err
	}
	return t, nil
}

// SetIndex returns the index of an information set by key.
func (t *Tree) SetIndex(key string) (int, bool) { i, ok := t.byKey[key]; return i, ok }

// Profile holds one probability vector per information set (indexed like Tree.Sets).
type Profile [][]float64

// Uniform returns the uniform-random profile.
func (t *Tree) Uniform() Profile {
	p := make(Profile, len(t.Sets))
	for i, s := range t.Sets {
		p[i] = make([]float64, len(s.Actions))
		for a := range p[i] {
			p[i][a] = 1 / float64(len(s.Actions))
		}
	}
	return p
}
