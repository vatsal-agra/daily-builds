// Package expr implements the expression tree used as the genome of the
// symbolic-regression search: evaluation, printing, parsing, simplification
// and differentiation.
package expr

import (
	"math"
	"strconv"
	"strings"
)

// Kind of a node.
type Kind int

const (
	Const Kind = iota
	Var
	Un
	Bin
)

// Op names. Unary: neg sin cos exp log sqrt abs. Binary: + - * / ^
type Node struct {
	Kind Kind
	Val  float64 // Const
	Idx  int     // Var index
	Op   string  // Un / Bin
	L, R *Node
}

func C(v float64) *Node          { return &Node{Kind: Const, Val: v} }
func V(i int) *Node              { return &Node{Kind: Var, Idx: i} }
func U(op string, a *Node) *Node { return &Node{Kind: Un, Op: op, L: a} }
func B(op string, a, b *Node) *Node {
	return &Node{Kind: Bin, Op: op, L: a, R: b}
}

var UnaryOps = []string{"neg", "sin", "cos", "exp", "log", "sqrt", "abs"}
var BinaryOps = []string{"+", "-", "*", "/", "^"}

// Clone deep-copies a tree.
func (n *Node) Clone() *Node {
	if n == nil {
		return nil
	}
	c := *n
	c.L = n.L.Clone()
	c.R = n.R.Clone()
	return &c
}

// Size is the node count.
func (n *Node) Size() int {
	if n == nil {
		return 0
	}
	return 1 + n.L.Size() + n.R.Size()
}

// Depth of the tree (leaf = 1).
func (n *Node) Depth() int {
	if n == nil {
		return 0
	}
	l, r := n.L.Depth(), n.R.Depth()
	if r > l {
		l = r
	}
	return 1 + l
}

// Complexity weights operators by how "expensive" they are to read.
func (n *Node) Complexity() int {
	if n == nil {
		return 0
	}
	w := 1
	if n.Kind == Un {
		switch n.Op {
		case "neg", "abs":
			w = 1
		default:
			w = 3
		}
	} else if n.Kind == Bin {
		switch n.Op {
		case "+", "-":
			w = 1
		case "*":
			w = 2
		default:
			w = 3
		}
	}
	return w + n.L.Complexity() + n.R.Complexity()
}

// Nodes returns pointers to every node (pre-order) for mutation/crossover.
func (n *Node) Nodes() []*Node {
	var out []*Node
	var walk func(*Node)
	walk = func(x *Node) {
		if x == nil {
			return
		}
		out = append(out, x)
		walk(x.L)
		walk(x.R)
	}
	walk(n)
	return out
}

// Consts returns pointers to all constant leaves.
func (n *Node) Consts() []*Node {
	var out []*Node
	for _, x := range n.Nodes() {
		if x.Kind == Const {
			out = append(out, x)
		}
	}
	return out
}

// Eval evaluates with protected operators; the result may be NaN/Inf only if
// the inputs are; callers treat non-finite as invalid.
func (n *Node) Eval(x []float64) float64 {
	switch n.Kind {
	case Const:
		return n.Val
	case Var:
		if n.Idx < len(x) {
			return x[n.Idx]
		}
		return math.NaN()
	case Un:
		a := n.L.Eval(x)
		switch n.Op {
		case "neg":
			return -a
		case "sin":
			return math.Sin(a)
		case "cos":
			return math.Cos(a)
		case "exp":
			if a > 50 {
				return math.NaN()
			}
			return math.Exp(a)
		case "log":
			if a <= 0 {
				return math.NaN()
			}
			return math.Log(a)
		case "sqrt":
			if a < 0 {
				return math.NaN()
			}
			return math.Sqrt(a)
		case "abs":
			return math.Abs(a)
		}
	case Bin:
		a, b := n.L.Eval(x), n.R.Eval(x)
		switch n.Op {
		case "+":
			return a + b
		case "-":
			return a - b
		case "*":
			return a * b
		case "/":
			if b == 0 {
				return math.NaN()
			}
			return a / b
		case "^":
			if a < 0 && b != math.Trunc(b) {
				return math.NaN()
			}
			if a == 0 && b < 0 {
				return math.NaN()
			}
			r := math.Pow(a, b)
			return r
		}
	}
	return math.NaN()
}

// String prints with minimal parentheses. varNames may be nil (x0, x1...).
func (n *Node) String() string { return n.Format(nil) }

func prec(n *Node) int {
	switch n.Kind {
	case Bin:
		switch n.Op {
		case "+", "-":
			return 1
		case "*", "/":
			return 2
		case "^":
			return 4
		}
	case Un:
		if n.Op == "neg" {
			return 3
		}
		return 6
	case Const:
		if n.Val < 0 {
			return 3
		}
	}
	return 6
}

func fmtConst(v float64) string {
	if v == math.Pi {
		return "pi"
	}
	if v == math.E {
		return "e"
	}
	return strconv.FormatFloat(v, 'g', 6, 64)
}

// Format prints using the given variable names.
func (n *Node) Format(names []string) string {
	var sb strings.Builder
	n.write(&sb, names, 0)
	return sb.String()
}

func (n *Node) write(sb *strings.Builder, names []string, parent int) {
	p := prec(n)
	paren := p < parent
	if paren {
		sb.WriteByte('(')
	}
	switch n.Kind {
	case Const:
		sb.WriteString(fmtConst(n.Val))
	case Var:
		if n.Idx < len(names) {
			sb.WriteString(names[n.Idx])
		} else {
			sb.WriteString("x" + strconv.Itoa(n.Idx))
		}
	case Un:
		if n.Op == "neg" {
			sb.WriteByte('-')
			n.L.write(sb, names, 4)
		} else {
			sb.WriteString(n.Op + "(")
			n.L.write(sb, names, 0)
			sb.WriteByte(')')
		}
	case Bin:
		switch n.Op {
		case "+", "-":
			n.L.write(sb, names, 1)
			sb.WriteString(" " + n.Op + " ")
			n.R.write(sb, names, 2)
		case "*", "/":
			n.L.write(sb, names, 2)
			sb.WriteString(" " + n.Op + " ")
			n.R.write(sb, names, 3)
		case "^":
			n.L.write(sb, names, 5)
			sb.WriteString("^")
			n.R.write(sb, names, 4)
		}
	}
	if paren {
		sb.WriteByte(')')
	}
}

// Equal is structural equality.
func (n *Node) Equal(o *Node) bool {
	if n == nil || o == nil {
		return n == o
	}
	if n.Kind != o.Kind || n.Op != o.Op || n.Idx != o.Idx || n.Val != o.Val {
		return false
	}
	return n.L.Equal(o.L) && n.R.Equal(o.R)
}
