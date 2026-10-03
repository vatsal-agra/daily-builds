// Command landmark is a Shazam-style audio fingerprinting toolkit.
package main

import (
	"flag"
	"fmt"
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"landmark/internal/degrade"
	"landmark/internal/engine"
	"landmark/internal/eval"
	"landmark/internal/fp"
	"landmark/internal/index"
	"landmark/internal/synth"
	"landmark/internal/timeline"
	"landmark/internal/viz"
	"landmark/internal/wavio"
)

const usage = `landmark — audio fingerprinting from scratch

usage: landmark <command> [flags]

  synth     compose procedural songs into WAV files
  index     fingerprint WAV files/directories into an index file
  identify  name the song in a WAV clip (and where in the song it starts)
  degrade   damage a WAV (crop, noise, filter, distortion, reverb, speed) to make test queries
  eval      run the robustness benchmark and false-accept test
  mix       splice WAV excerpts into a crossfaded DJ-style test mix
  timeline  segment a long mix into the songs it contains
  viz       write a self-contained HTML report for a query
  info      show what an index file contains
`

func die(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "landmark: "+format+"\n", a...)
	os.Exit(1)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "synth":
		cmdSynth(args)
	case "index":
		cmdIndex(args)
	case "identify":
		cmdIdentify(args)
	case "degrade":
		cmdDegrade(args)
	case "eval":
		cmdEval(args)
	case "mix":
		cmdMix(args)
	case "timeline":
		cmdTimeline(args)
	case "viz":
		cmdViz(args)
	case "info":
		cmdInfo(args)
	case "help", "-h", "--help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "landmark: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
}

func newFlags(name string) *flag.FlagSet {
	return flag.NewFlagSet(name, flag.ExitOnError)
}

// parse accepts flags before, after, or between positional arguments (Go's flag stops at the first
// positional, which makes `identify clip.wav -db x.lmk` fail confusingly). It returns the positionals.
func parse(fs *flag.FlagSet, args []string) []string {
	var pos []string
	for {
		fs.Parse(args)
		args = fs.Args()
		if len(args) == 0 {
			return pos
		}
		pos = append(pos, args[0])
		args = args[1:]
	}
}

func cmdSynth(args []string) {
	fs := newFlags("synth")
	n := fs.Int("n", 8, "number of songs")
	seed := fs.Int64("seed", 1, "first seed (song i uses seed+i)")
	dur := fs.Float64("dur", 60, "seconds per song")
	rate := fs.Int("rate", 22050, "sample rate")
	out := fs.String("out", "corpus", "output directory")
	parse(fs, args)
	if *n < 1 || *dur < 1 || *dur > 900 || *rate < 8000 || *rate > 96000 {
		die("synth: need n>=1, 1<=dur<=900, 8000<=rate<=96000")
	}
	if err := os.MkdirAll(*out, 0o755); err != nil {
		die("%v", err)
	}
	for i := 0; i < *n; i++ {
		s := *seed + int64(i)
		info, x := synth.Generate(s, *dur, *rate)
		path := filepath.Join(*out, fmt.Sprintf("song%04d.wav", s))
		if err := wavio.Write(path, x, *rate); err != nil {
			die("%v", err)
		}
		fmt.Printf("%s  %-22s %5.0f bpm  %-14s %4.0fs\n", path, info.Name, info.BPM, info.Key, info.Duration)
	}
}

func wavFiles(paths []string) ([]string, error) {
	var out []string
	for _, p := range paths {
		st, err := os.Stat(p)
		if err != nil {
			return nil, err
		}
		if !st.IsDir() {
			out = append(out, p)
			continue
		}
		ents, err := os.ReadDir(p)
		if err != nil {
			return nil, err
		}
		for _, e := range ents {
			if !e.IsDir() && strings.EqualFold(filepath.Ext(e.Name()), ".wav") {
				out = append(out, filepath.Join(p, e.Name()))
			}
		}
	}
	sort.Strings(out)
	return out, nil
}

func songName(path string) string {
	return strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
}

