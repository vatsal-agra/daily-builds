package main

import (
	"errors"
	"flag"
	"fmt"
	"reflect"

	"skein/sketch"
)

func cmdMerge(args []string) error {
	fs := flag.NewFlagSet("merge", flag.ContinueOnError)
	out := fs.String("o", "", "output file (required)")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	if *out == "" || fs.NArg() < 2 {
		return errors.New("usage: skein merge -o merged.skn a.skn b.skn [more...]")
	}
	acc, err := loadSketch(fs.Arg(0))
	if err != nil {
		return err
	}
	for _, p := range fs.Args()[1:] {
		o, err := loadSketch(p)
		if err != nil {
			return err
		}
		if reflect.TypeOf(acc) != reflect.TypeOf(o) {
			return fmt.Errorf("%s is a %s but %s is a %s: cannot merge", fs.Arg(0), sketch.Kind(acc), p, sketch.Kind(o))
		}
		if err := mergeInto(acc, o); err != nil {
			return fmt.Errorf("%s: %w", p, err)
		}
	}
	if err := saveSketch(*out, acc); err != nil {
		return err
	}
	fmt.Printf("merged %d %s sketches → %s\n", fs.NArg(), sketch.Kind(acc), *out)
	return nil
}

func mergeInto(a, b any) error {
	switch x := a.(type) {
	case *sketch.HLL:
		return x.Merge(b.(*sketch.HLL))
	case *sketch.CMS:
		return x.Merge(b.(*sketch.CMS))
	case *sketch.SpaceSaving:
		return x.Merge(b.(*sketch.SpaceSaving))
	case *sketch.Bloom:
		return x.Merge(b.(*sketch.Bloom))
	case *sketch.TDigest:
		x.Merge(b.(*sketch.TDigest))
		return nil
	case *sketch.MinHash:
		return x.Merge(b.(*sketch.MinHash))
	case *sketch.Bundle:
		return x.Merge(b.(*sketch.Bundle))
	case *sketch.Cuckoo:
		return errors.New("cuckoo filters cannot be merged (use a bloom filter for union)")
	}
	return fmt.Errorf("cannot merge %T", a)
}

func cmdInspect(args []string) error {
	fs := flag.NewFlagSet("inspect", flag.ContinueOnError)
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	if fs.NArg() != 1 {
		return errors.New("usage: skein inspect <file>")
	}
	v, err := loadSketch(fs.Arg(0))
	if err != nil {
		return err
	}
	fmt.Printf("type: %s  (checksum OK)\n", sketch.Kind(v))
	switch x := v.(type) {
	case *sketch.HLL:
		fmt.Printf("precision %d, %d registers, distinct ≈ %.0f ±%.2f%%\n", x.Precision(), x.Bytes(), x.Estimate(), 100*x.StdError())
	case *sketch.CMS:
		fmt.Printf("%d × %d counters (%s), total weight %d, ε=%.5f δ=%.4f\n", x.Width(), x.Depth(), bytesStr(x.Bytes()), x.Total(), x.Epsilon(), x.Delta())
	case *sketch.SpaceSaving:
		fmt.Printf("k=%d, total weight %d\n", x.K(), x.Total())
		for i, e := range x.Top(5) {
			fmt.Printf("  %d. %s %d (±%d)\n", i+1, trunc(e.Key, 30), e.Count, e.Err)
		}
	case *sketch.Bloom:
		fmt.Printf("%d bits (%s), k=%d, %d insertions, fill %.1f%%, distinct ≈ %.0f, current FP rate %.4f%%\n",
			x.Bits(), bytesStr(x.Bytes()), x.K(), x.Added(), 100*x.FillRatio(), x.EstimateCount(), 100*x.FalsePositiveRate())
	case *sketch.Cuckoo:
		fmt.Printf("%d items in %d slots (%.1f%% load), %s\n", x.Len(), x.Capacity(), 100*x.LoadFactor(), bytesStr(x.Bytes()))
	case *sketch.TDigest:
		fmt.Printf("n=%.0f, compression %g, %d centroids, range [%g, %g]\n", x.Count(), x.Compression(), x.Centroids(), x.Min(), x.Max())
	case *sketch.MinHash:
		fmt.Printf("k=%d, empty=%v\n", x.K(), x.Empty())
	case *sketch.Bundle:
		fmt.Printf("records %d; distinct ≈ %.0f; cms %dx%d; top-%d; t-digest n=%.0f\n", x.Records, x.Distinct.Estimate(), x.Freq.Width(), x.Freq.Depth(), x.Top.K(), x.Dist.Count())
	}
	return nil
}
