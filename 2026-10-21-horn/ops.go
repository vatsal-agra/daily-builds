package main

type opDef struct {
	pri int
	typ string
}

type opEntry struct {
	prefix, infix, postfix *opDef
}

type OpTable map[string]*opEntry

func newOpTable() OpTable {
	t := OpTable{}
	add := func(p int, typ string, names ...string) {
		for _, n := range names {
			t.add(p, typ, n)
		}
	}
	add(1200, "xfx", ":-", "-->")
	add(1200, "fx", ":-", "?-")
	add(1100, "xfy", ";", "|")
	add(1050, "xfy", "->", "*->")
	add(1000, "xfy", ",")
	add(990, "xfx", ":=")
	add(900, "fy", "\\+")
	add(700, "xfx", "=", "\\=", "==", "\\==", "@<", "@>", "@=<", "@>=", "=@=", "\\=@=", "=..", "is", "=:=", "=\\=", "<", ">", "=<", ">=", ">:<", ":<", "as")
	add(600, "xfy", ":")
	add(500, "yfx", "+", "-", "/\\", "\\/", "xor")
	add(400, "yfx", "*", "/", "//", "mod", "rem", "<<", ">>", "div", "rdiv", "divmod")
	add(200, "xfx", "**")
	add(200, "xfy", "^")
	add(200, "fy", "-", "+", "\\")
	add(100, "yfx", ".")
	add(1, "fx", "$")
	add(1150, "fx", "dynamic", "discontiguous", "initialization", "meta_predicate", "module_transparent", "multifile", "public", "thread_local", "table")
	return t
}

func (t OpTable) add(p int, typ, name string) {
	e := t[name]
	if e == nil {
		e = &opEntry{}
		t[name] = e
	}
	var d *opDef
	if p > 0 {
		d = &opDef{p, typ}
	}
	switch typ {
	case "fx", "fy":
		e.prefix = d
	case "xfx", "xfy", "yfx":
		e.infix = d
	case "xf", "yf":
		e.postfix = d
	}
}

func (d *opDef) leftMax() int {
	if d.typ == "yfx" || d.typ == "yf" {
		return d.pri
	}
	return d.pri - 1
}
func (d *opDef) rightMax() int {
	if d.typ == "xfy" || d.typ == "fy" {
		return d.pri
	}
	return d.pri - 1
}