func cmdIndex(args []string) {
	fs := newFlags("index")
	out := fs.String("out", "library.lmk", "index file to write")
	add := fs.Bool("add", false, "extend an existing index instead of starting fresh")
	paths := parse(fs, args)
	if len(paths) == 0 {
		die("index: give at least one WAV file or directory")
	}
	files, err := wavFiles(paths)
	if err != nil {
		die("%v", err)
	}
	if len(files) == 0 {
		die("index: no .wav files found")
	}
	ix := index.New(fp.Default())
	if *add {
		if ix, err = index.Load(*out); err != nil {
			die("%v", err)
		}
	}
	t0 := time.Now()
	for _, f := range files {
		x, rate, err := wavio.Read(f)
		if err != nil {
			die("%v", err)
		}
		if *add && ix.Has(songName(f)) {
			fmt.Printf("  = %-24s already indexed, skipped\n", songName(f))
			continue
		}
		s, err := engine.Add(ix, songName(f), x, rate)
		if err != nil {
			die("%s: %v", f, err)
		}
		fmt.Printf("  + %-24s %6.1fs  %6d landmarks\n", s.Name, float64(len(x))/float64(rate), s.Hashes)
	}
	if err := ix.Save(*out); err != nil {
		die("%v", err)
	}
	fmt.Printf("wrote %s: %d songs, %d distinct hashes (%.2fs)\n", *out, len(ix.Songs), ix.NumKeys(), time.Since(t0).Seconds())
}

func loadIndex(path string) *index.Index {
	ix, err := index.Load(path)
	if err != nil {
		die("%v", err)
	}
	return ix
}

func speedFlags(fs *flag.FlagSet) (*float64, *float64) {
	return fs.Float64("speed", 0, "search playback-speed changes up to ±this fraction (e.g. 0.06); 0 = off"),
		fs.Float64("speed-step", 0.005, "speed search step")
}

func cmdIdentify(args []string) {
	fs := newFlags("identify")
	db := fs.String("db", "library.lmk", "index file")
	sp, st := speedFlags(fs)
	minScore := fs.Int("min-score", index.DefaultPolicy().MinScore, "minimum aligned votes to accept")
	top := fs.Int("top", 3, "show this many candidates")
	pos := parse(fs, args)
	if len(pos) != 1 {
		die("identify: give exactly one WAV clip")
	}
	ix := loadIndex(*db)
	x, rate, err := wavio.Read(pos[0])
	if err != nil {
		die("%v", err)
	}
	pol := index.DefaultPolicy()
	pol.MinScore = *minScore
	t0 := time.Now()
	res, err := engine.Identify(ix, x, rate, pol, engine.SpeedRange{Max: *sp, Step: *st})
	if err != nil {
		die("%v", err)
	}
	fmt.Printf("query: %.1fs, %d peaks, %d landmarks (%.2fs)\n", float64(len(x))/float64(rate), res.Peaks, res.Hashes, time.Since(t0).Seconds())
	for i, m := range res.Matches {
		if i >= *top {
			break
		}
		fmt.Printf("  #%d %-26s votes %-4d offset %6.2fs  (%d raw collisions, best rival offset %d)\n", i+1, m.Song.Name, m.Score, m.OffsetSec, m.Hits, m.Alt)
	}
	if res.Hashes == 0 {
		fmt.Println("NO MATCH — no usable landmarks: the clip is silent, too quiet, or shorter than ~1.5 s")
		os.Exit(3)
	}
	if !res.Found {
		fmt.Printf("NO MATCH — %s\n", res.Reason)
		os.Exit(3)
	}
	extra := ""
	if res.Speed != 1 {
		extra = fmt.Sprintf(", playback speed ×%.3f", res.Speed)
	}
	fmt.Printf("MATCH  %s — clip starts at %.2fs into the song%s (confidence %.0f%%)\n",
		res.Best.Song.Name, res.Best.OffsetSec, extra, 100*res.Confidence)
	if res.OffsetAmbiguous {
		fmt.Println("       note: the clip sits in repeated material, so that start time may be one of several equally good alignments")
	}
}

