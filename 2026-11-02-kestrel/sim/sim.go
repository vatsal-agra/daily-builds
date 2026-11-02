// Package sim generates ground truth and noisy radar detections for tracking scenarios.
package sim

import (
	"fmt"
	"math"
	"sort"

	"kestrel/mat"
	"kestrel/model"
	"kestrel/stat"
)

// Leg is a manoeuvre segment: the target does this from the previous leg's end until Until.
type Leg struct {
	Until  float64
	Omega  float64 // turn rate rad/s (counter-clockwise positive); 0 = straight
	Ax, Ay float64 // constant acceleration m/s²
}

// Target is one simulated object.
type Target struct {
	ID         int
	Born, Dies float64 // active over [Born, Dies]
	X, Y       float64 // position at Born
	VX, VY     float64 // velocity at Born
	Legs       []Leg   // empty = straight line
}

// Radar describes the sensor and its error model.
type Radar struct {
	X, Y        float64
	SigR, SigB  float64 // range (m) and bearing (rad) noise std
	Pd          float64
	ClutterMean float64 // expected false alarms per scan
	RMin, RMax  float64
	BMin, BMax  float64
}

// Scenario bundles everything needed to run a simulation.
type Scenario struct {
	Name, Desc string
	Dt         float64 // scan period
	Duration   float64
	Radar      Radar
	Targets    []Target
}

// ClutterDensity is false alarms per unit (range × bearing) area.
func (r Radar) ClutterDensity() float64 {
	return r.ClutterMean / ((r.RMax - r.RMin) * (r.BMax - r.BMin))
}

// Truth is a target's true state at a scan.
type Truth struct {
	ID           int
	X, Y, VX, VY float64
	Omega        float64
}

// Detection is one radar return. Source is the generating target ID (0 = clutter);
// trackers never see it — only the scorer does.
type Detection struct {
	Z      *mat.M // [range, bearing]
	Source int
}

// Frame is one radar scan.
type Frame struct {
	K     int
	T     float64
	Truth []Truth
	Dets  []Detection
}

func (s *Scenario) Validate() error {
	r := s.Radar
	switch {
	case s.Dt <= 0 || s.Duration <= 0:
		return fmt.Errorf("scenario %q: dt and duration must be positive", s.Name)
	case r.Pd < 0 || r.Pd > 1:
		return fmt.Errorf("scenario %q: Pd %v outside [0,1]", s.Name, r.Pd)
	case r.SigR <= 0 || r.SigB <= 0:
		return fmt.Errorf("scenario %q: radar noise must be positive", s.Name)
	case r.RMax <= r.RMin || r.BMax <= r.BMin:
		return fmt.Errorf("scenario %q: empty surveillance volume", s.Name)
	case r.ClutterMean < 0:
		return fmt.Errorf("scenario %q: negative clutter", s.Name)
	}
	seen := map[int]bool{}
	for _, t := range s.Targets {
		if t.ID <= 0 || seen[t.ID] {
			return fmt.Errorf("scenario %q: target IDs must be unique and > 0 (got %d)", s.Name, t.ID)
		}
		seen[t.ID] = true
		if t.Dies <= t.Born {
			return fmt.Errorf("scenario %q: target %d dies before it is born", s.Name, t.ID)
		}
		prev := t.Born
		for _, l := range t.Legs {
			if l.Until <= prev {
				return fmt.Errorf("scenario %q: target %d legs must have increasing Until", s.Name, t.ID)
			}
			prev = l.Until
		}
	}
	return nil
}

// truthAt integrates target t from Born to time tm with fine sub-steps.
func (t *Target) truthAt(tm float64) Truth {
	x, y, vx, vy, w := t.X, t.Y, t.VX, t.VY, 0.0
	cur := t.Born
	const h = 0.05
	for cur < tm-1e-12 {
		step := math.Min(h, tm-cur)
		var ax, ay float64
		w = 0
		for _, l := range t.Legs {
			if cur < l.Until-1e-12 {
				w, ax, ay = l.Omega, l.Ax, l.Ay
				break
			}
		}
		if w != 0 {
			st := (&model.CT{}).Step(mat.Vec(x, vx, y, vy, w), step)
			x, vx, y, vy = st.D[0], st.D[1], st.D[2], st.D[3]
		} else {
			x += vx*step + ax*step*step/2
			y += vy*step + ay*step*step/2
			vx += ax * step
			vy += ay * step
		}
		cur += step
	}
	// report the turn rate in force at tm
	w = 0
	for _, l := range t.Legs {
		if tm < l.Until-1e-12 {
			w = l.Omega
			break
		}
	}
	return Truth{ID: t.ID, X: x, Y: y, VX: vx, VY: vy, Omega: w}
}

