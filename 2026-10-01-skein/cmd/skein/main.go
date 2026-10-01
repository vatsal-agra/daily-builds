// Command skein: streaming probabilistic analytics on the command line.
package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"

	"skein/sketch"
)

var errUsage = errors.New("usage")

const usage = `skein — streaming sketches for data too big to hold

usage: skein <command> [flags] [files...]      ("-" or no file = stdin)

  stats     one pass: distinct keys, top-K, frequencies, value quantiles; -o saves state
  count     distinct lines (HyperLogLog)
  top       heavy hitters (SpaceSaving) with error bounds
  quantile  p50/p90/p99... of numeric lines (t-digest)
  member    build | check | del   — Bloom / cuckoo membership filters
  sim       Jaccard similarity of two files (MinHash)
  dups      near-duplicate lines/documents (MinHash + LSH)
  merge     merge saved sketches built on different shards
  inspect   describe a saved sketch file

run 'skein <command> -h' for flags`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	cmds := map[string]func([]string) error{
		"stats": cmdStats, "count": cmdCount, "top": cmdTop, "quantile": cmdQuantile,
		"member": cmdMember, "sim": cmdSim, "dups": cmdDups, "merge": cmdMerge,
		"inspect": cmdInspect,
	}
	if cmd == "-h" || cmd == "--help" || cmd == "help" {
		fmt.Println(usage)
		return
	}
	fn, ok := cmds[cmd]
	if !ok {
		fmt.Fprintf(os.Stderr, "skein: unknown command %q\n\n%s\n", cmd, usage)
		os.Exit(2)
	}
	if err := fn(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return
		}
		if err == errUsage {
			os.Exit(2)
		}
		fmt.Fprintln(os.Stderr, "skein:", err)
		os.Exit(1)
	}
}

// ---- input plumbing -------------------------------------------------------

type fields struct {
	delim      string
	key, value int
}

func (f *fields) register(fs *flag.FlagSet, wantValue bool) {
	fs.StringVar(&f.delim, "d", "\t", "field delimiter")
	fs.IntVar(&f.key, "f", 0, "key field (1-based; 0 = whole line)")
	if wantValue {
		fs.IntVar(&f.value, "v", 0, "numeric value field (1-based; 0 = whole line is the value)")
	}
}

func (f *fields) pick(line string, n int) (string, bool) {
	if n == 0 {
		return line, true
	}
	parts := strings.Split(line, f.delim)
	if n > len(parts) {
		return "", false
	}
	return parts[n-1], true
}

// forEachLine streams every line of the named files (or stdin) to fn.
// Blank lines are skipped. A missing file is a hard error.
func forEachLine(files []string, fn func(line string) error) error {
	if len(files) == 0 {
		files = []string{"-"}
	}
	for _, name := range files {
		var r io.Reader = os.Stdin
		if name != "-" {
			fh, err := os.Open(name)
			if err != nil {
				return err
			}
			defer fh.Close()
			r = fh
		}
		sc := bufio.NewScanner(r)
		sc.Buffer(make([]byte, 64*1024), 16*1024*1024)
		for sc.Scan() {
			l := strings.TrimRight(sc.Text(), "\r")
			if l == "" {
				continue
			}
			if err := fn(l); err != nil {
				return err
			}
		}
		if err := sc.Err(); err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
	}
	return nil
}

func parseFlags(fs *flag.FlagSet, args []string) error {
	fs.SetOutput(os.Stderr)
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return err
		}
		return errUsage // flag package already printed the message and usage
	}
	return nil
}

func loadSketch(path string) (any, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	v, err := sketch.Unmarshal(b)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return v, nil
}

