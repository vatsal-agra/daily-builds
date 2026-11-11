package fem

import (
	"bufio"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
)

// Input is a parsed model file: either a solid (2-D continuum) or a frame problem.
type Input struct {
	Title  string
	Solid  *Model
	Frame  *Frame
	Solver SolverKind
	Fields []Field
	Scale  float64 // deformation scale, 0 = auto
	Mesh   bool    // draw mesh lines
}

type kv map[string]string

// kvRe matches key=value tokens but not comparison operators like x==0, r<=1 or y>=3.
var kvRe = regexp.MustCompile(`^[A-Za-z_]+=([^=].*)?$`)

func parseKV(fields []string) (kv, []string, error) {
	m := kv{}
	var rest []string
	for _, f := range fields {
		if kvRe.MatchString(f) {
			i := strings.IndexByte(f, '=')
			k := strings.ToLower(f[:i])
			if _, dup := m[k]; dup {
				return nil, nil, fmt.Errorf("duplicate key %q", k)
			}
			m[k] = f[i+1:]
		} else {
			rest = append(rest, f)
		}
	}
	return m, rest, nil
}

func (k kv) num(key string, def float64, required bool) (float64, error) {
	s, ok := k[key]
	if !ok {
		if required {
			return 0, fmt.Errorf("missing %s=", key)
		}
		return def, nil
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil || math.IsNaN(v) || math.IsInf(v, 0) {
		return 0, fmt.Errorf("%s=%q is not a finite number", key, s)
	}
	return v, nil
}

func (k kv) integer(key string, def int, required bool) (int, error) {
	s, ok := k[key]
	if !ok {
		if required {
			return 0, fmt.Errorf("missing %s=", key)
		}
		return def, nil
	}
	v, err := strconv.Atoi(s)
	if err != nil {
		return 0, fmt.Errorf("%s=%q is not an integer", key, s)
	}
	return v, nil
}

func (k kv) check(allowed ...string) error {
	ok := map[string]bool{}
	for _, a := range allowed {
		ok[a] = true
	}
	for key := range k {
		if !ok[key] {
			return fmt.Errorf("unknown option %q (allowed: %s)", key, strings.Join(allowed, ", "))
		}
	}
	return nil
}

var predRe = regexp.MustCompile(`^(x|y|r)(<=|>=|==|<|>)(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)$`)

type term struct {
	v   byte
	op  string
	val float64
}

// parsePred parses "x<=0&&y>=1" style selections (spaces are removed beforehand).
func parsePred(s string) ([]term, error) {
	var ts []term
	for _, part := range strings.Split(strings.ReplaceAll(s, " ", ""), "&&") {
		m := predRe.FindStringSubmatch(part)
		if m == nil {
			return nil, fmt.Errorf("cannot parse selection %q (use x|y|r with <,<=,==,>=,> joined by &&)", part)
		}
		v, _ := strconv.ParseFloat(m[3], 64)
		ts = append(ts, term{m[1][0], m[2], v})
	}
	return ts, nil
}

func evalPred(ts []term, x, y, tol float64) bool {
	for _, t := range ts {
		var a float64
		switch t.v {
		case 'x':
			a = x
		case 'y':
			a = y
		default:
			a = math.Hypot(x, y)
		}
		ok := false
		switch t.op {
		case "<=":
			ok = a <= t.val+tol
		case ">=":
			ok = a >= t.val-tol
		case "==":
			ok = math.Abs(a-t.val) <= tol
		case "<":
			ok = a < t.val-tol
		case ">":
			ok = a > t.val+tol
		}
		if !ok {
			return false
		}
	}
	return true
}

func parseDofs(s string, allowR bool) ([]int, error) {
	var d []int
	for _, c := range strings.ToLower(s) {
		switch c {
		case 'x':
			d = append(d, 0)
		case 'y':
			d = append(d, 1)
		case 'r':
			if !allowR {
				return nil, fmt.Errorf("rotation dof 'r' only applies to frames")
			}
			d = append(d, 2)
		default:
			return nil, fmt.Errorf("bad dof character %q in %q", string(c), s)
		}
	}
	if len(d) == 0 {
		return nil, fmt.Errorf("dofs= is empty")
	}
	return d, nil
}

// Parse reads the Girder model-file format. Errors carry line numbers.
func Parse(src string) (*Input, error) {
	in := &Input{Solver: SolverDirect, Fields: []Field{FieldVonMises, FieldDispMag}}
	var mat Material
	haveMat := false
	var mesh *Mesh
	isFrame := false
	sc := bufio.NewScanner(strings.NewReader(src))
	ln := 0
	fail := func(err error) (*Input, error) { return nil, fmt.Errorf("line %d: %w", ln, err) }
	for sc.Scan() {
		ln++
		line := sc.Text()
		if i := strings.IndexByte(line, '#'); i >= 0 {
			line = line[:i]
		}
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		cmd := strings.ToLower(fields[0])
		args, rest, err := parseKV(fields[1:])
		if err != nil {
			return fail(err)
		}
		for i, r := range rest { // "where <expr>" selection: everything after the word `where`
			if strings.EqualFold(r, "where") {
				if _, dup := args["where"]; dup || i == len(rest)-1 {
					return fail(fmt.Errorf("`where` needs a selection such as: where x==0"))
				}
				args["where"] = strings.Join(rest[i+1:], "")
				rest = rest[:i]
				break
			}
		}
		switch cmd {
		case "title":
			in.Title = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(line), fields[0]))
		case "frame":
			isFrame = true
			in.Frame = NewFrame()
		case "material":
			if err := args.check("e", "nu", "t", "plane", "rho", "k"); err != nil {
				return fail(err)
			}
			if mat.E, err = args.num("e", 0, true); err != nil {
				return fail(err)
			}
			if mat.Nu, err = args.num("nu", 0.3, false); err != nil {
				return fail(err)
			}
			if mat.Thickness, err = args.num("t", 1, false); err != nil {
				return fail(err)
			}
			if mat.Rho, err = args.num("rho", 0, false); err != nil {
				return fail(err)
			}
			if mat.Cond, err = args.num("k", 0, false); err != nil {
				return fail(err)
			}
			switch strings.ToLower(args["plane"]) {
			case "", "stress":
			case "strain":
				mat.PlaneStrain = true
			default:
				return fail(fmt.Errorf("plane= must be stress or strain"))
			}
			if err := mat.Validate(); err != nil {
				return fail(err)
			}
			haveMat = true
		case "mesh":
			if isFrame {
				return fail(fmt.Errorf("mesh is not valid in a frame model"))
			}
			if mesh != nil {
				return fail(fmt.Errorf("only one mesh per model"))
			}
			if len(rest) != 1 {
				return fail(fmt.Errorf("usage: mesh rect|annulus|quarterhole key=value..."))
			}
			et, err := ParseElemType(args["type"])
			if args["type"] == "" {
				et, err = Quad4, nil
			}
			if err != nil {
				return fail(err)
			}
			switch strings.ToLower(rest[0]) {
			case "rect":
				if err := args.check("x0", "y0", "w", "h", "nx", "ny", "type"); err != nil {
					return fail(err)
				}
				x0, _ := args.num("x0", 0, false)
				y0, _ := args.num("y0", 0, false)
				w, e1 := args.num("w", 0, true)
				h, e2 := args.num("h", 0, true)
				nx, e3 := args.integer("nx", 0, true)
				ny, e4 := args.integer("ny", 0, true)
				for _, e := range []error{e1, e2, e3, e4} {
					if e != nil {
						return fail(e)
					}
				}
				if nx*ny > 400000 {
					return fail(fmt.Errorf("mesh too large (%d cells)", nx*ny))
				}
				mesh, err = Rect(x0, y0, w, h, nx, ny, et)
			case "annulus", "quarterhole":
				keys := []string{"a", "b", "nr", "nt", "type"}
				if rest[0] == "quarterhole" {
					keys = []string{"a", "l", "nr", "nt", "type"}
				}
				if err := args.check(keys...); err != nil {
					return fail(err)
				}
				a, e1 := args.num("a", 0, true)
				nr, e3 := args.integer("nr", 0, true)
				nt, e4 := args.integer("nt", 0, true)
				var b float64
				var e2 error
				if rest[0] == "annulus" {
					b, e2 = args.num("b", 0, true)
				} else {
					b, e2 = args.num("l", 0, true)
				}
				for _, e := range []error{e1, e2, e3, e4} {
					if e != nil {
						return fail(e)
					}
				}
				if nr*nt > 400000 {
					return fail(fmt.Errorf("mesh too large"))
				}
				if rest[0] == "annulus" {
					mesh, err = Annulus(a, b, nr, nt, et)
				} else {
					mesh, err = QuarterHole(b, a, nr, nt, et)
				}
			default:
				return fail(fmt.Errorf("unknown mesh generator %q", rest[0]))
			}
			if err != nil {
				return fail(err)
			}
			if !haveMat {
				return fail(fmt.Errorf("define `material` before `mesh`"))
			}
			in.Solid = NewModel(mesh, mat)
		case "fix", "load", "traction", "pressure", "body", "node", "beam", "bar", "support", "force":
			if err := in.applyBC(cmd, args, rest, line, isFrame); err != nil {
				return fail(err)
			}
		case "solve":
			if err := args.check("solver"); err != nil {
				return fail(err)
			}
			switch SolverKind(args["solver"]) {
			case "", SolverDirect:
			case SolverCGJacobi, SolverCGIC0:
				in.Solver = SolverKind(args["solver"])
			default:
				return fail(fmt.Errorf("solver= must be direct, cg-jacobi or cg-ic0"))
			}
		case "plot":
			if err := args.check("fields", "scale", "mesh"); err != nil {
				return fail(err)
			}
			if f, ok := args["fields"]; ok {
				in.Fields = nil
				for _, name := range strings.Split(f, ",") {
					switch fl := Field(strings.ToLower(name)); fl {
					case FieldVonMises, FieldSXX, FieldSYY, FieldSXY, FieldS1, FieldS3, FieldDispMag, FieldUX, FieldUY:
						in.Fields = append(in.Fields, fl)
					default:
						return fail(fmt.Errorf("unknown field %q", name))
					}
				}
			}
			if s, ok := args["scale"]; ok && s != "auto" {
				if in.Scale, err = args.num("scale", 0, true); err != nil {
					return fail(err)
				}
			}
			in.Mesh = args["mesh"] == "on"
		default:
			return fail(fmt.Errorf("unknown directive %q", cmd))
		}
	}
	if in.Frame == nil && in.Solid == nil {
		return nil, fmt.Errorf("model defines neither a mesh nor a frame")
	}
	return in, nil
}

