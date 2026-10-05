package expr

import "fmt"

// Diff returns the symbolic derivative of n with respect to variable idx,
// simplified.
func Diff(n *Node, idx int) (*Node, error) {
	d, err := diff(n, idx)
	if err != nil {
		return nil, err
	}
	return Simplify(d), nil
}

func diff(n *Node, v int) (*Node, error) {
	switch n.Kind {
	case Const:
		return C(0), nil
	case Var:
		if n.Idx == v {
			return C(1), nil
		}
		return C(0), nil
	case Un:
		a := n.L
		da, err := diff(a, v)
		if err != nil {
			return nil, err
		}
		switch n.Op {
		case "neg":
			return U("neg", da), nil
		case "sin":
			return B("*", U("cos", a.Clone()), da), nil
		case "cos":
			return U("neg", B("*", U("sin", a.Clone()), da)), nil
		case "exp":
			return B("*", n.Clone(), da), nil
		case "log":
			return B("/", da, a.Clone()), nil
		case "sqrt":
			return B("/", da, B("*", C(2), n.Clone())), nil
		case "abs":
			return B("*", B("/", a.Clone(), n.Clone()), da), nil
		}
	case Bin:
		a, b := n.L, n.R
		da, err := diff(a, v)
		if err != nil {
			return nil, err
		}
		db, err := diff(b, v)
		if err != nil {
			return nil, err
		}
		switch n.Op {
		case "+":
			return B("+", da, db), nil
		case "-":
			return B("-", da, db), nil
		case "*":
			return B("+", B("*", da, b.Clone()), B("*", a.Clone(), db)), nil
		case "/":
			return B("/", B("-", B("*", da, b.Clone()), B("*", a.Clone(), db)), B("^", b.Clone(), C(2))), nil
		case "^":
			if b.Kind == Const { // power rule
				return B("*", B("*", C(b.Val), B("^", a.Clone(), C(b.Val-1))), da), nil
			}
			// d(a^b) = a^b * (db*log(a) + b*da/a)
			return B("*", n.Clone(), B("+", B("*", db, U("log", a.Clone())), B("/", B("*", b.Clone(), da), a.Clone()))), nil
		}
	}
	return nil, fmt.Errorf("cannot differentiate %v", n)
}