func cmdDegrade(args []string) {
	fs := newFlags("degrade")
	in := fs.String("in", "", "input WAV")
	out := fs.String("out", "query.wav", "output WAV")
	start := fs.Float64("start", 0, "crop start (s)")
	length := fs.Float64("len", 0, "crop length (s); 0 = to the end")
	snr := fs.Float64("snr", 0, "add noise at this SNR in dB (only when the flag is given)")
	pink := fs.Bool("pink", false, "use pink instead of white noise")
	lp := fs.Float64("lowpass", 0, "low-pass cutoff in Hz (0 = off)")
	drive := fs.Float64("distort", 0, "tanh distortion drive (0 = off)")
	rev := fs.Float64("reverb", 0, "reverb wet level 0..1 (0 = off)")
	gain := fs.Float64("gain", 0, "gain in dB")
	speed := fs.Float64("speed", 1, "playback speed factor (1 = off)")
	seed := fs.Int64("seed", 1, "random seed")
	parse(fs, args)
	snrSet := false
	fs.Visit(func(f *flag.Flag) { snrSet = snrSet || f.Name == "snr" })
	if *in == "" {
		die("degrade: -in is required")
	}
	x, rate, err := wavio.Read(*in)
	if err != nil {
		die("%v", err)
	}
	rng := rand.New(rand.NewSource(*seed))
	if *start < 0 || *length < 0 {
		die("degrade: -start and -len must be >= 0")
	}
	l := *length
	if l == 0 {
		l = float64(len(x))/float64(rate) - *start
	}
	x = degrade.Crop(x, rate, *start, l)
	if len(x) == 0 {
		die("degrade: crop is empty (start beyond end of file?)")
	}
	if *lp > 0 {
		x = degrade.Lowpass(x, rate, *lp)
	}
	if *drive > 0 {
		x = degrade.Distort(x, *drive)
	}
	if *rev > 0 {
		x = degrade.Reverb(x, rate, *rev, rng)
	}
	if snrSet {
		x = degrade.Noise(x, *snr, *pink, rng)
	}
	if *speed != 1 {
		if *speed <= 0.2 || *speed > 5 {
			die("degrade: -speed must be within (0.2, 5]")
		}
		x = degrade.Speed(x, *speed)
	}
	if *gain != 0 {
		x = degrade.Gain(x, *gain)
	}
	if err := wavio.Write(*out, x, rate); err != nil {
		die("%v", err)
	}
	fmt.Printf("wrote %s (%.1fs)\n", *out, float64(len(x))/float64(rate))
}

func cmdEval(args []string) {
	fs := newFlags("eval")
	songs := fs.Int("songs", 40, "indexed songs")
	negs := fs.Int("negatives", 8, "unindexed songs for the false-accept test")
	secs := fs.Float64("dur", 60, "seconds per song")
	trials := fs.Int("trials", 30, "trials per table cell")
	seed := fs.Int64("seed", 42, "random seed")
	only := fs.String("only", "", "run only conditions containing this text")
	md := fs.String("md", "", "also write the markdown table to this file")
	parse(fs, args)
	if *songs < 2 || *trials < 1 || *secs < 20 {
		die("eval: need songs>=2, trials>=1, dur>=20")
	}
	t0 := time.Now()
	rep, err := eval.Run(eval.Config{Songs: *songs, Negatives: *negs, SongSeconds: *secs, GenRate: 22050,
		ClipLens: []float64{5, 10}, Trials: *trials, Seed: *seed, Policy: index.DefaultPolicy(), Only: *only,
		Log: func(s string) { fmt.Fprintln(os.Stderr, s) }})
	if err != nil {
		die("%v", err)
	}
	fmt.Print(rep.Markdown)
	fmt.Printf("\n(elapsed %.1fs)\n", time.Since(t0).Seconds())
	if *md != "" {
		if err := os.WriteFile(*md, []byte(rep.Markdown), 0o644); err != nil {
			die("%v", err)
		}
	}
}

func cmdInfo(args []string) {
	fs := newFlags("info")
	db := fs.String("db", "library.lmk", "index file")
	parse(fs, args)
	ix := loadIndex(*db)
	p := ix.Params
	fmt.Printf("%s: %d songs, %d distinct hashes\nparams: %d Hz, FFT %d, hop %d (%.0f ms/frame), bins %d–%d, fan-out %d\n",
		*db, len(ix.Songs), ix.NumKeys(), p.Rate, p.NFFT, p.Hop, 1000*p.FrameSeconds(), p.MinBin, p.MaxBin, p.Fan)
	for _, s := range ix.Songs {
		fmt.Printf("  %3d  %-28s %6.1fs  %6d landmarks\n", s.ID, s.Name, float64(s.Frames)*p.FrameSeconds(), s.Hashes)
	}
}

func parseSpan(spec string) (string, float64, float64, error) {
	i := strings.LastIndex(spec, ":")
	if i < 0 {
		return spec, 0, 0, nil // whole file
	}
	var a, b float64
	if n, err := fmt.Sscanf(spec[i+1:], "%f-%f", &a, &b); err != nil || n != 2 || a < 0 || b <= a {
		return "", 0, 0, fmt.Errorf("bad span %q (want file.wav:START-END in seconds)", spec)
	}
	return spec[:i], a, b, nil
}

