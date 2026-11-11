package fem

import (
	"fmt"
	"math"
)

// TopOptCase names a built-in design problem.
type TopOptCase string

const (
	CaseMBB        TopOptCase = "mbb"        // half MBB beam (symmetry on the left)
	CaseCantilever TopOptCase = "cantilever" // clamped left edge, load at mid-height on the right
	CaseBridge     TopOptCase = "bridge"     // simply supported deck loaded along its underside
)

// TopOptParams configures a SIMP run.
type TopOptParams struct {
	Case      TopOptCase
	NX, NY    int
	VolFrac   float64
	Penal     float64
	RMin      float64 // filter radius in elements
	MaxIter   int
	Tol       float64 // stop when max density change < Tol
	SnapEvery int
}

// TopOptSnapshot stores a density field at an iteration.
type TopOptSnapshot struct {
	Iter  int
	Rho   []float64
	Compl float64
}

// TopOptResult is the outcome of an optimisation.
type TopOptResult struct {
	P         TopOptParams
	Rho       []float64 // physical (filtered) densities, row-major, row 0 = bottom
	Compl     []float64 // compliance history
	Vol       []float64 // volume fraction history
	Snaps     []TopOptSnapshot
	Iters     int
	Converged bool
	Initial   float64 // compliance of the uniform starting design
}

func (p *TopOptParams) validate() error {
	switch {
	case p.NX < 4 || p.NY < 4:
		return fmt.Errorf("grid must be at least 4x4 (got %dx%d)", p.NX, p.NY)
	case p.NX*p.NY > 40000:
		return fmt.Errorf("grid too large (%d elements, limit 40000)", p.NX*p.NY)
	case !(p.VolFrac > 0.02 && p.VolFrac < 0.98):
		return fmt.Errorf("volume fraction must be in (0.02, 0.98), got %g", p.VolFrac)
	case !(p.Penal >= 1 && p.Penal <= 6):
		return fmt.Errorf("penalty must be in [1, 6], got %g", p.Penal)
	case !(p.RMin >= 1):
		return fmt.Errorf("filter radius must be >= 1 element (smaller radii give checkerboards), got %g", p.RMin)
	case p.MaxIter < 1:
		return fmt.Errorf("max iterations must be positive")
	}
	switch p.Case {
	case CaseMBB, CaseCantilever, CaseBridge:
	default:
		return fmt.Errorf("unknown case %q (mbb, cantilever, bridge)", p.Case)
	}
	return nil
}

// setupTopOpt builds the grid mesh, supports and load vector for a case.
func setupTopOpt(p TopOptParams) (*Mesh, map[int]float64, []float64) {
	m, _ := Rect(0, 0, float64(p.NX), float64(p.NY), p.NX, p.NY, Quad4)
	node := func(i, j int) int { return j*(p.NX+1) + i }
	fixed := map[int]float64{}
	f := make([]float64, 2*m.NumNodes())
	switch p.Case {
	case CaseMBB:
		for j := 0; j <= p.NY; j++ {
			fixed[2*node(0, j)] = 0
		}
		fixed[2*node(p.NX, 0)+1] = 0
		f[2*node(0, p.NY)+1] = -1
	case CaseCantilever:
		for j := 0; j <= p.NY; j++ {
			fixed[2*node(0, j)] = 0
			fixed[2*node(0, j)+1] = 0
		}
		f[2*node(p.NX, p.NY/2)+1] = -1
	case CaseBridge:
		fixed[2*node(0, 0)] = 0
		fixed[2*node(0, 0)+1] = 0
		fixed[2*node(p.NX, 0)+1] = 0
		for i := 0; i <= p.NX; i++ { // deck load along the bottom edge
			w := 1.0 / float64(p.NX)
			if i == 0 || i == p.NX {
				w /= 2
			}
			f[2*node(i, 0)+1] -= w
		}
	}
	return m, fixed, f
}

