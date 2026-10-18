package mf

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func parse(t *testing.T, src string) *File {
	t.Helper()
	f, err := Parse("Mortisefile", src, t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return f
}

func TestVariablesAndFunctions(t *testing.T) {
	f := parse(t, `
A = x.c y.c z.h
B = $(filter %.c,$(A))
C = $(patsubst %.c,build/%.o,$(B))
D = $(B:.c=.o)
E += one
E += two
F ?= first
F ?= second
G = $(addprefix -I,inc lib) $(addsuffix .a,p q)
H = $(sort b a b c) $(words $(A)) $(firstword $(A)) $(notdir a/b/c.txt) $(dir a/b/c.txt) $(basename a/b.c) $(suffix a/b.c)
I = $(subst a,b,banana) $(if x,yes,no) $(if ,yes,no) $(filter-out %.c,$(A)) $(strip   a   b  )
`)
	want := map[string]string{
		"B": "x.c y.c", "C": "build/x.o build/y.o", "D": "x.o y.o", "E": "one two", "F": "first",
		"G": "-Iinc -Ilib p.a q.a",
		"H": "a b c 3 x.c c.txt a/b a/b .c",
		"I": "bbnbnb yes no z.h a b",
	}
	for k, v := range want {
		if f.Vars[k] != v {
			t.Errorf("%s = %q, want %q", k, f.Vars[k], v)
		}
	}
}

func TestRuleParsing(t *testing.T) {
	f := parse(t, `
default all
CC = cc
all: a.o b.o   # not a comment inside deps? it is part of text
    echo hi
%.o: %.c
    @depfile $*.d
    @desc CC $<
    $(CC) -c $< -o $@ ; echo $$HOME
x y &: spec
    gen
phony all
`)
	if len(f.Rules) != 3 {
		t.Fatalf("rules = %d", len(f.Rules))
	}
	p := f.Rules[1]
	if !p.IsPattern() || p.Depfile != "$*.d" || p.Desc != "CC $<" {
		t.Fatalf("pattern rule: %+v", p)
	}
	if got := p.Cmds[0].Text; got != "cc -c $< -o $@ ; echo $$HOME" {
		t.Fatalf("cmd = %q", got)
	}
	g := f.Rules[2]
	if !g.Grouped || !reflect.DeepEqual(g.Targets, []string{"x", "y"}) {
		t.Fatalf("grouped: %+v", g)
	}
	if !f.Rules[0].Phony || !reflect.DeepEqual(f.Default, []string{"all"}) {
		t.Fatalf("phony/default: %+v %+v", f.Rules[0], f.Default)
	}
}

func TestContinuationsAndComments(t *testing.T) {
	f := parse(t, "# top\nSRC = a.c \\\n   b.c \\\n   c.c\n\nt: $(SRC)\n    # comment line\n    echo a \\\n      b\n")
	if f.Vars["SRC"] != "a.c b.c c.c" {
		t.Fatalf("SRC = %q", f.Vars["SRC"])
	}
	r := f.Rules[0]
	if len(r.Cmds) != 1 || r.Cmds[0].Text != "echo a b" || len(r.Deps) != 3 {
		t.Fatalf("%+v", r)
	}
}

func TestErrorsArePositioned(t *testing.T) {
	cases := []struct{ src, want string }{
		{"a: b\n    ok\nthis is nonsense\n", "Mortisefile:3: expected a rule"},
		{"    echo hi\n", "Mortisefile:1: recipe line outside of a rule"},
		{"X = $(NOPE)\n", "Mortisefile:1: undefined variable \"NOPE\""},
		{"a: $(glob\n", "Mortisefile:1: unterminated"},
		{"a b: c\n", "Mortisefile:1: multiple targets need '&:'"},
		{"a: b\n    @bogus\n", "Mortisefile:2: unknown directive \"@bogus\""},
		{"%.o %.d: %.c\n", "Mortisefile:1: multiple targets need"},
		{"a%b%c: d\n", "more than one '%'"},
		{"../x: y\n", "escapes the project root"},
		{"a: b | c\n", "order-only"},
		{"X = $(patsubst a,b)\n", "takes 3 argument(s), got 2"},
		{"a:\n    @depfile\n", "@depfile needs a path"},
		{"x = $(y)\ny = $(x)\n", "undefined variable"},
	}
	for _, c := range cases {
		_, err := Parse("Mortisefile", c.src, t.TempDir())
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q: got %v, want substring %q", c.src, err, c.want)
		}
	}
}

