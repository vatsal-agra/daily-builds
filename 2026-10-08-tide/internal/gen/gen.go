// Package gen produces a deterministic synthetic fleet workload: CPU gauges
// with diurnal load, memory random walks, monotonically increasing request
// counters (with occasional restarts that reset them), and heavy-tailed
// latency. It exists to exercise and benchmark the database with data that
// has realistic structure, not constant filler.
package gen

import (
	"fmt"
	"math"
	"math/rand"

	"tide/internal/store"
)

type Config struct {
	Hosts    int
	Start    int64 // unix ms of first tick
	Interval int64 // ms between ticks
	Seed     int64
}

type host struct {
	name, dc string
	cpuBase  float64
	mem      float64
	reqs     map[string]float64 // route|code -> counter
	rng      *rand.Rand
}

type Generator struct {
	cfg   Config
	hosts []*host
	tick  int64
}

var routes = []string{"/api/users", "/api/orders", "/healthz"}
var dcs = []string{"eu-west", "us-east", "ap-south"}

func New(cfg Config) *Generator {
	if cfg.Hosts <= 0 {
		cfg.Hosts = 6
	}
	if cfg.Interval <= 0 {
		cfg.Interval = 10_000
	}
	g := &Generator{cfg: cfg}
	root := rand.New(rand.NewSource(cfg.Seed))
	for i := 0; i < cfg.Hosts; i++ {
		h := &host{name: fmt.Sprintf("web-%02d", i+1), dc: dcs[i%len(dcs)],
			cpuBase: 25 + root.Float64()*30, mem: 35 + root.Float64()*30,
			reqs: map[string]float64{}, rng: rand.New(rand.NewSource(cfg.Seed*1000 + int64(i)))}
		g.hosts = append(g.hosts, h)
	}
	return g
}

// Next returns the points for the next tick (one per series).
func (g *Generator) Next() []store.Point {
	t := g.cfg.Start + g.tick*g.cfg.Interval
	g.tick++
	dayFrac := math.Mod(float64(t)/86_400_000, 1)
	diurnal := 0.5 + 0.5*math.Sin(2*math.Pi*(dayFrac-0.3)) // 0..1
	var pts []store.Point
	for _, h := range g.hosts {
		lbl := func(name string, extra ...string) store.Labels {
			m := map[string]string{store.NameLabel: name, "host": h.name, "dc": h.dc}
			for i := 0; i+1 < len(extra); i += 2 {
				m[extra[i]] = extra[i+1]
			}
			return store.NewLabels(m)
		}
		cpu := h.cpuBase*0.6 + 40*diurnal + h.rng.NormFloat64()*3
		// occasional load spike on one host-minute
		if h.rng.Float64() < 0.004 {
			cpu += 25 + h.rng.Float64()*20
		}
		cpu = math.Max(0.5, math.Min(100, cpu))
		pts = append(pts, store.Point{Labels: lbl("cpu_usage_percent"), T: t, V: round(cpu, 2)})

		h.mem += h.rng.NormFloat64() * 0.15
		if h.mem > 92 {
			h.mem = 40 // OOM-kill / restart frees memory
		}
		h.mem = math.Max(20, h.mem)
		pts = append(pts, store.Point{Labels: lbl("mem_used_percent"), T: t, V: round(h.mem, 3)})

		restart := h.rng.Float64() < 0.0008
		for _, rt := range routes {
			load := (30 + 220*diurnal) * float64(len(rt)%5+1) / 3
			for _, code := range []string{"200", "500"} {
				key := rt + "|" + code
				if restart {
					h.reqs[key] = 0
				}
				rate := load
				if code == "500" {
					rate = load * 0.01 * (1 + 4*boolf(cpu > 85))
				}
				n := math.Max(0, rate*float64(g.cfg.Interval)/1000*(1+0.1*h.rng.NormFloat64()))
				h.reqs[key] += math.Round(n)
				pts = append(pts, store.Point{Labels: lbl("http_requests_total", "route", rt, "code", code), T: t, V: h.reqs[key]})
			}
		}
		// lognormal latency, slower when CPU is hot
		lat := math.Exp(3.2+0.45*h.rng.NormFloat64()) * (1 + cpu/150)
		pts = append(pts, store.Point{Labels: lbl("http_latency_ms", "route", "/api/orders"), T: t, V: round(lat, 2)})
	}
	return pts
}

func boolf(b bool) float64 {
	if b {
		return 1
	}
	return 0
}

func round(v float64, places int) float64 {
	p := math.Pow(10, float64(places))
	return math.Round(v*p) / p
}