// OptimizeTopology runs SIMP compliance minimisation with a density filter and OC update.
func OptimizeTopology(p TopOptParams, progress func(it int, c, v, change float64)) (*TopOptResult, error) {
	if err := p.validate(); err != nil {
		return nil, err
	}
	nx, ny := p.NX, p.NY
	ne := nx * ny
	mesh, fixed, f := setupTopOpt(p)
	mat := Material{E: 1, Nu: 0.3, Thickness: 1}
	xs, ys := mesh.ElemCoords(0)
	ke, err := Stiffness(Quad4, xs, ys, mat) // identical for every unit square
	if err != nil {
		return nil, err
	}
	// density-filter neighbourhoods (cone weights)
	type nb struct {
		j int
		w float64
	}
	nbrs := make([][]nb, ne)
	wsum := make([]float64, ne)
	r := int(math.Ceil(p.RMin)) - 1
	for ey := 0; ey < ny; ey++ {
		for ex := 0; ex < nx; ex++ {
			e := ey*nx + ex
			for y2 := max(ey-r, 0); y2 <= min(ey+r, ny-1); y2++ {
				for x2 := max(ex-r, 0); x2 <= min(ex+r, nx-1); x2++ {
					d := p.RMin - math.Hypot(float64(ex-x2), float64(ey-y2))
					if d > 0 {
						nbrs[e] = append(nbrs[e], nb{y2*nx + x2, d})
						wsum[e] += d
					}
				}
			}
		}
	}
	filter := func(x []float64) []float64 {
		out := make([]float64, ne)
		for e := range out {
			s := 0.0
			for _, q := range nbrs[e] {
				s += q.w * x[q.j]
			}
			out[e] = s / wsum[e]
		}
		return out
	}
	const emin = 1e-9
	x := make([]float64, ne)
	for i := range x {
		x[i] = p.VolFrac
	}
	res := &TopOptResult{P: p}
	scale := make([]float64, ne)
	for it := 1; it <= p.MaxIter; it++ {
		rho := filter(x)
		for e := range scale {
			scale[e] = emin + (1-emin)*math.Pow(rho[e], p.Penal)
		}
		K := assembleScaled(mesh, ke, scale)
		sol, err := ReduceAndSolve(K, f, fixed, SolverDirect, 0)
		if err != nil {
			return nil, err
		}
		// compliance and sensitivities
		c := 0.0
		dc := make([]float64, ne)
		for e, conn := range mesh.Conn {
			var ue [8]float64
			for i, n := range conn {
				ue[2*i], ue[2*i+1] = sol.U[2*n], sol.U[2*n+1]
			}
			s := 0.0
			for a := 0; a < 8; a++ {
				for b := 0; b < 8; b++ {
					s += ue[a] * ke[a*8+b] * ue[b]
				}
			}
			c += scale[e] * s
			dc[e] = -p.Penal * (1 - emin) * math.Pow(rho[e], p.Penal-1) * s
		}
		// chain rule through the filter: dc/dx_j = sum_i (w_ij / wsum_i) dc/drho_i
		dcx := make([]float64, ne)
		dvx := make([]float64, ne)
		for i := range nbrs {
			for _, q := range nbrs[i] {
				dcx[q.j] += q.w / wsum[i] * dc[i]
				dvx[q.j] += q.w / wsum[i]
			}
		}
		vol := 0.0
		for _, v := range rho {
			vol += v
		}
		vol /= float64(ne)
		if it == 1 {
			res.Initial = c
		}
		res.Compl = append(res.Compl, c)
		res.Vol = append(res.Vol, vol)
		if p.SnapEvery > 0 && (it == 1 || it%p.SnapEvery == 0) {
			res.Snaps = append(res.Snaps, TopOptSnapshot{Iter: it, Rho: rho, Compl: c})
		}
		// optimality-criteria update with bisection on the Lagrange multiplier
		lo, hi := 0.0, 1e9
		xn := make([]float64, ne)
		for hi-lo > 1e-9*(hi+lo) && hi > 1e-30 {
			mid := (lo + hi) / 2
			for e := range x {
				be := math.Sqrt(math.Max(-dcx[e], 0) / (dvx[e] * mid))
				xn[e] = math.Max(0, math.Max(x[e]-0.2, math.Min(1, math.Min(x[e]+0.2, x[e]*be))))
			}
			v := 0.0
			for _, q := range filter(xn) {
				v += q
			}
			if v/float64(ne) > p.VolFrac {
				lo = mid
			} else {
				hi = mid
			}
		}
		change := 0.0
		for e := range x {
			change = math.Max(change, math.Abs(xn[e]-x[e]))
		}
		x = xn
		res.Iters = it
		if progress != nil {
			progress(it, c, vol, change)
		}
		if p.Tol > 0 && change < p.Tol && it > 10 {
			res.Converged = true
			break
		}
	}
	res.Rho = filter(x)
	if p.SnapEvery > 0 {
		res.Snaps = append(res.Snaps, TopOptSnapshot{Iter: res.Iters, Rho: res.Rho, Compl: res.Compl[len(res.Compl)-1]})
	}
	return res, nil
}

