package main

import (
	"bufio"
	"fmt"
	"io"
	"math"
	"math/rand"
	"strings"
	"time"
)

// Describer lets a game render its states for a human sitting at a seat.
type Describer interface {
	// View describes what `seat` can see (their card, public board, pot, betting so far).
	View(seat int) string
	// Reveal describes everything once the hand is over.
	Reveal() string
}

func narrate(hist string, kuhn bool, seat int) string {
	if hist == "" {
		return "(no actions yet)"
	}
	var parts []string
	rounds := strings.Split(hist, "/")
	for ri, r := range rounds {
		bet := false
		for i := 0; i < len(r); i++ {
			who := "You"
			if i%2 != seat {
				who = "Opponent"
			}
			var act string
			switch r[i] {
			case 'p':
				if bet {
					act = "fold"
				} else {
					act = "check"
				}
			case 'f':
				act = "fold"
			case 'c':
				if bet {
					act = "call"
				} else {
					act = "check"
				}
			case 'b', 'r':
				switch {
				case bet && kuhn:
					act = "call"
				case bet:
					act = "raise"
				default:
					act = "bet"
				}
				bet = true
			}
			if bet && (r[i] == 'c' || r[i] == 'p' || (kuhn && r[i] == 'b' && act == "call")) {
				bet = false
			}
			if who != "You" {
				act += "s"
			}
			parts = append(parts, who+" "+act)
		}
		if ri < len(rounds)-1 {
			parts = append(parts, "| board dealt |")
		}
	}
	return strings.Join(parts, ", ")
}

func (n kuhnNode) View(seat int) string {
	pot := 2 + strings.Count(n.hist, "b") // each bet or call adds one chip
	return fmt.Sprintf("Your card: %s   Pot: %d   Action: %s", kuhnCards[n.c[seat]], pot, narrate(n.hist, true, seat))
}
func (n kuhnNode) Reveal() string {
	return fmt.Sprintf("P0 had %s, P1 had %s", kuhnCards[n.c[0]], kuhnCards[n.c[1]])
}

func (n leducNode) View(seat int) string {
	board := "—"
	if n.board >= 0 {
		board = leducRanks[n.board/2]
	}
	return fmt.Sprintf("Your card: %s   Board: %s   Pot: %d (you put in %d, opponent %d)\n   Action: %s",
		leducRanks[n.hole[seat]/2], board, n.contrib[0]+n.contrib[1], n.contrib[seat], n.contrib[1-seat], narrate(n.hist, false, seat))
}
func (n leducNode) Reveal() string {
	b := "—"
	if n.board >= 0 {
		b = leducRanks[n.board/2]
	}
	return fmt.Sprintf("P0 had %s, P1 had %s, board %s", leducRanks[n.hole[0]/2], leducRanks[n.hole[1]/2], b)
}

// PlayConfig controls an interactive session.
type PlayConfig struct {
	Tree  *Tree
	Game  Game
	Prof  Profile // the opponent's strategy
	Nash  Profile // equilibrium used for hints (defaults to Prof)
	Seat  int     // 0, 1 or -1 to alternate
	Hands int     // 0 = until quit / EOF
	Seed  int64
}

func (c PlayConfig) nash() Profile {
	if c.Nash != nil {
		return c.Nash
	}
	return c.Prof
}