// Run generates all frames deterministically from the seed.
func (s *Scenario) Run(seed int64) ([]Frame, error) {
	if err := s.Validate(); err != nil {
		return nil, err
	}
	rng := stat.NewRNG(seed)
	n := int(math.Floor(s.Duration/s.Dt + 1e-9))
	frames := make([]Frame, 0, n)
	r := s.Radar
	for k := 1; k <= n; k++ {
		tm := float64(k) * s.Dt
		fr := Frame{K: k, T: tm}
		for i := range s.Targets {
			t := &s.Targets[i]
			if tm < t.Born || tm > t.Dies {
				continue
			}
			tr := t.truthAt(tm)
			fr.Truth = append(fr.Truth, tr)
			rho := math.Hypot(tr.X-r.X, tr.Y-r.Y)
			b := math.Atan2(tr.Y-r.Y, tr.X-r.X)
			if rho < r.RMin || rho > r.RMax || b < r.BMin || b > r.BMax {
				continue // outside radar coverage
			}
			if rng.Float() > r.Pd {
				continue
			}
			fr.Dets = append(fr.Dets, Detection{
				Z:      mat.Vec(rho+r.SigR*rng.Norm(), stat.WrapAngle(b+r.SigB*rng.Norm())),
				Source: t.ID,
			})
		}
		for c := rng.Poisson(r.ClutterMean); c > 0; c-- {
			fr.Dets = append(fr.Dets, Detection{
				Z:      mat.Vec(rng.Uniform(r.RMin, r.RMax), rng.Uniform(r.BMin, r.BMax)),
				Source: 0,
			})
		}
		// shuffle so detection order leaks nothing about identity
		for i := len(fr.Dets) - 1; i > 0; i-- {
			j := int(rng.Float() * float64(i+1))
			fr.Dets[i], fr.Dets[j] = fr.Dets[j], fr.Dets[i]
		}
		frames = append(frames, fr)
	}
	return frames, nil
}

// ---------------------------------------------------------------- built-in scenarios

func baseRadar() Radar {
	return Radar{X: 0, Y: 0, SigR: 25, SigB: 0.4 * math.Pi / 180, Pd: 0.95, ClutterMean: 2,
		RMin: 500, RMax: 20000, BMin: -math.Pi, BMax: math.Pi}
}

// polar places a target at range rho / bearing deg with heading deg and speed v.
func polar(id int, rho, bearDeg, headDeg, v, born, dies float64, legs ...Leg) Target {
	b, h := bearDeg*math.Pi/180, headDeg*math.Pi/180
	return Target{ID: id, Born: born, Dies: dies, X: rho * math.Cos(b), Y: rho * math.Sin(b),
		VX: v * math.Cos(h), VY: v * math.Sin(h), Legs: legs}
}

// Scenarios returns the built-in catalogue, sorted by name.
func Scenarios() []Scenario {
	deg := math.Pi / 180
	out := []Scenario{
		{Name: "cruise", Desc: "3 well-separated constant-velocity targets, light clutter — the baseline.",
			Dt: 2, Duration: 120, Radar: baseRadar(),
			Targets: []Target{
				polar(1, 9000, 30, 200, 220, 0, 1e9),
				polar(2, 12000, 140, -40, 180, 0, 1e9),
				polar(3, 7000, -80, 20, 150, 0, 1e9),
			}},
		{Name: "crossing", Desc: "Two targets fly through each other's gates at a shallow angle, then separate.",
			Dt: 2, Duration: 120, Radar: baseRadar(),
			Targets: []Target{
				{ID: 1, Born: 0, Dies: 1e9, X: -6000, Y: 8000, VX: 200, VY: 0},
				{ID: 2, Born: 0, Dies: 1e9, X: 6000, Y: 8100, VX: -195, VY: -5},
			}},
		{Name: "swarm", Desc: "8 targets in a loose formation with heavy clutter (12 false alarms/scan).",
			Dt: 2, Duration: 100, Radar: func() Radar { r := baseRadar(); r.ClutterMean = 12; return r }(),
			Targets: func() []Target {
				var ts []Target
				for i := 0; i < 8; i++ {
					ts = append(ts, Target{ID: i + 1, Born: 0, Dies: 1e9,
						X: -5000 + float64(i%4)*900, Y: 9000 + float64(i/4)*900,
						VX: 180 + 6*float64(i), VY: -10 + 4*float64(i%3)})
				}
				return ts
			}()},
		{Name: "manoeuvre", Desc: "Targets that jink: sustained 3°/s turns and a braking run. Stresses model mismatch.",
			Dt: 2, Duration: 140, Radar: baseRadar(),
			Targets: []Target{
				polar(1, 10000, 20, 180, 200, 0, 1e9, Leg{Until: 40}, Leg{Until: 70, Omega: 3 * deg}, Leg{Until: 1e9}),
				polar(2, 8000, 100, 0, 170, 0, 1e9, Leg{Until: 50}, Leg{Until: 90, Omega: -3 * deg}, Leg{Until: 1e9}),
				polar(3, 11000, -60, 120, 220, 0, 1e9, Leg{Until: 60}, Leg{Until: 100, Ax: -2, Ay: -1}, Leg{Until: 1e9}),
			}},
		{Name: "birthdeath", Desc: "Targets enter and leave mid-run: the tracker must start and end tracks on its own.",
			Dt: 2, Duration: 120, Radar: baseRadar(),
			Targets: []Target{
				polar(1, 9000, 10, 190, 200, 0, 70),
				polar(2, 12000, 120, -30, 190, 20, 120),
				polar(3, 8000, -100, 10, 160, 50, 100),
			}},
		{Name: "dropouts", Desc: "Pd = 0.7 with 4 false alarms/scan: tracks must coast through missed detections.",
			Dt: 2, Duration: 120, Radar: func() Radar { r := baseRadar(); r.Pd = 0.7; r.ClutterMean = 4; return r }(),
			Targets: []Target{
				polar(1, 9000, 30, 200, 220, 0, 1e9),
				polar(2, 12000, 140, -40, 180, 0, 1e9),
			}},
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

// Lookup finds a built-in scenario by name.
func Lookup(name string) (Scenario, error) {
	var names []string
	for _, s := range Scenarios() {
		if s.Name == name {
			return s, nil
		}
		names = append(names, s.Name)
	}
	return Scenario{}, fmt.Errorf("unknown scenario %q (available: %v)", name, names)
}
