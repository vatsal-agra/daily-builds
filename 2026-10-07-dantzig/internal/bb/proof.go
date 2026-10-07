// Package bb implements branch & bound with a checkable proof tree.
package bb

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"strconv"

	"dantzig/internal/exact"
	"dantzig/internal/model"
)

// PNode is a node of the proof tree: either a branching split or a leaf.
type PNode struct {
	Var   *int     `json:"var,omitempty"`   // branching variable
	Split string   `json:"split,omitempty"` // integer s: down = x<=s, up = x>=s+1
	Down  *PNode   `json:"down,omitempty"`
	Up    *PNode   `json:"up,omitempty"`
	Leaf  string   `json:"leaf,omitempty"` // bound | farkas | open | uncertified
	Y     []string `json:"y,omitempty"`    // row multipliers certifying the leaf
	LP    *float64 `json:"lp,omitempty"`   // float LP objective (display only)
	Inc   bool     `json:"inc,omitempty"`  // this leaf produced the final incumbent (display only)
}

// FlatNode is the serialised form of a proof-tree node. Children are indices
// into Proof.Nodes (always greater than the parent's index; the root is 0), so
// arbitrarily deep trees never recurse in the encoder, decoder or checker.
type FlatNode struct {
	Var   *int     `json:"var,omitempty"`
	Split string   `json:"split,omitempty"`
	Down  int      `json:"down,omitempty"`
	Up    int      `json:"up,omitempty"`
	Leaf  string   `json:"leaf,omitempty"`
	Y     []string `json:"y,omitempty"`
	LP    *float64 `json:"lp,omitempty"`
	Inc   bool     `json:"inc,omitempty"`
}

// Proof is the complete certificate of a solve.
type Proof struct {
	Version   int        `json:"version"`
	ModelHash string     `json:"model_sha256"`
	Status    string     `json:"status"` // optimal | infeasible | unbounded | unbounded_relaxation | limit
	Objective string     `json:"objective,omitempty"`
	X         []string   `json:"x"` // null when no solution is claimed
	Ray       []string   `json:"ray,omitempty"`
	Nodes     []FlatNode `json:"nodes,omitempty"`
	Tree      *PNode     `json:"-"` // builder form, flattened by Seal
}

// Seal flattens the builder tree into Nodes (iteratively).
func (p *Proof) Seal() {
	p.Nodes = nil
	if p.Tree == nil {
		return
	}
	type item struct {
		n      *PNode
		parent int
		isUp   bool
	}
	stack := []item{{p.Tree, -1, false}}
	for len(stack) > 0 {
		it := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		idx := len(p.Nodes)
		p.Nodes = append(p.Nodes, FlatNode{Var: it.n.Var, Split: it.n.Split, Leaf: it.n.Leaf, Y: it.n.Y, LP: it.n.LP, Inc: it.n.Inc})
		if it.parent >= 0 {
			if it.isUp {
				p.Nodes[it.parent].Up = idx
			} else {
				p.Nodes[it.parent].Down = idx
			}
		}
		if it.n.Var != nil {
			stack = append(stack, item{it.n.Up, idx, true}, item{it.n.Down, idx, false})
		}
	}
}

// HashModel fingerprints the canonical text of a model.
func HashModel(m *model.Model) string {
	h := sha256.Sum256([]byte(model.Format(m)))
	return hex.EncodeToString(h[:])
}

func ratStrs(v []*big.Rat) []string {
	if v == nil {
		return nil
	}
	o := make([]string, len(v)) // non-nil even when empty
	for i, r := range v {
		o[i] = r.RatString()
	}
	return o
}

func parseRats(s []string) ([]*big.Rat, error) {
	o := make([]*big.Rat, len(s))
	for i, t := range s {
		r, ok := new(big.Rat).SetString(t)
		if !ok {
			return nil, fmt.Errorf("bad rational %q", t)
		}
		o[i] = r
	}
	return o, nil
}

// MarshalProof encodes a proof as indented JSON.
func MarshalProof(p *Proof) ([]byte, error) { return json.MarshalIndent(p, "", " ") }

// CheckReport is what the independent checker established.
type CheckReport struct {
	Status         string
	Objective      *big.Rat // original sense, includes constant (nil if none)
	Leaves         int
	BoundLeaves    int
	FarkasLeaves   int
	OpenLeaves     int
	Uncertified    int
	Nodes          int
	GlobalBound    *big.Rat // proven bound (original sense) if all leaves carry a certificate
	Complete       bool
	IncumbentExact bool
}

func ceilRat(r *big.Rat) *big.Rat {
	q := new(big.Int).Div(r.Num(), r.Denom()) // floor for positive denominators (Euclidean)
	if !r.IsInt() {
		q.Add(q, big.NewInt(1))
	}
	return new(big.Rat).SetInt(q)
}