func saveSketch(path string, v any) error {
	b, err := sketch.Marshal(v)
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func human(n float64) string {
	switch {
	case n >= 1e9:
		return fmt.Sprintf("%.2fG", n/1e9)
	case n >= 1e6:
		return fmt.Sprintf("%.2fM", n/1e6)
	case n >= 1e4:
		return fmt.Sprintf("%.1fk", n/1e3)
	}
	return strconv.FormatFloat(n, 'f', -1, 64)
}

func bytesStr(n int) string {
	switch {
	case n >= 1<<20:
		return fmt.Sprintf("%.1f MiB", float64(n)/(1<<20))
	case n >= 1<<10:
		return fmt.Sprintf("%.1f KiB", float64(n)/(1<<10))
	}
	return fmt.Sprintf("%d B", n)
}

// ---- stats ----------------------------------------------------------------

func parseQuantiles(s string) ([]float64, error) {
	var qs []float64
	for _, p := range strings.Split(s, ",") {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		q, err := strconv.ParseFloat(p, 64)
		if err != nil || !(q >= 0 && q <= 1) {
			return nil, fmt.Errorf("bad quantile %q (want numbers in [0,1])", p)
		}
		qs = append(qs, q)
	}
	if len(qs) == 0 {
		return nil, errors.New("no quantiles given")
	}
	return qs, nil
}

func cmdStats(args []string) error {
	fs := flag.NewFlagSet("stats", flag.ContinueOnError)
	var f fields
	f.register(fs, true)
	cfg := sketch.DefaultBundleConfig()
	fs.IntVar(&cfg.Precision, "p", cfg.Precision, "HyperLogLog precision (4..18)")
	fs.IntVar(&cfg.TopK, "k", cfg.TopK, "heavy hitters to track")
	fs.Float64Var(&cfg.Eps, "eps", cfg.Eps, "count-min error as a fraction of stream length")
	fs.Float64Var(&cfg.Delta, "delta", cfg.Delta, "count-min failure probability")
	qs := fs.String("q", "0.5,0.9,0.99,0.999", "quantiles to report")
	show := fs.Int("show", 10, "heavy hitters to print")
	out := fs.String("o", "", "save sketch state to this file")
	in := fs.String("load", "", "start from a previously saved state (incremental update)")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	quant, err := parseQuantiles(*qs)
	if err != nil {
		return err
	}
	var b *sketch.Bundle
	if *in != "" {
		conflict := ""
		fs.Visit(func(fl *flag.Flag) {
			switch fl.Name {
			case "p", "k", "eps", "delta":
				conflict = fl.Name
			}
		})
		if conflict != "" {
			return fmt.Errorf("-%s cannot be combined with -load: a saved state keeps the parameters it was built with", conflict)
		}
		v, err := loadSketch(*in)
		if err != nil {
			return err
		}
		var ok bool
		if b, ok = v.(*sketch.Bundle); !ok {
			return fmt.Errorf("%s is a %s, not a stats bundle", *in, sketch.Kind(v))
		}
	} else if b, err = sketch.NewBundle(cfg); err != nil {
		return err
	}
	hasVal := f.value != 0
	bad := 0
	err = forEachLine(fs.Args(), func(line string) error {
		key, ok := f.pick(line, f.key)
		if !ok {
			bad++
			return nil
		}
		if !hasVal {
			return b.Observe(key, 0, false)
		}
		raw, ok := f.pick(line, f.value)
		v, perr := strconv.ParseFloat(strings.TrimSpace(raw), 64)
		if !ok || perr != nil {
			bad++
			return nil
		}
		return b.Observe(key, v, true)
	})
	if err != nil {
		return err
	}
	if b.Records == 0 {
		if bad > 0 {
			return fmt.Errorf("no usable records: all %d line(s) were skipped (field out of range or value not numeric; check -d/-f/-v)", bad)
		}
		return errors.New("no input records")
	}
	fmt.Printf("records            %d\n", b.Records)
	fmt.Printf("distinct keys      ≈ %s   (HLL p=%d, ±%.2f%% std error)\n", human(float64(int64(b.Distinct.Estimate()+0.5))), b.Distinct.Precision(), 100*b.Distinct.StdError())
	fmt.Printf("memory             %s HLL + %s CMS + top-%d + %s t-digest\n", bytesStr(b.Distinct.Bytes()), bytesStr(b.Freq.Bytes()), b.Top.K(), bytesStr(b.Dist.Bytes()))
	fmt.Printf("top keys (count ≥ true ≥ count−err; CMS ε·N = %.0f):\n", b.Freq.Epsilon()*float64(b.Freq.Total()))
	for i, e := range b.Top.Top(*show) {
		fmt.Printf("  %2d. %-30s %10d  (±%d)  cms=%d\n", i+1, trunc(e.Key, 30), e.Count, e.Err, b.Freq.Estimate([]byte(e.Key)))
	}
	if b.Dist.Count() > 0 {
		fmt.Printf("values (n=%.0f, min=%.6g, max=%.6g):\n", b.Dist.Count(), b.Dist.Min(), b.Dist.Max())
		for _, q := range quant {
			v, _ := b.Dist.Quantile(q)
			fmt.Printf("  p%-7s %.6g\n", pct(q), v)
		}
	}
	if bad > 0 {
		fmt.Fprintf(os.Stderr, "skein: skipped %d unparsable line(s)\n", bad)
	}
	if *out != "" {
		if err := saveSketch(*out, b); err != nil {
			return err
		}
		fmt.Fprintf(os.Stderr, "saved %s\n", *out)
	}
	return nil
}

// pct renders a quantile as a clean percentile label (0.999 → "99.9", 0.07 → "7").
func pct(q float64) string { return strconv.FormatFloat(math.Round(q*1e8)/1e6, 'f', -1, 64) }

func trunc(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n-1]) + "…"
}

