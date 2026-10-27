package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"bayou/internal/bn"
	"bayou/internal/factor"
	"bayou/internal/parse"
)

// loadNet reads a network, choosing BIF vs .bn by extension then by content.
func loadNet(path string) (*bn.Network, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	src := string(b)
	name := filepath.Base(path)
	isBIF := strings.HasSuffix(strings.ToLower(path), ".bif") ||
		(!strings.HasSuffix(strings.ToLower(path), ".bn") && strings.Contains(src, "probability") && strings.Contains(src, "discrete"))
	var n *bn.Network
	if isBIF {
		n, err = parse.ParseBIF(name, src)
	} else {
		n, err = parse.ParseBN(name, src)
	}
	if err != nil {
		return nil, err
	}
	if n.Name == "" {
		n.Name = strings.TrimSuffix(name, filepath.Ext(name))
	}
	return n, nil
}

func needPos(pos []string, n int, what string) error {
	if len(pos) < n {
		return usageError("missing " + what)
	}
	if len(pos) > n {
		return usageError(fmt.Sprintf("unexpected argument %q", pos[n]))
	}
	return nil
}

func writeJSON(w io.Writer, v any) error {
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

// distTable renders a (joint) distribution as rows "A=a B=b  p  bar".
func distTable(w io.Writer, net *bn.Network, f *factor.Factor, indent string) {
	probs := f.Probs()
	type row struct {
		label string
		p     float64
	}
	var rows []row
	cnt := make([]int, len(f.Vars))
	for i := range probs {
		parts := make([]string, len(f.Vars))
		for k, v := range f.Vars {
			parts[k] = net.Vars[v].Name + "=" + net.Vars[v].States[cnt[k]]
		}
		label := strings.Join(parts, " ")
		if len(f.Vars) == 1 {
			label = net.Vars[f.Vars[0]].States[cnt[0]]
		}
		rows = append(rows, row{label, probs[i]})
		for k := len(cnt) - 1; k >= 0; k-- {
			if cnt[k]++; cnt[k] < f.Card[k] {
				break
			}
			cnt[k] = 0
		}
	}
	width := 0
	for _, r := range rows {
		if len(r.label) > width {
			width = len(r.label)
		}
	}
	for _, r := range rows {
		fmt.Fprintf(w, "%s%-*s  %9.6f  %s\n", indent, width, r.label, r.p, bar(r.p, 30))
	}
}

func bar(p float64, width int) string {
	n := int(p*float64(width) + 0.5)
	if n > width {
		n = width
	}
	return strings.Repeat("█", n)
}

func nameList(net *bn.Network, ids []int) []string {
	out := make([]string, len(ids))
	for i, v := range ids {
		out[i] = net.Vars[v].Name
	}
	return out
}