func floorRat(r *big.Rat) *big.Rat {
	q := new(big.Int).Div(r.Num(), r.Denom())
	return new(big.Rat).SetInt(q)
}

// Check independently re-verifies a proof against the model using only exact
// arithmetic. It returns an error if any claim fails.
func Check(m *model.Model, p *Proof) (*CheckReport, error) {
	if p.Version != 1 {
		return nil, fmt.Errorf("unsupported proof version %d", p.Version)
	}
	if p.ModelHash != HashModel(m) {
		return nil, fmt.Errorf("proof was produced for a different model (hash mismatch)")
	}
	rep := &CheckReport{Status: p.Status}
	cost := m.MinCost()
	box0 := exact.BoxOf(m)
	sign := big.NewRat(1, 1)
	if m.Maximize {
		sign = big.NewRat(-1, 1)
	}
	toOrig := func(v *big.Rat) *big.Rat { // internal min value -> original objective
		o := new(big.Rat).Mul(v, sign)
		return o.Add(o, m.ObjConst)
	}
	switch p.Status {
	case "unbounded":
		x0, err := parseRats(p.X)
		if err != nil {
			return nil, err
		}
		ray, err := parseRats(p.Ray)
		if err != nil {
			return nil, err
		}
		if len(x0) != len(m.Vars) || len(ray) != len(m.Vars) {
			return nil, fmt.Errorf("unbounded certificate has wrong dimension")
		}
		if err := exact.CheckRay(m, cost, x0, ray); err != nil {
			return nil, fmt.Errorf("unbounded certificate rejected: %w", err)
		}
		if m.HasInts() {
			// the base point must be integer-feasible and the ray integral on the
			// integer variables, so x0 + t*ray stays integer-feasible for integer t
			if err := exact.CheckPoint(m, box0, x0, true); err != nil {
				return nil, fmt.Errorf("MIP unbounded certificate: base point: %w", err)
			}
			for j, v := range m.Vars {
				if v.Int && !ray[j].IsInt() {
					return nil, fmt.Errorf("MIP unbounded certificate: ray is fractional on integer variable %s", v.Name)
				}
			}
		}
		rep.Complete = true
		return rep, nil
	case "unbounded_relaxation":
		x0, err := parseRats(p.X)
		if err != nil {
			return nil, err
		}
		ray, err := parseRats(p.Ray)
		if err != nil {
			return nil, err
		}
		if err := exact.CheckRay(m, cost, x0, ray); err != nil {
			return nil, fmt.Errorf("relaxation ray rejected: %w", err)
		}
		rep.Complete = true
		return rep, nil
	case "optimal", "infeasible", "limit":
	default:
		return nil, fmt.Errorf("unknown status %q", p.Status)
	}

	// incumbent
	var incObj *big.Rat
	if p.X != nil {
		x, err := parseRats(p.X)
		if err != nil {
			return nil, err
		}
		if err := exact.CheckPoint(m, box0, x, true); err != nil {
			return nil, fmt.Errorf("incumbent rejected: %w", err)
		}
		incObj = exact.Dot(cost, x)
		rep.IncumbentExact = true
		if p.Objective != "" {
			claim, ok := new(big.Rat).SetString(p.Objective)
			if !ok || claim.Cmp(toOrig(incObj)) != 0 {
				return nil, fmt.Errorf("claimed objective %s != recomputed %s", p.Objective, model.RatStr(toOrig(incObj)))
			}
		}
		rep.Objective = toOrig(incObj)
	} else if p.Status == "optimal" {
		return nil, fmt.Errorf("status optimal without a solution")
	}
	if len(p.Nodes) == 0 {
		return nil, fmt.Errorf("proof has no tree")
	}
	intObj := m.ObjIsIntegral()
	var minBound *big.Rat // min over leaves of proven internal bound
	boundKnown := true
	type frame struct {
		idx int
		box exact.Box
	}
	seen := make([]bool, len(p.Nodes))
	stack := []frame{{0, box0}}
	for len(stack) > 0 {
		f := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		if f.idx < 0 || f.idx >= len(p.Nodes) || seen[f.idx] {
			return nil, fmt.Errorf("malformed proof tree (bad or repeated node index %d)", f.idx)
		}
		seen[f.idx] = true
		n := &p.Nodes[f.idx]
		box := f.box
		rep.Nodes++
		if n.Var != nil {
			j := *n.Var
			if j < 0 || j >= len(m.Vars) || !m.Vars[j].Int {
				return nil, fmt.Errorf("branching on non-integer variable index %d", j)
			}
			s, ok := new(big.Rat).SetString(n.Split)
			if !ok || !s.IsInt() {
				return nil, fmt.Errorf("branch split %q is not an integer", n.Split)
			}
			if n.Down <= f.idx || n.Up <= f.idx {
				return nil, fmt.Errorf("branch node %d has missing or backward child", f.idx)
			}
			down := box.Clone()
			if down.Hi[j] == nil || down.Hi[j].Cmp(s) > 0 {
				down.Hi[j] = s
			}
			up := box.Clone()
			s1 := new(big.Rat).Add(s, big.NewRat(1, 1))
			if up.Lo[j] == nil || up.Lo[j].Cmp(s1) < 0 {
				up.Lo[j] = s1
			}
			stack = append(stack, frame{n.Up, up}, frame{n.Down, down})
			continue
		}
		rep.Leaves++
		switch n.Leaf {
		case "farkas":
			y, err := parseRats(n.Y)
			if err != nil {
				return nil, err
			}
			if box.Empty() {
				rep.FarkasLeaves++
				continue
			}
			if len(y) != len(m.Rows) {
				return nil, fmt.Errorf("Farkas leaf has %d multipliers, model has %d rows", len(y), len(m.Rows))
			}
			if err := exact.CheckFarkas(m, box, y); err != nil {
				return nil, fmt.Errorf("Farkas leaf rejected: %w", err)
			}
			rep.FarkasLeaves++
		case "gcd":
			row, err := strconv.Atoi(n.Split)
			if err != nil {
				return nil, fmt.Errorf("gcd leaf: bad row index %q", n.Split)
			}
			if err := exact.CheckGCDRow(m, row); err != nil {
				return nil, fmt.Errorf("gcd leaf rejected: %w", err)
			}
			rep.FarkasLeaves++
		case "bound":
			y, err := parseRats(n.Y)
			if err != nil {
				return nil, err
			}
			if len(y) != len(m.Rows) {
				return nil, fmt.Errorf("bound leaf has %d multipliers, model has %d rows", len(y), len(m.Rows))
			}
			b, ok := exact.LagrangeBound(m, box, cost, y)
			if !ok {
				return nil, fmt.Errorf("bound leaf multipliers need an infinite bound")
			}
			if minBound == nil || b.Cmp(minBound) < 0 {
				minBound = b
			}
			if p.Status == "limit" {
				rep.BoundLeaves++ // a limit-terminated proof only needs valid bounds
				continue
			}
			if incObj == nil {
				return nil, fmt.Errorf("bound leaf in a proof without incumbent")
			}
			eff := b
			if intObj {
				eff = ceilRat(b)
			}
			if eff.Cmp(incObj) < 0 {
				return nil, fmt.Errorf("bound leaf proves only %s, incumbent is %s (a better solution may exist)",
					model.RatStr(eff), model.RatStr(incObj))
			}
			rep.BoundLeaves++
		case "open":
			rep.OpenLeaves++
			if len(n.Y) == len(m.Rows) {
				y, err := parseRats(n.Y)
				if err != nil {
					return nil, err
				}
				if b, ok := exact.LagrangeBound(m, box, cost, y); ok {
					if minBound == nil || b.Cmp(minBound) < 0 {
						minBound = b
					}
					continue
				}
			}
			boundKnown = false
		case "uncertified":
			rep.Uncertified++
			boundKnown = false
		default:
			return nil, fmt.Errorf("unknown leaf kind %q", n.Leaf)
		}
	}
	for i, ok := range seen {
		if !ok {
			return nil, fmt.Errorf("proof contains unreachable node %d", i)
		}
	}
	rep.Complete = rep.OpenLeaves == 0 && rep.Uncertified == 0
	if boundKnown && minBound != nil {
		gb := minBound
		if intObj {
			gb = ceilRat(gb)
		}
		rep.GlobalBound = toOrig(gb)
	}
	switch p.Status {
	case "optimal":
		if !rep.Complete {
			return nil, fmt.Errorf("claimed optimal but the proof has %d open and %d uncertified leaves", rep.OpenLeaves, rep.Uncertified)
		}
		if rep.FarkasLeaves+rep.BoundLeaves != rep.Leaves {
			return nil, fmt.Errorf("leaf accounting mismatch")
		}
	case "infeasible":
		if p.X != nil {
			return nil, fmt.Errorf("status infeasible but a solution is attached")
		}
		if !rep.Complete || rep.FarkasLeaves != rep.Leaves {
			return nil, fmt.Errorf("claimed infeasible but not every leaf is a Farkas leaf")
		}
	case "limit":
		// nothing more to prove: bounds and incumbent verified above
	}
	return rep, nil
}

// UnmarshalProof decodes a proof file.
func UnmarshalProof(b []byte) (*Proof, error) {
	var p Proof
	if err := json.Unmarshal(b, &p); err != nil {
		return nil, fmt.Errorf("not a valid proof file: %w", err)
	}
	return &p, nil
}
