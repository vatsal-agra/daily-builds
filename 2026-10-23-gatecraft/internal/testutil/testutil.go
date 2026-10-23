// Package testutil holds helpers shared by package tests.
package testutil

import (
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/elab"
	"gatecraft/internal/hdl"
)

// Build parses and elaborates src (top inferred unless top != "").
func Build(t testing.TB, src, top string) *aig.AIG {
	t.Helper()
	g, err := Try(src, top)
	if err != nil {
		t.Fatalf("elaboration failed: %v", err)
	}
	return g
}

// Try returns the elaboration error instead of failing.
func Try(src, top string) (*aig.AIG, error) {
	f, err := hdl.Parse("test.v", src)
	if err != nil {
		return nil, err
	}
	return elab.Elaborate([]*hdl.File{f}, elab.Options{Top: top})
}
