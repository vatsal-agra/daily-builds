package life

import "sort"

// LibPattern is a built-in pattern with an optional known fact for self-checks.
type LibPattern struct {
	Name, RLE, Rule, Note string
}

var library = []LibPattern{
	{"block", "2o$2o!", "B3/S23", "smallest still life"},
	{"beehive", "b2o$o2bo$b2o!", "B3/S23", "still life"},
	{"blinker", "3o!", "B3/S23", "period-2 oscillator"},
	{"toad", "b3o$3o!", "B3/S23", "period-2 oscillator"},
	{"beacon", "2o2b$2o2b$2b2o$2b2o!", "B3/S23", "period-2 oscillator"},
	{"pentadecathlon", "2bo4bo$2ob4ob2o$2bo4bo!", "B3/S23", "period-15 oscillator"},
	{"glider", "bob$2bo$3o!", "B3/S23", "c/4 diagonal spaceship"},
	{"lwss", "bo2bo$o4b$o3bo$4o!", "B3/S23", "c/2 orthogonal spaceship"},
	{"rpentomino", "b2o$2ob$bo!", "B3/S23", "methuselah: stable at generation 1103 with 116 cells"},
	{"acorn", "bo5b$3bo3b$2o2b3o!", "B3/S23", "methuselah: stable at generation 5206 with 633 cells"},
	{"diehard", "6bob$2o6b$bo3b3o!", "B3/S23", "vanishes at generation 130"},
	{"gosper-gun", "24bo$22bobo$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o$2o8bo3bob2o4bobo$10bo5bo7bo$11bo3bo$12b2o!", "B3/S23", "period-30 glider gun, linear growth"},
	{"highlife-replicator", "3b3o$2bo2bo$bo3bo$o4bo$o3bo$b2o2bo$2bo2b2o!", "B36/S23", "HighLife: copies itself"},
	{"seeds-pair", "2o!", "B2/S", "Seeds: explosive growth"},
}

// Library returns the built-in patterns sorted by name.
func Library() []LibPattern {
	out := append([]LibPattern(nil), library...)
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

// LookupPattern finds a built-in pattern by name.
func LookupPattern(name string) (*Pattern, bool) {
	for _, lp := range library {
		if lp.Name == name {
			p, err := ParseRLE(lp.RLE)
			if err != nil {
				panic("bad built-in pattern " + name + ": " + err.Error())
			}
			p.Name = lp.Name
			p.Rule, p.HasRule = mustRule(lp.Rule), true
			return p, true
		}
	}
	return nil, false
}