// ---- count / top / quantile ------------------------------------------------

func cmdCount(args []string) error {
	fs := flag.NewFlagSet("count", flag.ContinueOnError)
	var f fields
	f.register(fs, false)
	p := fs.Int("p", 14, "precision (4..18)")
	exact := fs.Bool("exact", false, "also compute the exact count (uses O(n) memory) and show the error")
	out := fs.String("o", "", "save HLL to file")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	h, err := sketch.NewHLL(*p)
	if err != nil {
		return err
	}
	set := map[string]struct{}{}
	n := 0
	err = forEachLine(fs.Args(), func(l string) error {
		k, ok := f.pick(l, f.key)
		if !ok {
			return nil
		}
		n++
		h.AddString(k)
		if *exact {
			set[k] = struct{}{}
		}
		return nil
	})
	if err != nil {
		return err
	}
	est := h.Estimate()
	fmt.Printf("lines %d, distinct ≈ %.0f (±%.2f%%, %s)\n", n, est, 100*h.StdError(), bytesStr(h.Bytes()))
	if *exact {
		t := float64(len(set))
		e := 0.0
		if t > 0 {
			e = (est - t) / t * 100
		}
		fmt.Printf("exact distinct = %d, error %+.3f%%\n", len(set), e)
	}
	if *out != "" {
		return saveSketch(*out, h)
	}
	return nil
}

func cmdTop(args []string) error {
	fs := flag.NewFlagSet("top", flag.ContinueOnError)
	var f fields
	f.register(fs, false)
	k := fs.Int("k", 10, "number of items")
	cap := fs.Int("capacity", 0, "counters to keep (default 10×k, min 100)")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	if *k < 1 {
		return errors.New("-k must be >= 1")
	}
	c := *cap
	if c == 0 {
		c = *k * 10
		if c < 100 {
			c = 100
		}
	}
	if c < *k {
		return errors.New("-capacity must be >= -k")
	}
	s, err := sketch.NewSpaceSaving(c)
	if err != nil {
		return err
	}
	err = forEachLine(fs.Args(), func(l string) error {
		if key, ok := f.pick(l, f.key); ok {
			s.Add(key, 1)
		}
		return nil
	})
	if err != nil {
		return err
	}
	if s.Total() == 0 {
		return errors.New("no input records")
	}
	fmt.Printf("%d records, guaranteed to hold every key with > %d occurrences\n", s.Total(), s.Total()/uint64(c))
	for i, e := range s.Top(*k) {
		fmt.Printf("%3d. %-32s %10d  (true ∈ [%d, %d])\n", i+1, trunc(e.Key, 32), e.Count, e.Count-e.Err, e.Count)
	}
	return nil
}

func cmdQuantile(args []string) error {
	fs := flag.NewFlagSet("quantile", flag.ContinueOnError)
	var f fields
	f.key = 0
	fs.StringVar(&f.delim, "d", "\t", "field delimiter")
	fs.IntVar(&f.key, "v", 0, "value field (1-based; 0 = whole line)")
	qs := fs.String("q", "0.5,0.9,0.95,0.99,0.999", "quantiles")
	exact := fs.Bool("exact", false, "compare against exact quantiles (O(n) memory)")
	comp := fs.Float64("c", 100, "t-digest compression")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	quant, err := parseQuantiles(*qs)
	if err != nil {
		return err
	}
	td, err := sketch.NewTDigest(*comp)
	if err != nil {
		return err
	}
	var all []float64
	bad := 0
	err = forEachLine(fs.Args(), func(l string) error {
		raw, ok := f.pick(l, f.key)
		v, perr := strconv.ParseFloat(strings.TrimSpace(raw), 64)
		if !ok || perr != nil || td.Add(v) != nil {
			bad++
			return nil
		}
		if *exact {
			all = append(all, v)
		}
		return nil
	})
	if err != nil {
		return err
	}
	if td.Count() == 0 {
		return errors.New("no numeric input")
	}
	fmt.Printf("n=%.0f  min=%g  max=%g  (%d centroids, %s)\n", td.Count(), td.Min(), td.Max(), td.Centroids(), bytesStr(td.Bytes()))
	sort.Float64s(all)
	for _, q := range quant {
		v, _ := td.Quantile(q)
		if *exact {
			e := all[int(q*float64(len(all)-1)+0.5)]
			fmt.Printf("  p%-7s %-12.6g exact %-12.6g\n", pct(q), v, e)
		} else {
			fmt.Printf("  p%-7s %.6g\n", pct(q), v)
		}
	}
	if bad > 0 {
		fmt.Fprintf(os.Stderr, "skein: skipped %d non-numeric line(s)\n", bad)
	}
	return nil
}

