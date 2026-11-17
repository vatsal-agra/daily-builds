package orrery

import (
	"bufio"
	"fmt"
	"math"
	"math/rand"
	"sort"
	"strconv"
	"strings"
)

// ParseScenario reads the scenario text format:
//
//	# comment
//	title Some name
//	G 1            gravitational constant
//	eps 0.01       Plummer softening
//	theta 0.5      Barnes–Hut opening angle (0 = exact)
//	body Sun   m=1  pos=0,0,0 vel=0,0,0
//	body Earth m=3e-6 orbit=Sun a=1 e=0.0167 i=0 raan=0 argp=0 ma=0  (angles in degrees; ma = mean anomaly)
//	barycentric    shift to the centre-of-mass frame after reading
//
// Errors carry the line number.
func ParseScenario(text string) (*System, error) {
	s := &System{G: 1}
	bary := false
	sc := bufio.NewScanner(strings.NewReader(text))
	sc.Buffer(make([]byte, 1<<20), 1<<26)
	ln := 0
	for sc.Scan() {
		ln++
		line := sc.Text()
		if i := strings.Index(line, "#"); i >= 0 {
			line = line[:i]
		}
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		fail := func(format string, a ...any) (*System, error) {
			return nil, fmt.Errorf("line %d: %s", ln, fmt.Sprintf(format, a...))
		}
		switch strings.ToLower(f[0]) {
		case "title":
			s.Title = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(line), f[0]))
		case "g", "eps", "theta":
			if len(f) != 2 {
				return fail("%s takes exactly one value", f[0])
			}
			v, err := strconv.ParseFloat(f[1], 64)
			if err != nil || math.IsNaN(v) || math.IsInf(v, 0) {
				return fail("bad number %q for %s", f[1], f[0])
			}
			switch strings.ToLower(f[0]) {
			case "g":
				s.G = v
			case "eps":
				s.Eps = v
			default:
				s.Theta = v
			}
		case "barycentric":
			bary = true
		case "body":
			b, err := parseBody(s, f[1:])
			if err != nil {
				return fail("%v", err)
			}
			s.Bodies = append(s.Bodies, b)
		default:
			return fail("unknown directive %q", f[0])
		}
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	if len(s.Bodies) == 0 {
		return nil, fmt.Errorf("scenario has no bodies")
	}
	if bary {
		s.ToBarycentric()
	}
	if err := s.Validate(); err != nil {
		return nil, err
	}
	return s, nil
}

func parseVec(v string) (Vec3, error) {
	p := strings.Split(v, ",")
	if len(p) != 3 {
		return Vec3{}, fmt.Errorf("vector %q needs 3 comma-separated components", v)
	}
	var out [3]float64
	for i, c := range p {
		x, err := strconv.ParseFloat(c, 64)
		if err != nil || math.IsNaN(x) || math.IsInf(x, 0) {
			return Vec3{}, fmt.Errorf("bad number %q in vector", c)
		}
		out[i] = x
	}
	return Vec3{out[0], out[1], out[2]}, nil
}

