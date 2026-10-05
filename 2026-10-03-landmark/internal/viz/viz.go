// Package viz renders a self-contained HTML report explaining how a query was (or was not) identified.
package viz

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"html"
	"math"
	"sort"
	"strings"

	"landmark/internal/engine"
	"landmark/internal/fp"
	"landmark/internal/index"
)

type pairJS struct {
	A, B [2]int
	M    bool // pair's hash occurs in the winning song at the winning alignment
}

type scoreJS struct {
	Name  string
	Score int
	Alt   int
}

type payload struct {
	Title     string
	Frames    int
	Bins      int
	MinBin    int
	FrameSec  float64
	BinHz     float64
	Spec      string // base64 uint8 matrix, frames × bins
	Peaks     [][2]int
	Pairs     []pairJS
	Hist      [][2]int // [delta frame, votes]
	BestDelta int
	Scores    []scoreJS
	Found     bool
	Song      string
	OffsetSec float64
	Conf      float64
	Reason    string
	Speed     float64
	Ambiguous bool
	NPeaks    int
	NHashes   int
	NMatched  int
}

// Render builds the report page for the query x (mono, `rate` Hz) given the identification result res.
func Render(ix *index.Index, x []float64, rate int, res engine.Result, title string) (string, error) {
	p := ix.Params
	spec := fp.Spectrogram(x, float64(rate)/res.Speed, p)
	if len(spec) == 0 {
		return "", fmt.Errorf("clip too short to analyse")
	}
	peaks := fp.FindPeaks(spec, p)
	pairs := fp.PairsFan(peaks, p, p.QueryFan)

	hi, lo := p.MaxBin+1, p.MinBin
	if hi > len(spec[0]) {
		hi = len(spec[0])
	}
	ceil := float32(-1e9)
	for _, row := range spec {
		for _, v := range row[lo:hi] {
			if v > ceil {
				ceil = v
			}
		}
	}
	const rangeDB = 75.0
	raw := make([]byte, 0, len(spec)*(hi-lo))
	for _, row := range spec {
		for _, v := range row[lo:hi] {
			u := (float64(v-ceil) + rangeDB) / rangeDB
			raw = append(raw, byte(math.Max(0, math.Min(1, u))*255))
		}
	}

	pl := payload{Title: title, Frames: len(spec), Bins: hi - lo, MinBin: lo, FrameSec: p.FrameSeconds(),
		BinHz: float64(p.Rate) / float64(p.NFFT), Spec: base64.StdEncoding.EncodeToString(raw),
		Found: res.Found, Reason: res.Reason, Speed: res.Speed, Conf: res.Confidence, Ambiguous: res.OffsetAmbiguous,
		NPeaks: len(peaks), NHashes: len(pairs),
		Peaks: [][2]int{}, Pairs: []pairJS{}, Hist: [][2]int{}, Scores: []scoreJS{}} // never null in JSON
	for _, pk := range peaks {
		pl.Peaks = append(pl.Peaks, [2]int{pk.T, pk.F})
	}
	var best *index.Match
	if len(res.Matches) > 0 {
		best = &res.Matches[0]
	}
	if best != nil {
		pl.BestDelta = int(best.Offset)
		pl.Song = best.Song.Name
		pl.OffsetSec = best.OffsetSec
		hist := ix.Histogram(hashes(pairs), best.Song.ID)
		for d, v := range hist {
			pl.Hist = append(pl.Hist, [2]int{int(d), v})
		}
		sort.Slice(pl.Hist, func(i, j int) bool { return pl.Hist[i][0] < pl.Hist[j][0] })
	}
	for i, m := range res.Matches {
		if i >= 6 {
			break
		}
		pl.Scores = append(pl.Scores, scoreJS{m.Song.Name, m.Score, m.Alt})
	}
	for _, pr := range pairs {
		pj := pairJS{A: [2]int{pr.A.T, pr.A.F}, B: [2]int{pr.B.T, pr.B.F}}
		if best != nil && res.Found {
			for _, po := range ix.Lookup(pr.H) {
				d := int(po.T) - int(pr.T) - int(best.Offset)
				if po.Song == best.Song.ID && d >= -1 && d <= 1 {
					pj.M = true
					pl.NMatched++
					break
				}
			}
		}
		pl.Pairs = append(pl.Pairs, pj)
	}
	js, err := json.Marshal(pl)
	if err != nil {
		return "", err
	}
	return strings.Replace(strings.ReplaceAll(page, "__TITLE__", html.EscapeString(title)), "__DATA__", string(js), 1), nil
}

func hashes(ps []fp.Pair) []fp.Hash {
	out := make([]fp.Hash, len(ps))
	for i, p := range ps {
		out[i] = p.Hash
	}
	return out
}