func cmdMix(args []string) {
	fs := newFlags("mix")
	out := fs.String("out", "mix.wav", "output WAV")
	xf := fs.Float64("fade", 1.5, "crossfade seconds between tracks")
	snr := fs.Float64("snr", 0, "add white noise at this SNR in dB (only when given)")
	seed := fs.Int64("seed", 1, "noise seed")
	spans := parse(fs, args)
	snrSet := false
	fs.Visit(func(f *flag.Flag) { snrSet = snrSet || f.Name == "snr" })
	if len(spans) < 2 {
		die("mix: give at least two tracks as file.wav:START-END")
	}
	var mix []float64
	mixRate := 0
	for _, sp := range spans {
		path, a, b, err := parseSpan(sp)
		if err != nil {
			die("%v", err)
		}
		x, rate, err := wavio.Read(path)
		if err != nil {
			die("%v", err)
		}
		if mixRate == 0 {
			mixRate = rate
		} else if rate != mixRate {
			die("mix: all tracks must share one sample rate (%d vs %d)", mixRate, rate)
		}
		if b == 0 {
			b = float64(len(x)) / float64(rate)
		}
		seg := degrade.Crop(x, rate, a, b-a)
		if len(seg) == 0 {
			die("mix: span %q is empty", sp)
		}
		mix = crossfade(mix, seg, int(*xf*float64(rate)))
	}
	if snrSet {
		mix = degrade.Noise(mix, *snr, false, rand.New(rand.NewSource(*seed)))
	}
	if err := wavio.Write(*out, mix, mixRate); err != nil {
		die("%v", err)
	}
	fmt.Printf("wrote %s (%.1fs, %d tracks)\n", *out, float64(len(mix))/float64(mixRate), len(spans))
}

// crossfade appends b to a, overlapping n samples with an equal-power fade.
func crossfade(a, b []float64, n int) []float64 {
	if len(a) == 0 {
		return append([]float64(nil), b...)
	}
	if n > len(a) {
		n = len(a)
	}
	if n > len(b) {
		n = len(b)
	}
	out := append([]float64(nil), a...)
	for i := 0; i < n; i++ {
		t := float64(i) / float64(n)
		k := len(a) - n + i
		out[k] = a[k]*math.Cos(t*math.Pi/2) + b[i]*math.Sin(t*math.Pi/2)
	}
	return append(out, b[n:]...)
}

func cmdTimeline(args []string) {
	fs := newFlags("timeline")
	db := fs.String("db", "library.lmk", "index file")
	win := fs.Float64("win", 8, "analysis window (s)")
	step := fs.Float64("step", 2, "window step (s)")
	sp, st := speedFlags(fs)
	pos := parse(fs, args)
	if len(pos) != 1 {
		die("timeline: give exactly one WAV recording")
	}
	ix := loadIndex(*db)
	x, rate, err := wavio.Read(pos[0])
	if err != nil {
		die("%v", err)
	}
	cfg := timeline.Default()
	cfg.Window, cfg.Step = *win, *step
	cfg.Speed = engine.SpeedRange{Max: *sp, Step: *st}
	t0 := time.Now()
	segs, err := timeline.Run(ix, x, rate, cfg)
	if err != nil {
		die("%v", err)
	}
	fmt.Printf("%.1fs recording, %.1fs windows every %.1fs (%.1fs)\n\n", float64(len(x))/float64(rate), *win, *step, time.Since(t0).Seconds())
	fmt.Printf("  %-13s %-26s %s\n", "mix time", "song", "song position at segment start")
	for _, s := range segs {
		name, at := "— unidentified —", ""
		if s.Known {
			name, at = s.Song.Name, fmt.Sprintf("%.1fs", s.SongStart)
		}
		fmt.Printf("  %5.1f–%-6.1f %-26s %s\n", s.Start, s.End, name, at)
	}
}

func cmdViz(args []string) {
	fs := newFlags("viz")
	db := fs.String("db", "library.lmk", "index file")
	out := fs.String("out", "report.html", "output HTML file")
	sp, st := speedFlags(fs)
	pos := parse(fs, args)
	if len(pos) != 1 {
		die("viz: give exactly one WAV clip")
	}
	ix := loadIndex(*db)
	x, rate, err := wavio.Read(pos[0])
	if err != nil {
		die("%v", err)
	}
	const maxSec = 30
	if float64(len(x))/float64(rate) > maxSec {
		x = x[:maxSec*rate]
		fmt.Printf("note: clip truncated to the first %d s for the report\n", maxSec)
	}
	res, err := engine.Identify(ix, x, rate, index.DefaultPolicy(), engine.SpeedRange{Max: *sp, Step: *st})
	if err != nil {
		die("%v", err)
	}
	html, err := viz.Render(ix, x, rate, res, filepath.Base(pos[0]))
	if err != nil {
		die("%v", err)
	}
	if err := os.WriteFile(*out, []byte(html), 0o644); err != nil {
		die("%v", err)
	}
	fmt.Printf("wrote %s (%d KB)\n", *out, len(html)/1024)
}