func parseBody(s *System, f []string) (Body, error) {
	if len(f) == 0 {
		return Body{}, fmt.Errorf("body needs a name")
	}
	b := Body{Name: f[0]}
	if strings.Contains(b.Name, "=") {
		return b, fmt.Errorf("body name %q must come first and not contain '='", b.Name)
	}
	kv := map[string]string{}
	for _, tok := range f[1:] {
		i := strings.Index(tok, "=")
		if i <= 0 {
			return b, fmt.Errorf("expected key=value, got %q", tok)
		}
		k := strings.ToLower(tok[:i])
		if _, dup := kv[k]; dup {
			return b, fmt.Errorf("duplicate key %q", k)
		}
		kv[k] = tok[i+1:]
	}
	num := func(k string, def float64) (float64, error) {
		v, ok := kv[k]
		if !ok {
			return def, nil
		}
		delete(kv, k)
		x, err := strconv.ParseFloat(v, 64)
		if err != nil || math.IsNaN(x) || math.IsInf(x, 0) {
			return 0, fmt.Errorf("bad number %q for %s", v, k)
		}
		return x, nil
	}
	mv, ok := kv["m"]
	if !ok {
		return b, fmt.Errorf("body %s: missing m=", b.Name)
	}
	m, err := strconv.ParseFloat(mv, 64)
	if err != nil || !(m > 0) || math.IsInf(m, 0) {
		return b, fmt.Errorf("body %s: mass must be a positive number, got %q", b.Name, mv)
	}
	b.M = m
	delete(kv, "m")
	if parent, ok := kv["orbit"]; ok {
		delete(kv, "orbit")
		pi := s.Index(parent)
		if pi < 0 {
			return b, fmt.Errorf("body %s: orbit parent %q must be defined earlier", b.Name, parent)
		}
		var el Elements
		if el.A, err = num("a", 0); err != nil {
			return b, err
		}
		if el.E, err = num("e", 0); err != nil {
			return b, err
		}
		var deg [4]float64
		for i, k := range []string{"i", "raan", "argp", "ma"} {
			if deg[i], err = num(k, 0); err != nil {
				return b, err
			}
		}
		el.I, el.Raan, el.Argp, el.M = deg[0]*math.Pi/180, deg[1]*math.Pi/180, deg[2]*math.Pi/180, deg[3]*math.Pi/180
		if el.A <= 0 {
			return b, fmt.Errorf("body %s: orbit needs a>0", b.Name)
		}
		P := s.Bodies[pi]
		mu := s.G * (P.M + b.M)
		r, v, err := StateFromElements(el, mu)
		if err != nil {
			return b, fmt.Errorf("body %s: %v", b.Name, err)
		}
		b.Pos, b.Vel = P.Pos.Add(r), P.Vel.Add(v)
		if len(kv) > 0 {
			return b, fmt.Errorf("body %s: unknown keys %v", b.Name, keys(kv))
		}
		return b, nil
	}
	if v, ok := kv["pos"]; ok {
		delete(kv, "pos")
		if b.Pos, err = parseVec(v); err != nil {
			return b, err
		}
	}
	if v, ok := kv["vel"]; ok {
		delete(kv, "vel")
		if b.Vel, err = parseVec(v); err != nil {
			return b, err
		}
	}
	if len(kv) > 0 {
		return b, fmt.Errorf("body %s: unknown keys %v", b.Name, keys(kv))
	}
	return b, nil
}

func keys(m map[string]string) []string {
	k := make([]string, 0, len(m))
	for x := range m {
		k = append(k, x)
	}
	sort.Strings(k)
	return k
}

// FormatScenario writes a scenario that parses back to an identical system.
func FormatScenario(s *System) string {
	var sb strings.Builder
	f := func(x float64) string { return strconv.FormatFloat(x, 'g', -1, 64) }
	if s.Title != "" {
		fmt.Fprintf(&sb, "title %s\n", s.Title)
	}
	fmt.Fprintf(&sb, "G %s\neps %s\ntheta %s\n", f(s.G), f(s.Eps), f(s.Theta))
	for _, b := range s.Bodies {
		fmt.Fprintf(&sb, "body %s m=%s pos=%s,%s,%s vel=%s,%s,%s\n", b.Name, f(b.M),
			f(b.Pos.X), f(b.Pos.Y), f(b.Pos.Z), f(b.Vel.X), f(b.Vel.Y), f(b.Vel.Z))
	}
	return sb.String()
}

// BuiltinInfo describes a built-in scenario.
type BuiltinInfo struct{ Name, Desc string }

// Builtins lists built-in systems.
func Builtins() []BuiltinInfo {
	return []BuiltinInfo{
		{"twobody", "Eccentric Kepler binary (e=0.6), exact analytic solution exists"},
		{"figure8", "Chenciner–Montgomery figure-eight choreography (3 equal masses, period 6.3259)"},
		{"pythagorean", "Burrau's 3-4-5 problem: chaotic, many close encounters"},
		{"solar", "Sun + 8 planets, approximate J2000 elements (AU, yr, M☉; G=4π²)"},
		{"trojan", "Sun, Jupiter and a body at the L4 Lagrange point"},
		{"plummer", "Plummer sphere in virial equilibrium (param: n, seed)"},
		{"disc", "Central mass with a thin disc of light test particles (param: n, seed)"},
	}
}

