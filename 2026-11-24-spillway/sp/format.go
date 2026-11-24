package sp

import (
	"fmt"
	"sort"
	"strings"
)

// FormatMachine prints allocated code in assembly-like form, one block at a time.
func FormatMachine(m *Function) string {
	var sb strings.Builder
	for _, b := range m.Blocks {
		sb.WriteString(b.Name + ":\n")
		for i := range b.Instrs {
			sb.WriteString("    " + m.FormatInstr(&b.Instrs[i]) + "\n")
		}
	}
	return sb.String()
}

// FormatSweep renders a K-sweep as a text table of cycles / spill traffic.
func FormatSweep(sweep [][]Row) string {
	var sb strings.Builder
	fmt.Fprintf(&sb, "%3s | %-24s | %-24s | %-24s\n", "K", "color (cycles / spills)", "linear (cycles / spills)", "naive (cycles / spills)")
	fmt.Fprintln(&sb, strings.Repeat("-", 3+3*27))
	for _, rows := range sweep {
		cells := make([]string, len(rows))
		for i, r := range rows {
			switch {
			case r.Alloc == nil || !r.Verified:
				cells[i] = "ERROR"
			default:
				cells[i] = fmt.Sprintf("%d / %d", r.Dyn.Cycles, r.Dyn.SpillLoads+r.Dyn.SpillStores)
			}
		}
		fmt.Fprintf(&sb, "%3d | %-24s | %-24s | %-24s\n", rows[0].K, cells[0], cells[1], cells[2])
	}
	return sb.String()
}

// FormatLiveness dumps loop depth, per-block live sets, intervals and max pressure.
func FormatLiveness(f *Function) string {
	lv := f.Liveness()
	depth := f.LoopDepth()
	var sb strings.Builder
	names := func(b Bitset) string {
		var ns []string
		b.each(func(r int) { ns = append(ns, f.RegName(r)) })
		sort.Strings(ns)
		return "{" + strings.Join(ns, " ") + "}"
	}
	maxP := 0
	f.LiveAfter(lv, func(bi, ii int, live Bitset) {
		if c := live.count(); c > maxP {
			maxP = c
		}
	})
	for bi, b := range f.Blocks {
		fmt.Fprintf(&sb, "%-8s depth=%d preds=%v succs=%v\n  live-in  %s\n  live-out %s\n", b.Name, depth[bi], b.Preds, b.Succs, names(lv.In[bi]), names(lv.Out[bi]))
	}
	ivs, nm := f.Intervals(lv)
	fmt.Fprintf(&sb, "\nlive intervals (doubled positions: use=2p, def=2p+1; %d instructions):\n", nm.Total)
	for _, iv := range ivs {
		fmt.Fprintf(&sb, "  %-10s [%d, %d]\n", f.RegName(iv.Reg), iv.Start, iv.End)
	}
	fmt.Fprintf(&sb, "\nmax register pressure (values live after any instruction): %d\n", maxP)
	return sb.String()
}