func TestGlob(t *testing.T) {
	root := t.TempDir()
	for _, p := range []string{"src/a.c", "src/b.c", "src/deep/c.c", "src/deep/er/d.c", "src/e.h", ".hidden/x.c", "top.c"} {
		full := filepath.Join(root, p)
		os.MkdirAll(filepath.Dir(full), 0o755)
		os.WriteFile(full, nil, 0o644)
	}
	check := func(pat string, want ...string) {
		t.Helper()
		got, err := Glob(root, pat)
		if err != nil || !reflect.DeepEqual(got, want) {
			t.Errorf("Glob(%q) = %v, %v; want %v", pat, got, err, want)
		}
	}
	check("src/*.c", "src/a.c", "src/b.c")
	check("src/**/*.c", "src/a.c", "src/b.c", "src/deep/c.c", "src/deep/er/d.c")
	check("**/*.c", "src/a.c", "src/b.c", "src/deep/c.c", "src/deep/er/d.c", "top.c")
	check("src/?.h", "src/e.h")
	check("src/[ab].c", "src/a.c", "src/b.c")
	check("nothing/*.c")
	check("src/deep") // directories are not returned
	if _, err := Glob(root, "src/[.c"); err == nil {
		t.Error("bad pattern must error")
	}
	if _, err := Glob(root, "../*"); err == nil {
		t.Error("escaping the root must error")
	}
}

func TestShellFunctionAndEscaping(t *testing.T) {
	f := parse(t, "V = $(shell echo hello 'a$$b')\nt: x\n    echo $(V)\n")
	if f.Vars["V"] != "hello a$$b" {
		t.Fatalf("V = %q", f.Vars["V"])
	}
	got, err := ExpandRun(f.Vars, nil, f.Rules[0].Cmds[0].Text)
	if err != nil || got != "echo hello a$b" {
		t.Fatalf("%q %v", got, err)
	}
}

func TestMatchStem(t *testing.T) {
	cases := []struct {
		pat, s, stem string
		ok           bool
	}{
		{"build/%.o", "build/a/b.o", "a/b", true},
		{"%.o", "x.c", "", false},
		{"%.o", ".o", "", false},
		{"a%z", "abcz", "bc", true},
		{"exact", "exact", "", true},
		{"exact", "other", "", false},
	}
	for _, c := range cases {
		stem, ok := MatchStem(c.pat, c.s)
		if ok != c.ok || stem != c.stem {
			t.Errorf("MatchStem(%q,%q) = %q,%v", c.pat, c.s, stem, ok)
		}
	}
}

func TestAutoModifiers(t *testing.T) {
	got, err := ExpandRun(nil, map[string]string{"@": "out/x.o", "<": "src/x.c", "^": "src/x.c inc/y.h"}, "$(@D) $(@F) $(<F) $(^D)")
	if err != nil || got != "out x.o x.c src inc" {
		t.Fatalf("%q %v", got, err)
	}
}

func TestInclude(t *testing.T) {
	root := t.TempDir()
	os.WriteFile(filepath.Join(root, "common.mk"), []byte("Z = from-include\nz: \n    echo\n"), 0o644)
	f, err := Parse("Mortisefile", "include common.mk\nY = $(Z)!\n", root)
	if err != nil || f.Vars["Y"] != "from-include!" || len(f.Rules) != 1 {
		t.Fatalf("%v %+v", err, f)
	}
	if _, err := Parse("Mortisefile", "include nope.mk\n", root); err == nil {
		t.Fatal("missing include must error")
	}
}

// R6 (REVIEW.md): trailing comments leaked into variable values and deps.
func TestTrailingComments(t *testing.T) {
	f := parse(t, "X = a b   # tail comment\nY = has\\#hash\nZ = $(subst a,#,a)  # c\nt: d  # why\n    echo hi # kept for the shell\n")
	if f.Vars["X"] != "a b" || f.Vars["Y"] != "has#hash" || f.Vars["Z"] != "#" {
		t.Fatalf("%q %q %q", f.Vars["X"], f.Vars["Y"], f.Vars["Z"])
	}
	r := f.Rules[0]
	if len(r.Deps) != 1 || r.Deps[0] != "d" || r.Cmds[0].Text != "echo hi # kept for the shell" {
		t.Fatalf("%+v", r)
	}
}