// ---- member ---------------------------------------------------------------

func cmdMember(args []string) error {
	if len(args) == 0 {
		return errors.New("usage: skein member build|check|del ...")
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "build":
		fs := flag.NewFlagSet("member build", flag.ContinueOnError)
		var f fields
		f.register(fs, false)
		n := fs.Int("n", 0, "expected number of items (required)")
		fp := fs.Float64("fp", 0.01, "target false-positive rate (bloom)")
		cuckoo := fs.Bool("cuckoo", false, "build a cuckoo filter (supports deletion) instead of a bloom filter")
		out := fs.String("o", "", "output file (required)")
		if err := parseFlags(fs, rest); err != nil {
			return err
		}
		if *n < 1 || *out == "" {
			return errors.New("member build needs -n <expected items> and -o <file>")
		}
		var add func(string) error
		dupes := 0
		var v any
		if *cuckoo {
			c, err := sketch.NewCuckoo(*n)
			if err != nil {
				return err
			}
			v, add = c, func(s string) error {
				fresh, err := c.AddUnique([]byte(s))
				if !fresh {
					dupes++
				}
				return err
			}
		} else {
			b, err := sketch.NewBloom(*n, *fp)
			if err != nil {
				return err
			}
			v, add = b, func(s string) error { b.Add([]byte(s)); return nil }
		}
		cnt := 0
		err := forEachLine(fs.Args(), func(l string) error {
			k, ok := f.pick(l, f.key)
			if !ok {
				return nil
			}
			cnt++
			if err := add(k); err != nil {
				return fmt.Errorf("after %d items: %w (raise -n)", cnt, err)
			}
			return nil
		})
		if err != nil {
			return err
		}
		if err := saveSketch(*out, v); err != nil {
			return err
		}
		fmt.Printf("built %s from %d lines → %s (%s)", sketch.Kind(v), cnt, *out, bytesStr(sizeOf(v)))
		if *cuckoo {
			fmt.Printf(", %d distinct keys stored, %d repeats skipped", cnt-dupes, dupes)
		}
		fmt.Println()
		return nil
	case "check", "del":
		fs := flag.NewFlagSet("member "+sub, flag.ContinueOnError)
		if err := parseFlags(fs, rest); err != nil {
			return err
		}
		if fs.NArg() < 2 {
			return fmt.Errorf("usage: skein member %s <filter> <key>... (or - to read keys from stdin)", sub)
		}
		v, err := loadSketch(fs.Arg(0))
		if err != nil {
			return err
		}
		keys := fs.Args()[1:]
		if len(keys) == 1 && keys[0] == "-" {
			keys = nil
			if err := forEachLine(nil, func(l string) error { keys = append(keys, l); return nil }); err != nil {
				return err
			}
		}
		missing := 0
		for _, k := range keys {
			switch x := v.(type) {
			case *sketch.Bloom:
				if sub == "del" {
					return errors.New("bloom filters cannot delete; build with -cuckoo")
				}
				r := x.Contains([]byte(k))
				fmt.Printf("%-40s %s\n", k, map[bool]string{true: "probably present", false: "definitely absent"}[r])
				if !r {
					missing++
				}
			case *sketch.Cuckoo:
				if sub == "del" {
					r := x.Delete([]byte(k))
					fmt.Printf("%-40s %s\n", k, map[bool]string{true: "deleted", false: "not found"}[r])
					if !r {
						missing++
					}
				} else {
					r := x.Contains([]byte(k))
					fmt.Printf("%-40s %s\n", k, map[bool]string{true: "probably present", false: "definitely absent"}[r])
					if !r {
						missing++
					}
				}
			default:
				return fmt.Errorf("%s is a %s, not a membership filter", fs.Arg(0), sketch.Kind(v))
			}
		}
		if sub == "del" {
			if err := saveSketch(fs.Arg(0), v); err != nil {
				return err
			}
		}
		if missing > 0 {
			os.Exit(3) // grep-style: non-zero when something was absent
		}
		return nil
	}
	return fmt.Errorf("unknown member subcommand %q", sub)
}

