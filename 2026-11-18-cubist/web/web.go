// Package web renders the HTML player and serves the interactive solver.
package web

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"math/rand"
	"net/http"
	"strings"
	"sync"
	"time"

	"cubist/cube"
)

//go:embed player.html
var playerHTML string

// Solution is the JSON payload shared by the static page and the API.
type Solution struct {
	Start    string   `json:"start"`
	Scramble string   `json:"scramble"`
	Moves    []string `json:"moves"`
	Phase1   int      `json:"phase1"`
	Ms       float64  `json:"ms"`
	Final    string   `json:"final"`
}

// BuildSolution solves c (reached from scramble text, if known) and packages the result.
func BuildSolution(c cube.Cube, scramble string, opt cube.Options) (Solution, error) {
	res, err := cube.Solve(c, opt)
	if err != nil {
		return Solution{}, err
	}
	names := make([]string, len(res.Moves))
	for i, m := range res.Moves {
		names[i] = m.String()
	}
	start := c.Facelets()
	return Solution{
		Start: start, Scramble: scramble, Moves: names, Phase1: res.Phase1,
		Ms:    float64(res.Elapsed.Microseconds()) / 1000,
		Final: cube.PhysicalFaceletsFrom(start, res.Moves),
	}, nil
}

// RenderHTML returns a fully self-contained page that replays sol.
func RenderHTML(sol Solution, serve bool) (string, error) {
	data, err := json.Marshal(sol)
	if err != nil {
		return "", err
	}
	out := strings.Replace(playerHTML, "/*__DATA__*/null", string(data), 1)
	if serve {
		out = strings.Replace(out, "/*__SERVE__*/false", "true", 1)
	}
	return out, nil
}

type solveReq struct {
	Scramble string `json:"scramble"`
	Facelets string `json:"facelets"`
	Random   bool   `json:"random"`
}

// Handler returns the HTTP handler for `cubist serve`.
func Handler(opt cube.Options) http.Handler {
	mux := http.NewServeMux()
	var mu sync.Mutex
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		page, err := RenderHTML(Solution{Start: cube.SolvedFacelets, Moves: []string{}}, true)
		if err != nil {
			http.Error(w, err.Error(), 500)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, page)
	})
	mux.HandleFunc("/api/solve", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fail := func(code int, msg string) {
			w.WriteHeader(code)
			json.NewEncoder(w).Encode(map[string]string{"error": msg})
		}
		if r.Method != http.MethodPost {
			fail(405, "POST only")
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 1<<16)
		var req solveReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			fail(400, "bad JSON: "+err.Error())
			return
		}
		var c cube.Cube
		scr := ""
		switch {
		case req.Random:
			mu.Lock()
			c = cube.RandomState(rng)
			mu.Unlock()
		case strings.TrimSpace(req.Facelets) != "":
			var err error
			if c, err = cube.ParseFacelets(req.Facelets); err != nil {
				fail(422, err.Error())
				return
			}
		case strings.TrimSpace(req.Scramble) != "":
			ms, err := cube.ParseMoves(req.Scramble)
			if err != nil {
				fail(422, err.Error())
				return
			}
			if len(ms) > 500 {
				fail(422, "scramble too long (max 500 moves)")
				return
			}
			c = cube.FromMoves(ms)
			scr = cube.FormatMoves(ms)
		default:
			fail(422, "give a scramble, a facelet string, or random:true")
			return
		}
		o := opt
		if o.TimeLimit == 0 || o.TimeLimit > 3*time.Second {
			o.TimeLimit = 3 * time.Second
		}
		sol, err := BuildSolution(c, scr, o)
		if err != nil {
			fail(422, err.Error())
			return
		}
		if req.Random {
			sol.Scramble = "(random state) " + cube.FormatMoves(cube.InvertSeq(mustParse(sol.Moves)))
		}
		json.NewEncoder(w).Encode(sol)
	})
	return mux
}

func mustParse(names []string) []cube.Move {
	ms, _ := cube.ParseMoves(strings.Join(names, " "))
	return ms
}
