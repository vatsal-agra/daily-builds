// Command tide is the Tide time-series database: server, tools and benchmark.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"math"
	"net/http"
	"os"
	"os/signal"
	"sort"
	"strings"
	"syscall"
	"text/tabwriter"
	"time"

	"tide/internal/gen"
	"tide/internal/query"
	"tide/internal/server"
	"tide/internal/store"
)

const usage = `tide — a small time-series database

usage:
  tide serve  [-dir DIR] [-addr :8428] [-retention 30d] [-compact-every 1h] [-alerts FILE] [-demo]
  tide gen    [-dir DIR] [-hosts N] [-hours H] [-interval 10s] [-seed N]
  tide query  [-dir DIR] [-now TIME] 'sum(rate(http_requests_total)) by (host) range 1h'
  tide stats  [-dir DIR]
  tide bench  [-series N] [-samples N]
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "serve":
		err = cmdServe(os.Args[2:])
	case "gen":
		err = cmdGen(os.Args[2:])
	case "query":
		err = cmdQuery(os.Args[2:])
	case "stats":
		err = cmdStats(os.Args[2:])
	case "bench":
		err = cmdBench(os.Args[2:])
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "tide: unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "tide:", err)
		os.Exit(1)
	}
}

func cmdServe(args []string) error {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	dir := fs.String("dir", "./tide-data", "data directory")
	addr := fs.String("addr", "127.0.0.1:8428", "listen address")
	retention := fs.Duration("retention", 0, "drop blocks older than this (e.g. 720h); 0 = keep forever")
	compactEvery := fs.Duration("compact-every", time.Hour, "merge blocks this often; 0 disables")
	alertFile := fs.String("alerts", "", "alert rules file")
	demo := fs.Bool("demo", false, "seed 3h of synthetic fleet metrics and keep feeding live data")
	fs.Parse(args)

	st, err := store.Open(store.Options{Dir: *dir})
	if err != nil {
		return err
	}
	stats := st.Stats()
	fmt.Printf("tide: opened %s — %d series, %d samples (%d recovered from WAL, %d torn bytes dropped)\n",
		*dir, stats.Series, stats.TotalSamples, stats.RecoveredWAL, stats.WALTornBytes)

	srv := server.New(st)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if *alertFile != "" {
		am, err := server.LoadAlerts(*alertFile, st)
		if err != nil {
			return err
		}
		srv.Alerts = am
		go am.Run(ctx, srv.Now)
		fmt.Printf("tide: %d alert rules loaded from %s\n", am.RuleCount(), *alertFile)
	}
	if *demo {
		if err := startDemo(ctx, st); err != nil {
			return err
		}
	}
	go maintenance(ctx, st, *compactEvery, *retention)

	hs := &http.Server{Addr: *addr, Handler: srv.Handler(), ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 2 * time.Minute, IdleTimeout: 2 * time.Minute}
	errc := make(chan error, 1)
	go func() { errc <- hs.ListenAndServe() }()
	fmt.Printf("tide: dashboard on http://%s\n", *addr)
	select {
	case err := <-errc:
		st.Close()
		return err
	case <-ctx.Done():
	}
	sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	hs.Shutdown(sctx)
	// No flush here: the WAL already holds the head durably, and flushing on
	// every restart would litter the data dir with tiny blocks.
	fmt.Println("tide: shutting down (head is durable in the WAL)")
	return st.Close()
}

func maintenance(ctx context.Context, st *store.Store, compactEvery, retention time.Duration) {
	t := time.NewTicker(time.Minute)
	defer t.Stop()
	last := time.Now()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-t.C:
			if retention > 0 {
				if n, err := st.DropBefore(now.Add(-retention).UnixMilli()); err != nil {
					fmt.Fprintln(os.Stderr, "tide: retention:", err)
				} else if n > 0 {
					fmt.Printf("tide: retention dropped %d block(s)\n", n)
				}
			}
			if compactEvery > 0 && now.Sub(last) >= compactEvery {
				last = now
				if res, err := st.Compact(); err != nil {
					fmt.Fprintln(os.Stderr, "tide: compaction:", err)
				} else if res.BlocksBefore > 1 {
					fmt.Printf("tide: compacted %d blocks -> 1 (%d dup samples removed)\n", res.BlocksBefore, res.Duplicates)
				}
			}
		}
	}
}

func startDemo(ctx context.Context, st *store.Store) error {
	const interval = 5000
	hist := int64(3 * 3600 * 1000)
	// Resume after the newest stored sample so restarts don't re-insert history.
	now := time.Now().UnixMilli()
	start := now - hist
	if _, mx, ok := st.TimeRange(); ok && mx+interval > start {
		start = mx + interval
	}
	g := gen.New(gen.Config{Hosts: 6, Start: start, Interval: interval, Seed: 42})
	n := 0
	for t := start; t <= now; t += interval {
		res, err := st.Append(g.Next())
		if err != nil {
			return err
		}
		n += res.Accepted
	}
	fmt.Printf("tide: demo data seeded (%d samples)\n", n)
	go func() {
		tk := time.NewTicker(interval * time.Millisecond)
		defer tk.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-tk.C:
				if _, err := st.Append(g.Next()); err != nil {
					fmt.Fprintln(os.Stderr, "tide: demo feed:", err)
				}
			}
		}
	}()
	return nil
}

func cmdGen(args []string) error {
	fs := flag.NewFlagSet("gen", flag.ExitOnError)
	dir := fs.String("dir", "./tide-data", "data directory")
	hosts := fs.Int("hosts", 6, "number of hosts")
	hours := fs.Float64("hours", 24, "hours of history ending now")
	interval := fs.Duration("interval", 10*time.Second, "scrape interval")
	seed := fs.Int64("seed", 1, "random seed")
	fs.Parse(args)
	if *hours <= 0 || *interval < time.Millisecond || *hosts <= 0 {
		return errors.New("hosts, hours and interval must be positive")
	}
	st, err := store.Open(store.Options{Dir: *dir})
	if err != nil {
		return err
	}
	defer st.Close()
	end := time.Now().UnixMilli()
	start := end - int64(*hours*3600*1000)
	if _, mx, ok := st.TimeRange(); ok && mx >= start {
		start = mx + interval.Milliseconds()
	}
	g := gen.New(gen.Config{Hosts: *hosts, Start: start, Interval: interval.Milliseconds(), Seed: *seed})
	t0 := time.Now()
	total := 0
	for t := start; t <= end; t += interval.Milliseconds() {
		res, err := st.Append(g.Next())
		if err != nil {
			return err
		}
		total += res.Accepted
	}
	if err := st.Flush(); err != nil {
		return err
	}
	fmt.Printf("generated %d samples in %s\n", total, time.Since(t0).Round(time.Millisecond))
	printStats(st.Stats())
	return nil
}

func cmdStats(args []string) error {
	fs := flag.NewFlagSet("stats", flag.ExitOnError)
	dir := fs.String("dir", "./tide-data", "data directory")
	fs.Parse(args)
	st, err := store.Open(store.Options{Dir: *dir})
	if err != nil {
		return err
	}
	defer st.Close()
	printStats(st.Stats())
	return nil
}

func printStats(s store.Stats) {
	fmt.Printf("series          %d\n", s.Series)
	fmt.Printf("samples         %d (%d in head, %d in %d block(s))\n", s.TotalSamples, s.HeadSamples, s.BlockSamples, s.Blocks)
	fmt.Printf("chunk bytes     %d\n", s.HeadChunkBytes+int(s.BlockChunkBytes))
	fmt.Printf("bytes/sample    %.3f (raw = 16)\n", s.BytesPerSample)
	fmt.Printf("compression     %.1fx\n", s.CompressionX)
	if s.TotalSamples > 0 {
		fmt.Printf("time range      %s .. %s\n", time.UnixMilli(s.MinT).UTC().Format(time.RFC3339), time.UnixMilli(s.MaxT).UTC().Format(time.RFC3339))
	}
}

func cmdQuery(args []string) error {
	fs := flag.NewFlagSet("query", flag.ExitOnError)
	dir := fs.String("dir", "./tide-data", "data directory")
	fs.Parse(args)
	if fs.NArg() != 1 {
		return errors.New("query: exactly one expression required")
	}
	q, err := query.Parse(fs.Arg(0))
	if err != nil {
		return err
	}
	st, err := store.Open(store.Options{Dir: *dir})
	if err != nil {
		return err
	}
	defer st.Close()
	t0 := time.Now()
	res, err := query.Eval(q, st, time.Now())
	if err != nil {
		return err
	}
	elapsed := time.Since(t0)
	if len(res.Series) == 0 {
		fmt.Println("(no data)")
		return nil
	}
	sort.Slice(res.Series, func(i, j int) bool { return res.Series[i].Name < res.Series[j].Name })
	tw := tabwriter.NewWriter(os.Stdout, 0, 4, 2, ' ', 0)
	for _, s := range res.Series {
		n := len(s.Points)
		mn, mx, sum := math.Inf(1), math.Inf(-1), 0.0
		for _, p := range s.Points {
			mn, mx, sum = math.Min(mn, p.V), math.Max(mx, p.V), sum+p.V
		}
		last := s.Points[n-1]
		fmt.Fprintf(tw, "%s\t%d pts\tmin %.4g\tavg %.4g\tmax %.4g\tlast %.4g @ %s\n", s.Name, n, mn, sum/float64(n), mx, last.V,
			time.UnixMilli(last.T).UTC().Format("15:04:05"))
	}
	tw.Flush()
	fmt.Printf("\n%d series, %s, evaluated in %s\n", len(res.Series), q.Describe(), elapsed.Round(time.Microsecond))
	return nil
}

func cmdBench(args []string) error {
	fs := flag.NewFlagSet("bench", flag.ExitOnError)
	series := fs.Int("series", 200, "number of series (hosts*9)")
	samples := fs.Int("samples", 2000, "samples per series")
	fs.Parse(args)
	dir, err := os.MkdirTemp("", "tide-bench-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(dir)
	st, err := store.Open(store.Options{Dir: dir})
	if err != nil {
		return err
	}
	defer st.Close()
	hosts := (*series + 8) / 9
	start := time.Now().UnixMilli() - int64(*samples)*10_000
	g := gen.New(gen.Config{Hosts: hosts, Start: start, Interval: 10_000, Seed: 7})
	t0 := time.Now()
	total := 0
	for i := 0; i < *samples; i++ {
		res, err := st.Append(g.Next())
		if err != nil {
			return err
		}
		total += res.Accepted
	}
	ing := time.Since(t0)
	fmt.Printf("ingest   %d samples in %s (%.0f samples/s, one fsync per tick of %d points)\n", total, ing.Round(time.Millisecond), float64(total)/ing.Seconds(), hosts*9)
	t0 = time.Now()
	if err := st.Flush(); err != nil {
		return err
	}
	fmt.Printf("flush    %s\n", time.Since(t0).Round(time.Millisecond))
	s := st.Stats()
	fmt.Printf("storage  %.3f bytes/sample vs 16 raw => %.1fx compression\n", s.BytesPerSample, s.CompressionX)
	for _, qs := range []string{
		`avg(cpu_usage_percent{host="web-01"}) range 6h step 1m at latest`,
		`sum(rate(http_requests_total{code="200"})) by (route) range 6h step 1m at latest`,
		`p99(http_latency_ms) range 6h step 5m at latest`,
		`max(avg(cpu_usage_percent)) by (dc) range 6h step 1m at latest`,
	} {
		q, err := query.Parse(strings.TrimSpace(qs))
		if err != nil {
			return err
		}
		t0 = time.Now()
		res, err := query.Eval(q, st, time.Now())
		if err != nil {
			return err
		}
		fmt.Printf("query    %-12s %3d series  %s\n", time.Since(t0).Round(time.Microsecond), len(res.Series), qs)
	}
	return nil
}