func sizeOf(v any) int {
	switch x := v.(type) {
	case *sketch.Bloom:
		return x.Bytes()
	case *sketch.Cuckoo:
		return x.Bytes()
	case *sketch.HLL:
		return x.Bytes()
	case *sketch.CMS:
		return x.Bytes()
	case *sketch.TDigest:
		return x.Bytes()
	case *sketch.MinHash:
		return x.Bytes()
	}
	return 0
}

// ---- similarity -----------------------------------------------------------

func readAll(path string) (string, error) {
	var b []byte
	var err error
	if path == "-" {
		b, err = io.ReadAll(os.Stdin)
	} else {
		b, err = os.ReadFile(path)
	}
	return string(b), err
}

func cmdSim(args []string) error {
	fs := flag.NewFlagSet("sim", flag.ContinueOnError)
	k := fs.Int("k", 128, "signature size")
	sh := fs.Int("shingle", 3, "word shingle length")
	exact := fs.Bool("exact", false, "also compute exact Jaccard")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	if fs.NArg() != 2 {
		return errors.New("usage: skein sim [flags] fileA fileB")
	}
	ta, err := readAll(fs.Arg(0))
	if err != nil {
		return err
	}
	tb, err := readAll(fs.Arg(1))
	if err != nil {
		return err
	}
	a, err := sketch.SignatureOf(ta, *k, *sh)
	if err != nil {
		return err
	}
	b, _ := sketch.SignatureOf(tb, *k, *sh)
	if a.Empty() || b.Empty() {
		return errors.New("one of the inputs has no words")
	}
	j, _ := a.Jaccard(b)
	fmt.Printf("estimated Jaccard similarity: %.3f  (k=%d, ±%.3f)\n", j, *k, stderr(j, *k))
	if *exact {
		fmt.Printf("exact Jaccard similarity:     %.3f\n", sketch.ExactJaccard(sketch.Shingles(ta, *sh), sketch.Shingles(tb, *sh)))
	}
	return nil
}

func stderr(j float64, k int) float64 {
	return math.Sqrt(j * (1 - j) / float64(k))
}

func cmdDups(args []string) error {
	fs := flag.NewFlagSet("dups", flag.ContinueOnError)
	var f fields
	f.register(fs, false)
	k := fs.Int("k", 128, "signature size")
	sh := fs.Int("shingle", 2, "word shingle length")
	th := fs.Float64("t", 0.7, "similarity threshold")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	l, err := sketch.NewLSH(*k, *th)
	if err != nil {
		return err
	}
	type doc struct {
		id   string
		text string
	}
	var docs []doc
	text := map[string]string{}
	n := 0
	err = forEachLine(fs.Args(), func(line string) error {
		n++
		t, ok := f.pick(line, f.key)
		if !ok {
			return nil
		}
		id := fmt.Sprintf("line %d", n)
		docs = append(docs, doc{id, t})
		text[id] = t
		return nil
	})
	if err != nil {
		return err
	}
	pairs := 0
	skipped := 0
	for _, d := range docs {
		sig, _ := sketch.SignatureOf(d.text, *k, *sh)
		if sig.Empty() {
			skipped++
			continue
		}
		ms, _ := l.Query(sig, *th)
		for _, m := range ms {
			fmt.Printf("%.2f  %s  ~  %s\n        %q\n        %q\n", m.Jaccard, m.ID, d.id, trunc(text[m.ID], 70), trunc(d.text, 70))
			pairs++
		}
		l.Insert(d.id, sig)
	}
	fmt.Printf("%d documents, %d near-duplicate pair(s) ≥ %.2f (LSH %d bands × %d rows)", len(docs), pairs, *th, l.Bands(), l.Rows())
	if skipped > 0 {
		fmt.Printf(", %d empty skipped", skipped)
	}
	fmt.Println()
	return nil
}
