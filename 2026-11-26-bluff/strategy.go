package main

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"sort"
	"strings"
)

// StratFile is the on-disk form of a strategy.
type StratFile struct {
	Game       string               `json:"game"`
	Iterations int                  `json:"iterations"`
	Exploit    float64              `json:"exploitability"`
	Sets       map[string]*SetStrat `json:"infosets"`
}

// SetStrat is the strategy at one information set.
type SetStrat struct {
	Actions []string  `json:"actions"`
	Probs   []float64 `json:"probs"`
}

// ToFile converts a profile into its serializable form.
func (t *Tree) ToFile(prof Profile, iters int) *StratFile {
	e, _, _ := t.Exploitability(prof)
	f := &StratFile{Game: t.Game, Iterations: iters, Exploit: e, Sets: map[string]*SetStrat{}}
	for i, s := range t.Sets {
		f.Sets[s.Key] = &SetStrat{Actions: s.Actions, Probs: append([]float64(nil), prof[i]...)}
	}
	return f
}

// FromFile converts a stored strategy back into a profile, validating it against the tree.
func (t *Tree) FromFile(f *StratFile) (Profile, error) {
	if f.Game != t.Game {
		return nil, fmt.Errorf("strategy is for %q, not %q", f.Game, t.Game)
	}
	prof := make(Profile, len(t.Sets))
	for i, s := range t.Sets {
		ss, ok := f.Sets[s.Key]
		if !ok {
			return nil, fmt.Errorf("strategy is missing info set %q", s.Key)
		}
		if len(ss.Probs) != len(s.Actions) {
			return nil, fmt.Errorf("info set %q has %d probabilities, want %d", s.Key, len(ss.Probs), len(s.Actions))
		}
		sum := 0.0
		for _, p := range ss.Probs {
			if p < 0 || p != p {
				return nil, fmt.Errorf("info set %q has invalid probability %v", s.Key, p)
			}
			sum += p
		}
		if sum < 0.999 || sum > 1.001 {
			return nil, fmt.Errorf("info set %q probabilities sum to %.4f", s.Key, sum)
		}
		prof[i] = make([]float64, len(ss.Probs))
		for a, p := range ss.Probs {
			prof[i][a] = p / sum
		}
	}
	return prof, nil
}

// SaveStrategy writes a strategy file.
func SaveStrategy(path string, f *StratFile) error {
	b, err := json.MarshalIndent(f, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o644)
}

// LoadStrategy reads a strategy file.
func LoadStrategy(path string) (*StratFile, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var f StratFile
	if err := json.Unmarshal(b, &f); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if f.Game == "" || len(f.Sets) == 0 {
		return nil, fmt.Errorf("%s: not a bluff strategy file", path)
	}
	return &f, nil
}

// Bots are simple scripted opponents defined by action-name preferences.
var botPrefs = map[string][]string{
	"station": {"call", "check"},                 // never folds, never raises
	"maniac":  {"raise", "bet", "call", "check"}, // always puts in the maximum
	"nit":     {"fold", "check"},                 // gives up whenever allowed
	"random":  nil,                               // uniform
}

// BotNames lists the scripted opponents.
func BotNames() []string {
	var n []string
	for k := range botPrefs {
		n = append(n, k)
	}
	sort.Strings(n)
	return n
}

// BotProfile builds a profile playing the named scripted bot.
func (t *Tree) BotProfile(name string) (Profile, error) {
	prefs, ok := botPrefs[name]
	if !ok {
		return nil, fmt.Errorf("unknown bot %q (have: %s)", name, strings.Join(BotNames(), ", "))
	}
	if prefs == nil {
		return t.Uniform(), nil
	}
	prof := make(Profile, len(t.Sets))
	for i, s := range t.Sets {
		prof[i] = make([]float64, len(s.Actions))
		for _, want := range prefs {
			found := false
			for a, an := range s.Actions {
				if an == want {
					prof[i][a] = 1
					found = true
					break
				}
			}
			if found {
				break
			}
		}
	}
	return prof, nil
}

// ResolveStrategy accepts a bot name, a strategy file path, or "solved" (solve now).
func ResolveStrategy(t *Tree, spec string, solveIters int) (Profile, error) {
	if spec == "solved" || spec == "" {
		s := NewSolver(t)
		for k := 0; k < solveIters; k++ {
			s.Step()
		}
		return s.Average(), nil
	}
	if _, ok := botPrefs[spec]; ok {
		return t.BotProfile(spec)
	}
	f, err := LoadStrategy(spec)
	if err != nil {
		return nil, err
	}
	return t.FromFile(f)
}

// Sample draws an action index from a probability vector.
func Sample(r *rand.Rand, p []float64) int {
	x := r.Float64()
	acc := 0.0
	for i, v := range p {
		acc += v
		if x < acc {
			return i
		}
	}
	for i := len(p) - 1; i >= 0; i-- {
		if p[i] > 0 {
			return i
		}
	}
	return 0
}

// GameByName returns a built-in game.
func GameByName(name string) (Game, error) {
	switch strings.ToLower(name) {
	case "kuhn":
		return Kuhn{}, nil
	case "leduc":
		return Leduc{}, nil
	}
	return nil, fmt.Errorf("unknown game %q (have: kuhn, leduc)", name)
}