// Builtin constructs a named scenario. n and seed only affect generators.
func Builtin(name string, n int, seed int64) (*System, error) {
	var s *System
	switch name {
	case "twobody":
		s = &System{Title: "Eccentric binary", G: 1}
		s.Bodies = []Body{{Name: "A", M: 1}, {Name: "B", M: 0.5}}
		r, v, _ := StateFromElements(Elements{A: 1, E: 0.6, M: 0}, s.G*1.5)
		s.Bodies[1].Pos, s.Bodies[1].Vel = r, v
		s.ToBarycentric()
	case "figure8":
		s = &System{Title: "Figure-eight choreography", G: 1}
		p := Vec3{0.97000436, -0.24308753, 0}
		v := Vec3{-0.93240737, -0.86473146, 0}
		s.Bodies = []Body{
			{Name: "A", M: 1, Pos: p, Vel: v.Scale(-0.5)},
			{Name: "B", M: 1, Pos: p.Scale(-1), Vel: v.Scale(-0.5)},
			{Name: "C", M: 1, Vel: v},
		}
	case "pythagorean":
		s = &System{Title: "Pythagorean three-body problem", G: 1}
		s.Bodies = []Body{
			{Name: "m3", M: 3, Pos: Vec3{1, 3, 0}},
			{Name: "m4", M: 4, Pos: Vec3{-2, -1, 0}},
			{Name: "m5", M: 5, Pos: Vec3{1, -1, 0}},
		}
		s.ToBarycentric()
	case "solar":
		return solarSystem(), nil
	case "trojan":
		s = &System{Title: "Sun–Jupiter–Trojan (L4)", G: 4 * math.Pi * math.Pi}
		s.Bodies = []Body{{Name: "Sun", M: 1}, {Name: "Jupiter", M: 9.546e-4}}
		r, v, _ := StateFromElements(Elements{A: 5.2026, E: 0}, s.G*(1+9.546e-4))
		s.Bodies[1].Pos, s.Bodies[1].Vel = r, v
		// rotate Jupiter's state by +60° for the Trojan
		c, sn := math.Cos(math.Pi/3), math.Sin(math.Pi/3)
		rot := func(a Vec3) Vec3 { return Vec3{c*a.X - sn*a.Y, sn*a.X + c*a.Y, a.Z} }
		s.Bodies = append(s.Bodies, Body{Name: "Trojan", M: 1e-12, Pos: rot(r), Vel: rot(v)})
		s.ToBarycentric()
	case "plummer":
		if n < 2 {
			n = 200
		}
		s = plummer(n, seed)
	case "disc":
		if n < 1 {
			n = 300
		}
		s = disc(n, seed)
	default:
		names := make([]string, 0)
		for _, b := range Builtins() {
			names = append(names, b.Name)
		}
		return nil, fmt.Errorf("unknown built-in scenario %q (choose from %v)", name, names)
	}
	if err := s.Validate(); err != nil {
		return nil, err
	}
	return s, nil
}