// assembleScaled assembles a mesh of identical quad elements with per-element stiffness scaling.
func assembleScaled(m *Mesh, ke, scale []float64) *CSR {
	t := NewTriplets(2 * m.NumNodes())
	nd := 8
	t.I = make([]int, 0, len(m.Conn)*64)
	t.J = make([]int, 0, len(m.Conn)*64)
	t.V = make([]float64, 0, len(m.Conn)*64)
	for e, c := range m.Conn {
		dofs := dofsOf(c)
		for i := 0; i < nd; i++ {
			for j := 0; j < nd; j++ {
				t.I = append(t.I, dofs[i])
				t.J = append(t.J, dofs[j])
				t.V = append(t.V, scale[e]*ke[i*nd+j])
			}
		}
	}
	return t.ToCSR()
}

// GrayFraction returns the share of elements with intermediate density (0.1..0.9).
func GrayFraction(rho []float64) float64 {
	n := 0
	for _, v := range rho {
		if v > 0.1 && v < 0.9 {
			n++
		}
	}
	return float64(n) / float64(len(rho))
}

// TopOptReport renders the optimisation result as an HTML page.
func TopOptReport(r *TopOptResult) string {
	var b stringsBuilder
	last := r.Compl[len(r.Compl)-1]
	b.w(`<div class="grid">`)
	b.w(stat("compliance", fmt.Sprintf("%.4g", last)))
	b.w(stat("vs uniform start", fmt.Sprintf("%.1f× stiffer", r.Initial/last)))
	b.w(stat("volume fraction", fmt.Sprintf("%.3f", r.Vol[len(r.Vol)-1])))
	b.w(stat("iterations", fmt.Sprintf("%d%s", r.Iters, map[bool]string{true: " ✓", false: ""}[r.Converged])))
	b.w(stat("gray elements", fmt.Sprintf("%.1f%%", 100*GrayFraction(r.Rho))))
	b.w(`</div>`)
	b.w(`<div class="panels"><figure><figcaption>Optimised design<small>` + string(r.P.Case) + fmt.Sprintf(`, %d×%d elements, SIMP p=%g, filter radius %g</small></figcaption>`, r.P.NX, r.P.NY, r.P.Penal, r.P.RMin) + DensitySVG(r.Rho, r.P.NX, r.P.NY, 720) + `</figure></div>`)
	if len(r.Snaps) > 1 {
		b.w(`<h2>Evolution</h2><div class="panels">`)
		step := 1
		if len(r.Snaps) > 6 {
			step = (len(r.Snaps) - 1) / 5
		}
		for i := 0; i < len(r.Snaps); i += step {
			s := r.Snaps[i]
			b.w(fmt.Sprintf(`<figure><figcaption>iteration %d<small>compliance %.4g</small></figcaption>%s</figure>`, s.Iter, s.Compl, DensitySVG(s.Rho, r.P.NX, r.P.NY, 360)))
		}
		b.w(`</div>`)
	}
	b.w(`<h2>Convergence</h2>` + lineChart(r.Compl))
	return Page("Girder topology optimisation", "SIMP compliance minimisation with density filter and optimality-criteria update", b.String())
}

type stringsBuilder struct{ s []byte }

func (b *stringsBuilder) w(x string)     { b.s = append(b.s, x...) }
func (b *stringsBuilder) String() string { return string(b.s) }

// lineChart draws a small log-y SVG line chart.
func lineChart(v []float64) string {
	const W, H = 720.0, 220.0
	lo, hi := math.Inf(1), math.Inf(-1)
	for _, x := range v {
		lo, hi = math.Min(lo, math.Log10(x)), math.Max(hi, math.Log10(x))
	}
	if hi-lo < 1e-9 {
		hi = lo + 1
	}
	pts := ""
	for i, x := range v {
		px := 50 + (W-70)*float64(i)/math.Max(1, float64(len(v)-1))
		py := 15 + (H-45)*(1-(math.Log10(x)-lo)/(hi-lo))
		pts += fmt.Sprintf("%.1f,%.1f ", px, py)
	}
	return fmt.Sprintf(`<figure><svg viewBox="0 0 %.0f %.0f" role="img" aria-label="compliance history"><polyline fill="none" stroke="var(--accent)" stroke-width="2.2" points="%s"/><line x1="50" y1="%.0f" x2="%.0f" y2="%.0f" stroke="var(--line)"/><text class="tick" x="50" y="%.0f">iteration 1 → %d</text><text class="tick" x="4" y="22">%.3g</text><text class="tick" x="4" y="%.0f">%.3g</text><text class="tick" x="%.0f" y="%.0f" text-anchor="end">compliance (log scale)</text></svg></figure>`,
		W, H, pts, H-30, W-20, H-30, H-10, len(v), math.Pow(10, hi), H-32, math.Pow(10, lo), W-20, H-10)
}
