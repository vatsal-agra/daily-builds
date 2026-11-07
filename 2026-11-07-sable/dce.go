package sable

// DCE removes values that cannot affect output, traps or the return value.
func DCE(f *Func) bool {
	live := map[*Value]bool{}
	var work []*Value
	mark := func(v *Value) {
		if !live[v] {
			live[v] = true
			work = append(work, v)
		}
	}
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			if v.HasSideEffect() {
				mark(v)
			}
		}
		if b.Ctrl != nil {
			mark(b.Ctrl)
		}
	}
	for len(work) > 0 {
		v := work[len(work)-1]
		work = work[:len(work)-1]
		for _, a := range v.Args {
			mark(a)
		}
	}
	ch := false
	for _, b := range f.Blocks {
		keep := b.Instrs[:0]
		for _, v := range b.Instrs {
			if live[v] {
				keep = append(keep, v)
			} else {
				ch = true
			}
		}
		b.Instrs = keep
	}
	return ch
}