// PlaySession runs the interactive loop. It returns the human's net chips and hands played.
func PlaySession(cfg PlayConfig, in io.Reader, out io.Writer) (float64, int, error) {
	rng := rand.New(rand.NewSource(cfg.Seed))
	sc := bufio.NewScanner(in)
	total, hands := 0.0, 0
	fmt.Fprintf(out, "Playing %s against the solved strategy. Type an action (or its number), 'hint' for the equilibrium advice, 'quit' to stop.\n", cfg.Tree.Game)
	for cfg.Hands == 0 || hands < cfg.Hands {
		seat := cfg.Seat
		if seat < 0 {
			seat = hands % 2
		}
		fmt.Fprintf(out, "\n=== Hand %d — you are P%d ===\n", hands+1, seat)
		n := cfg.Game.Root()
		quit := false
		for !n.Terminal() {
			p := n.Player()
			if p == -1 {
				n = n.Child(sampleChance(rng, n))
				continue
			}
			acts := n.Actions()
			if p != seat {
				si, ok := cfg.Tree.SetIndex(n.InfoSet())
				if !ok {
					return total, hands, fmt.Errorf("internal: unknown info set %q", n.InfoSet())
				}
				a := Sample(rng, cfg.Prof[si])
				fmt.Fprintf(out, "  Opponent %ss.\n", verb(acts[a]))
				n = n.Child(a)
				continue
			}
			si, ok := cfg.Tree.SetIndex(n.InfoSet())
			if !ok {
				return total, hands, fmt.Errorf("internal: unknown info set %q", n.InfoSet())
			}
			fmt.Fprintf(out, "  %s\n", n.(Describer).View(seat))
			chosen := -1
			for chosen < 0 {
				fmt.Fprintf(out, "  your move [%s]> ", optionList(acts))
				if !sc.Scan() {
					if err := sc.Err(); err != nil {
						return total, hands, fmt.Errorf("reading input: %w", err)
					}
					quit = true
					break
				}
				line := strings.ToLower(strings.TrimSpace(sc.Text()))
				switch {
				case line == "":
					continue
				case line == "quit" || line == "q" || line == "exit":
					quit = true
				case line == "hint" || line == "h" || line == "?":
					printHint(out, cfg.Tree, cfg.nash(), si)
					continue
				default:
					chosen = matchAction(acts, line)
					if chosen < 0 {
						fmt.Fprintf(out, "  ? '%s' is not one of: %s\n", line, strings.Join(acts, ", "))
						continue
					}
				}
				break
			}
			if quit {
				break
			}
			fmt.Fprintf(out, "  You %s.\n", verb(acts[chosen]))
			n = n.Child(chosen)
		}
		if quit {
			break
		}
		res := n.Utility()
		if seat == 1 {
			res = -res
		}
		total += res
		hands++
		fmt.Fprintf(out, "  %s.\n  Result: %+g chips. Session: %+g over %d hand(s).\n", n.(Describer).Reveal(), res, total, hands)
	}
	if hands > 0 {
		fmt.Fprintf(out, "\nSession over: %+g chips in %d hand(s) (%+.3f/hand).\n", total, hands, total/float64(hands))
	} else {
		fmt.Fprintln(out, "\nSession over: no hands completed.")
	}
	return total, hands, nil
}

func verb(a string) string {
	switch a {
	case "fold":
		return "fold"
	case "check":
		return "check"
	case "call":
		return "call"
	case "bet":
		return "bet"
	case "raise":
		return "raise"
	}
	return a
}

func optionList(acts []string) string {
	var o []string
	for i, a := range acts {
		o = append(o, fmt.Sprintf("%d:%s", i+1, a))
	}
	return strings.Join(o, " ")
}

func matchAction(acts []string, line string) int {
	for i, a := range acts {
		if line == a || line == fmt.Sprint(i+1) {
			return i
		}
	}
	found := -1
	for i, a := range acts {
		if strings.HasPrefix(a, line) {
			if found >= 0 {
				return -1
			}
			found = i
		}
	}
	return found
}

func sampleChance(rng *rand.Rand, n Node) int {
	k := len(n.Actions())
	x, acc := rng.Float64(), 0.0
	for i := 0; i < k; i++ {
		acc += n.ChanceProb(i)
		if x < acc {
			return i
		}
	}
	return k - 1
}

func printHint(out io.Writer, t *Tree, prof Profile, si int) {
	s := t.Sets[si]
	vals := t.ActionValues(prof, si)
	fmt.Fprintf(out, "  hint — equilibrium play here (info set %s). EV = your expected final result for the hand in chips, antes included:\n", s.Key)
	best := 0
	for a := range vals {
		if vals[a] > vals[best] {
			best = a
		}
	}
	for a, an := range s.Actions {
		mark := " "
		if a == best {
			mark = "*"
		}
		fmt.Fprintf(out, "   %s %-6s mix %5.1f%%   EV %+.3f chips\n", mark, an, 100*prof[si][a], vals[a])
	}
}

// MatchResult summarizes a simulated match.
type MatchResult struct {
	Hands      int
	Mean       float64 // chips/hand won by A (the solved strategy)
	StdErr     float64
	ExactEV    float64 // exact expected chips/hand of A vs B, averaging seats
	Exploitab  float64 // how much a perfect exploiter wins per hand against B
	BRvsB      float64 // = Exploitab (alias kept for output clarity)
	AExploitab float64
}

