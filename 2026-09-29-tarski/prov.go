package main

import (
	"fmt"
	"strings"
)

// Why renders a proof tree for a derived fact.
func (e *Engine) Why(pred string, t []Val) (string, error) {
	rel := e.Rels[pred]
	if rel == nil {
		return "", fmt.Errorf("unknown predicate %s", pred)
	}
	if len(t) != rel.Arity {
		return "", fmt.Errorf("%s takes %d argument(s), got %d", pred, rel.Arity, len(t))
	}
	i, ok := rel.set[tupleKey(t)]
	if !ok {
		return "", fmt.Errorf("%s is not derivable (it is false in the minimal model)", tupleString(pred, t))
	}
	var b strings.Builder
	lines := 0
	e.proof(&b, FactRef{pred, i}, "", "", &lines)
	if lines > maxProofLines {
		fmt.Fprintf(&b, "… proof truncated after %d lines\n", maxProofLines)
	}
	return b.String(), nil
}

const maxProofLines = 2000

func (e *Engine) proof(b *strings.Builder, f FactRef, prefix, childPrefix string, lines *int) {
	*lines++
	if *lines > maxProofLines {
		return
	}
	rel := e.Rels[f.Pred]
	text := tupleString(f.Pred, rel.Tuples[f.Idx])
	d := rel.Prov[f.Idx]
	switch {
	case d == nil:
		fmt.Fprintf(b, "%s%s  [fact]\n", prefix, text)
		return
	case d.Agg != "":
		fmt.Fprintf(b, "%s%s  [%s; rule: %s]\n", prefix, text, d.Agg, d.Rule)
		return
	}
	fmt.Fprintf(b, "%s%s  [line %d: %s]\n", prefix, text, d.Rule.Line, d.Rule)
	for i := range d.Body {
		last := i == len(d.Body)-1
		branch, cont := "├─ ", "│  "
		if last {
			branch, cont = "└─ ", "   "
		}
		if d.Body[i].Pred != "" {
			e.proof(b, d.Body[i], childPrefix+branch, childPrefix+cont, lines)
		} else if *lines++; *lines <= maxProofLines {
			fmt.Fprintf(b, "%s%s  ✓\n", childPrefix+branch, d.Note[i])
		}
	}
}

// ProofSize counts the nodes of the proof tree (used by tests).
func (e *Engine) ProofSize(f FactRef) int {
	d := e.Rels[f.Pred].Prov[f.Idx]
	n := 1
	if d != nil {
		for _, c := range d.Body {
			if c.Pred != "" {
				n += e.ProofSize(c)
			}
		}
	}
	return n
}