func solarSystem() *System {
	s := &System{Title: "Solar system (approx. J2000)", G: 4 * math.Pi * math.Pi}
	s.Bodies = []Body{{Name: "Sun", M: 1}}
	type pl struct {
		name                    string
		m, a, e, i, raan, w, ma float64
	}
	for _, p := range []pl{
		{"Mercury", 1.66e-7, 0.38710, 0.2056, 7.00, 48.33, 29.12, 174.8},
		{"Venus", 2.448e-6, 0.72333, 0.0068, 3.39, 76.68, 54.88, 50.1},
		{"Earth", 3.003e-6, 1.00000, 0.0167, 0.00, 348.74, 114.2, 357.5},
		{"Mars", 3.227e-7, 1.52368, 0.0934, 1.85, 49.56, 286.5, 19.4},
		{"Jupiter", 9.546e-4, 5.20260, 0.0484, 1.30, 100.46, 273.87, 20.0},
		{"Saturn", 2.859e-4, 9.55490, 0.0555, 2.49, 113.66, 339.39, 317.0},
		{"Uranus", 4.366e-5, 19.2184, 0.0463, 0.77, 74.00, 96.9, 142.2},
		{"Neptune", 5.151e-5, 30.0699, 0.0090, 1.77, 131.78, 273.2, 256.2},
	} {
		d := math.Pi / 180
		r, v, _ := StateFromElements(Elements{A: p.a, E: p.e, I: p.i * d, Raan: p.raan * d, Argp: p.w * d, M: p.ma * d},
			s.G*(1+p.m))
		s.Bodies = append(s.Bodies, Body{Name: p.name, M: p.m, Pos: r, Vel: v})
	}
	s.ToBarycentric()
	return s
}

// plummer samples the Plummer model (Aarseth, Hénon & Wielen 1974) in Hénon
// units and rescales velocities so the sample is *exactly* in virial balance.
func plummer(n int, seed int64) *System {
	rng := rand.New(rand.NewSource(seed))
	s := &System{Title: fmt.Sprintf("Plummer sphere (n=%d, seed=%d)", n, seed), G: 1, Eps: 0.02, Theta: 0.5}
	a := 3 * math.Pi / 16
	for i := 0; i < n; i++ {
		var r float64
		for {
			x := rng.Float64()
			if x <= 0 {
				continue
			}
			r = a / math.Sqrt(math.Pow(x, -2.0/3)-1)
			if r < 30*a { // truncate the extreme tail
				break
			}
		}
		dir := isotropic(rng)
		var q float64
		for {
			q = rng.Float64()
			g := rng.Float64() * 0.1
			if g < q*q*math.Pow(1-q*q, 3.5) {
				break
			}
		}
		ve := math.Sqrt2 * math.Pow(1+r*r/(a*a), -0.25) / math.Sqrt(a)
		s.Bodies = append(s.Bodies, Body{Name: fmt.Sprintf("p%d", i), M: 1 / float64(n),
			Pos: dir.Scale(r), Vel: isotropic(rng).Scale(q * ve)})
	}
	s.ToBarycentric()
	k, u := s.Kinetic(), s.Potential()
	f := math.Sqrt(0.5 * math.Abs(u) / k)
	for i := range s.Bodies {
		s.Bodies[i].Vel = s.Bodies[i].Vel.Scale(f)
	}
	return s
}

func isotropic(rng *rand.Rand) Vec3 {
	z := 2*rng.Float64() - 1
	p := 2 * math.Pi * rng.Float64()
	r := math.Sqrt(1 - z*z)
	return Vec3{r * math.Cos(p), r * math.Sin(p), z}
}

// disc builds a heavy central mass with n light particles on near-circular
// orbits between r=0.5 and r=2.
func disc(n int, seed int64) *System {
	rng := rand.New(rand.NewSource(seed))
	s := &System{Title: fmt.Sprintf("Test-particle disc (n=%d, seed=%d)", n, seed), G: 1, Eps: 0.001, Theta: 0.6}
	s.Bodies = append(s.Bodies, Body{Name: "star", M: 1})
	m := 1e-6 / float64(n)
	for i := 0; i < n; i++ {
		r := 0.5 + 1.5*rng.Float64()
		ph := 2 * math.Pi * rng.Float64()
		vc := math.Sqrt(s.G / r)
		e := 0.05 * rng.Float64()
		s.Bodies = append(s.Bodies, Body{Name: fmt.Sprintf("d%d", i), M: m,
			Pos: Vec3{r * math.Cos(ph), r * math.Sin(ph), 0.01 * r * (rng.Float64() - 0.5)},
			Vel: Vec3{-vc * math.Sin(ph) * (1 + e), vc * math.Cos(ph) * (1 + e), 0}})
	}
	s.ToBarycentric()
	return s
}