// Match simulates A vs B for hands hands, alternating seats, and also computes exact values.
func Match(t *Tree, g Game, a, b Profile, hands int, seed int64) (*MatchResult, error) {
	if hands < 1 {
		return nil, fmt.Errorf("hands must be ≥ 1")
	}
	rng := rand.New(rand.NewSource(seed))
	var sum, sq float64
	for h := 0; h < hands; h++ {
		seatA := h % 2
		n := g.Root()
		for !n.Terminal() {
			if n.Player() == -1 {
				n = n.Child(sampleChance(rng, n))
				continue
			}
			si, ok := t.SetIndex(n.InfoSet())
			if !ok {
				return nil, fmt.Errorf("internal: unknown info set %q", n.InfoSet())
			}
			pr := b[si]
			if n.Player() == seatA {
				pr = a[si]
			}
			n = n.Child(Sample(rng, pr))
		}
		u := n.Utility()
		if seatA == 1 {
			u = -u
		}
		sum += u
		sq += u * u
	}
	mean := sum / float64(hands)
	v := sq/float64(hands) - mean*mean
	r := &MatchResult{Hands: hands, Mean: mean, StdErr: math.Sqrt(math.Max(v, 0) / float64(hands))}
	r.ExactEV = (t.Value(t.Compose(a, b)) - t.Value(t.Compose(b, a))) / 2
	r.Exploitab, _, _ = t.Exploitability(b)
	r.AExploitab, _, _ = t.Exploitability(a)
	r.BRvsB = r.Exploitab
	return r, nil
}

func cmdPlay(args []string, out io.Writer, in io.Reader) error {
	fs := newFlags("play")
	spec := fs.String("strategy", "solved", "opponent strategy: solved, bot name, or JSON file")
	iters := fs.Int("iters", 2000, "CFR+ iterations when solving")
	seat := fs.Int("seat", -1, "0 or 1 to fix your seat; -1 alternates")
	hands := fs.Int("hands", 0, "stop after N hands (0 = until you quit)")
	seed := fs.Int64("seed", 0, "RNG seed (0 = random)")
	pos, err := parseInterleaved(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return fmt.Errorf("usage: bluff play <kuhn|leduc> [-strategy S] [-seat 0|1] [-hands N]")
	}
	if *hands < 0 {
		return fmt.Errorf("-hands must be ≥ 0")
	}
	if *iters < 1 {
		return fmt.Errorf("-iters must be ≥ 1")
	}
	if *seat < -1 || *seat > 1 {
		return fmt.Errorf("-seat must be -1, 0 or 1")
	}
	g, t, err := loadGame(pos[0])
	if err != nil {
		return err
	}
	prof, err := ResolveStrategy(t, *spec, *iters)
	if err != nil {
		return err
	}
	nash := prof
	if *spec != "solved" && *spec != "" {
		if nash, err = ResolveStrategy(t, "solved", *iters); err != nil {
			return err
		}
	}
	if *seed == 0 {
		*seed = time.Now().UnixNano()
	}
	_, _, err = PlaySession(PlayConfig{Tree: t, Game: g, Prof: prof, Nash: nash, Seat: *seat, Hands: *hands, Seed: *seed}, in, out)
	return err
}

func cmdMatch(args []string, out io.Writer) error {
	fs := newFlags("match")
	vs := fs.String("vs", "station", "opponent: bot name or strategy JSON")
	hands := fs.Int("hands", 100000, "hands to simulate")
	iters := fs.Int("iters", 2000, "CFR+ iterations for the solved strategy")
	seed := fs.Int64("seed", 1, "RNG seed")
	pos, err := parseInterleaved(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return fmt.Errorf("usage: bluff match <kuhn|leduc> -vs BOT [-hands N]")
	}
	if *iters < 1 {
		return fmt.Errorf("-iters must be ≥ 1")
	}
	g, t, err := loadGame(pos[0])
	if err != nil {
		return err
	}
	a, err := ResolveStrategy(t, "solved", *iters)
	if err != nil {
		return err
	}
	b, err := ResolveStrategy(t, *vs, *iters)
	if err != nil {
		return err
	}
	r, err := Match(t, g, a, b, *hands, *seed)
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "solved CFR+ strategy vs %q in %s, %d hands (seats alternate)\n", *vs, t.Game, r.Hands)
	fmt.Fprintf(out, "  simulated  %+.4f ± %.4f chips/hand\n", r.Mean, r.StdErr)
	fmt.Fprintf(out, "  exact EV   %+.4f chips/hand\n", r.ExactEV)
	fmt.Fprintf(out, "  a perfect exploiter would win %.4f chips/hand from %q; solved strategy is exploitable for only %.5f\n", r.Exploitab, *vs, r.AExploitab)
	return nil
}