func (in *Input) applyBC(cmd string, args kv, rest []string, line string, isFrame bool) error {
	if isFrame {
		f := in.Frame
		switch cmd {
		case "node":
			if len(rest) != 2 {
				return fmt.Errorf("usage: node X Y")
			}
			x, e1 := strconv.ParseFloat(rest[0], 64)
			y, e2 := strconv.ParseFloat(rest[1], 64)
			if e1 != nil || e2 != nil {
				return fmt.Errorf("node coordinates must be numbers")
			}
			f.AddNode(x, y)
		case "beam", "bar":
			if err := args.check("e", "a", "i", "w", "rho"); err != nil {
				return err
			}
			if len(rest) != 2 {
				return fmt.Errorf("usage: %s N1 N2 E= A= [I=] [W=]", cmd)
			}
			n1, e1 := strconv.Atoi(rest[0])
			n2, e2 := strconv.Atoi(rest[1])
			if e1 != nil || e2 != nil {
				return fmt.Errorf("node ids must be integers")
			}
			m := Member{N1: n1, N2: n2, Truss: cmd == "bar"}
			var err error
			if m.E, err = args.num("e", 0, true); err != nil {
				return err
			}
			if m.A, err = args.num("a", 0, true); err != nil {
				return err
			}
			if m.I, err = args.num("i", 0, cmd == "beam"); err != nil {
				return err
			}
			if m.W, err = args.num("w", 0, false); err != nil {
				return err
			}
			if m.Rho, err = args.num("rho", 0, false); err != nil {
				return err
			}
			_, err = f.AddMember(m)
			return err
		case "support":
			if err := args.check("dofs"); err != nil {
				return err
			}
			n, err := oneInt(rest, "support N dofs=xyr")
			if err != nil {
				return err
			}
			d, err := parseDofs(args["dofs"], true)
			if err != nil {
				return err
			}
			for _, c := range d {
				if err := f.Fix(n, c); err != nil {
					return err
				}
			}
		case "force":
			if err := args.check("fx", "fy", "mz"); err != nil {
				return err
			}
			n, err := oneInt(rest, "force N fx= fy= mz=")
			if err != nil {
				return err
			}
			fx, e1 := args.num("fx", 0, false)
			fy, e2 := args.num("fy", 0, false)
			mz, e3 := args.num("mz", 0, false)
			for _, e := range []error{e1, e2, e3} {
				if e != nil {
					return e
				}
			}
			return f.Load(n, fx, fy, mz)
		default:
			return fmt.Errorf("%q is not valid in a frame model", cmd)
		}
		return nil
	}
	md := in.Solid
	if md == nil {
		return fmt.Errorf("`%s` must come after `mesh`", cmd)
	}
	x0, y0, x1, y1 := md.Mesh.Bounds()
	tol := 1e-9 * math.Max(x1-x0, y1-y0)
	var sel []term
	if w, ok := args["where"]; ok {
		var err error
		if sel, err = parsePred(w); err != nil {
			return err
		}
	}
	nodes := func() ([]int, error) {
		switch {
		case args["where"] != "":
			var ns []int
			for i := range md.Mesh.X {
				if evalPred(sel, md.Mesh.X[i], md.Mesh.Y[i], tol) {
					ns = append(ns, i)
				}
			}
			if len(ns) == 0 {
				return nil, fmt.Errorf("selection %q matches no nodes", args["where"])
			}
			return ns, nil
		case args["node"] != "":
			n, err := strconv.Atoi(args["node"])
			if err != nil {
				return nil, fmt.Errorf("node=%q is not an integer", args["node"])
			}
			return []int{n}, nil
		case args["nearest"] != "":
			p := strings.Split(args["nearest"], ",")
			if len(p) != 2 {
				return nil, fmt.Errorf("nearest= needs x,y")
			}
			x, e1 := strconv.ParseFloat(p[0], 64)
			y, e2 := strconv.ParseFloat(p[1], 64)
			if e1 != nil || e2 != nil {
				return nil, fmt.Errorf("nearest= needs numeric x,y")
			}
			return []int{md.Mesh.NearestNode(x, y)}, nil
		}
		return nil, fmt.Errorf("select nodes with where=, node= or nearest=")
	}
	edges := func() ([]Edge, error) {
		if args["where"] == "" {
			return nil, fmt.Errorf("select boundary edges with where=")
		}
		es := md.Mesh.EdgesWhere(func(ax, ay, bx, by float64) bool {
			return evalPred(sel, ax, ay, tol) && evalPred(sel, bx, by, tol)
		})
		if len(es) == 0 {
			return nil, fmt.Errorf("selection %q matches no boundary edges", args["where"])
		}
		return es, nil
	}
	switch cmd {
	case "fix":
		if err := args.check("where", "node", "nearest", "dofs", "value"); err != nil {
			return err
		}
		ns, err := nodes()
		if err != nil {
			return err
		}
		ds := args["dofs"]
		if ds == "" {
			ds = "xy"
		}
		d, err := parseDofs(ds, false)
		if err != nil {
			return err
		}
		v, err := args.num("value", 0, false)
		if err != nil {
			return err
		}
		for _, n := range ns {
			for _, c := range d {
				if err := md.FixDOF(n, c, v); err != nil {
					return err
				}
			}
		}
	case "load":
		if err := args.check("where", "node", "nearest", "fx", "fy", "total"); err != nil {
			return err
		}
		ns, err := nodes()
		if err != nil {
			return err
		}
		fx, e1 := args.num("fx", 0, false)
		fy, e2 := args.num("fy", 0, false)
		for _, e := range []error{e1, e2} {
			if e != nil {
				return e
			}
		}
		if args["total"] == "yes" { // split the force evenly over the selected nodes
			fx, fy = fx/float64(len(ns)), fy/float64(len(ns))
		}
		for _, n := range ns {
			if err := md.PointLoad(n, fx, fy); err != nil {
				return err
			}
		}
	case "traction":
		if err := args.check("where", "tx", "ty"); err != nil {
			return err
		}
		es, err := edges()
		if err != nil {
			return err
		}
		tx, e1 := args.num("tx", 0, false)
		ty, e2 := args.num("ty", 0, false)
		for _, e := range []error{e1, e2} {
			if e != nil {
				return e
			}
		}
		for _, e := range es {
			if err := md.EdgeTraction(e, tx, ty); err != nil {
				return err
			}
		}
	case "pressure":
		if err := args.check("where", "p"); err != nil {
			return err
		}
		es, err := edges()
		if err != nil {
			return err
		}
		p, err := args.num("p", 0, true)
		if err != nil {
			return err
		}
		for _, e := range es {
			if err := md.EdgePressure(e, p); err != nil {
				return err
			}
		}
	case "body":
		if err := args.check("bx", "by"); err != nil {
			return err
		}
		bx, e1 := args.num("bx", 0, false)
		by, e2 := args.num("by", 0, false)
		for _, e := range []error{e1, e2} {
			if e != nil {
				return e
			}
		}
		return md.BodyForce(bx, by)
	default:
		return fmt.Errorf("%q is not valid in a solid model", cmd)
	}
	return nil
}

func oneInt(rest []string, usage string) (int, error) {
	if len(rest) != 1 {
		return 0, fmt.Errorf("usage: %s", usage)
	}
	n, err := strconv.Atoi(rest[0])
	if err != nil {
		return 0, fmt.Errorf("node id %q is not an integer", rest[0])
	}
	return n, nil
}
