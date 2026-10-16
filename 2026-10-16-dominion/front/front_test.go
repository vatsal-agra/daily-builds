package front

import (
	"fmt"
	"strings"
	"testing"

	"dominion/ir"
)

func run(t *testing.T, src string) ir.Result {
	t.Helper()
	m, err := Compile(src)
	if err != nil {
		t.Fatalf("compile: %v", err)
	}
	// text round trip must preserve behaviour
	m2, err := ir.Parse(m.String())
	if err != nil {
		t.Fatalf("reparse: %v\n%s", err, m)
	}
	if err := m2.Verify(); err != nil {
		t.Fatalf("verify reparsed: %v", err)
	}
	r1, r2 := m.Run(1e7), m2.Run(1e7)
	if !r1.Same(r2) {
		t.Fatalf("round trip changed behaviour: %v vs %v", r1, r2)
	}
	return r1
}

func TestPrograms(t *testing.T) {
	cases := []struct {
		name, src, out string
		ret            int64
	}{
		{"fib", `fn fib(n){ if n<2 {return n;} return fib(n-1)+fib(n-2);} fn main(){ print(fib(15)); return fib(10);}`, "610\n", 55},
		{"loops", `fn main(){ var s=0; for var i=0; i<10; i+=1 { if i%2==0 {continue;} if i>7 {break;} s+=i; } return s; }`, "", 1 + 3 + 5 + 7},
		{"arrays", `fn main(){ var a[10]; var i=0; while i<10 { a[i]=i*i; i=i+1; } var s=0; for i=0; i<10; i+=1 { s+=a[i]; } print(s); return a[9]; }`, "285\n", 81},
		{"shortcircuit", `fn side(x){ print(x); return x; } fn main(){ var r = side(0) && side(1); var q = side(2) || side(3); return r*10+q; }`, "0\n2\n", 1},
		{"unary", `fn main(){ return -(3) + ~5 + !0 + !7 + - -4; }`, "", -3 + ^5 + 1 + 0 + 4},
		{"shadow", `fn main(){ var x=1; { var x=2; print(x);} print(x); return 0; }`, "2\n1\n", 0},
		{"bigarr", `fn main(){ var a[100]; var s=0; for var i=0;i<100;i+=1 { s+=a[i]; a[i]=1; } var j=0; while j<3 { var b[8]; b[3]+=1; s+=b[3]; j+=1;} return s; }`, "", 3},
		{"deadcode", `fn main(){ return 5; print(1); }`, "", 5},
		{"fallthrough", `fn f(){ } fn main(){ return f()+1; }`, "", 1},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := run(t, c.src)
			if r.Trap != "" || r.Out != c.out || r.Ret != c.ret {
				t.Fatalf("got %v want out=%q ret=%d", r, c.out, c.ret)
			}
		})
	}
}

func TestTraps(t *testing.T) {
	for src, want := range map[string]string{
		`fn main(){ var z=0; return 1/z; }`:                   ir.TrapDivZero,
		`fn main(){ var a[3]; return a[3]; }`:                 ir.TrapOOB,
		`fn main(){ var a[3]; a[0-1]=1; return 0; }`:          ir.TrapOOB,
		`fn f(n){ return f(n+1); } fn main(){ return f(0); }`: ir.TrapStack,
		`fn main(){ while 1 { } return 0; }`:                  ir.TrapFuel,
	} {
		m, err := Compile(src)
		if err != nil {
			t.Fatal(err)
		}
		if r := m.Run(100000); r.Trap != want {
			t.Errorf("%s: trap=%q want %q", src, r.Trap, want)
		}
	}
}

func TestErrors(t *testing.T) {
	for src, want := range map[string]string{
		`fn main(){ return x; }`:                      "undefined variable",
		`fn main(){ var a[3]; return a; }`:            "without an index",
		`fn main(){ var x=1; return x[0]; }`:          "not an array",
		`fn main(){ break; }`:                         "outside of a loop",
		`fn main(){ return f(); }`:                    "undefined function",
		`fn f(a){return a;} fn main(){ return f(); }`: "expects 1",
		`fn main(){ var x=1; var x=2; }`:              "already declared",
		`fn main(){ return 1 +; }`:                    "expected expression",
		`fn main(){ return 1 `:                        "expected",
		`fn main(){ 1+2; }`:                           "must be a call",
		`fn main(){ var a[0]; }`:                      "array size",
		`fn main(){ return 99999999999999999999; }`:   "out of range",
		`fn main(){ return 1 @ 2; }`:                  "unexpected character",
		`fn main(){} fn main(){}`:                     "defined twice",
		`fn f(a,a){} fn main(){}`:                     "duplicate parameter",
		`main(){}`:                                    "expected 'fn'",
	} {
		_, err := Compile(src)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: err=%v want containing %q", src, err, want)
		}
	}
}

func TestMinInt64AndShadowInit(t *testing.T) {
	r := run(t, `fn main(){ var m = -9223372036854775808; print(m); print(-m); print(m - 1); return -(-9223372036854775807 - 1) == m; }`)
	if r.Out != "-9223372036854775808\n-9223372036854775808\n9223372036854775807\n" || r.Ret != 1 {
		t.Fatalf("got %v", r)
	}
	if _, err := Compile(`fn main(){ return 9223372036854775808; }`); err == nil {
		t.Fatal("positive 2^63 must be rejected")
	}
	r = run(t, `fn main(){ var x=1; { var x = x + 1; print(x);} return x; }`)
	if r.Out != "2\n" || r.Ret != 1 {
		t.Fatalf("self-referential shadow init: %v", r)
	}
}

func TestOutputLimit(t *testing.T) {
	m, _ := Compile(`fn main(){ while 1 { print(123456789); } return 0; }`)
	if r := m.Run(1 << 40); r.Trap != ir.TrapOutput {
		t.Fatalf("want output limit trap, got %v", r.Trap)
	}
}

// && and || must short-circuit AND produce 0/1, in value position and in branch position.
func TestLogicalOperatorsTruthTable(t *testing.T) {
	b2i := func(b bool) int {
		if b {
			return 1
		}
		return 0
	}
	for _, a := range []int{0, 1, 2, -3} {
		for _, b := range []int{0, 1, 5} {
			src := fmt.Sprintf(`fn t(x){ print(x); return x; }
fn main(){
  var and = t(%[1]d) && t(%[2]d);
  var or = t(%[1]d) || t(%[2]d);
  print(and); print(or);
  var c1 = 0; if %[1]d && %[2]d { c1 = 1; }
  var c2 = 0; if %[1]d || %[2]d { c2 = 1; }
  var c3 = 0; if !(%[1]d && %[2]d) { c3 = 1; }
  var c4 = 0; var k = 0; while k < 3 && %[2]d != 0 { c4 += 1; k += 1; }
  return and * 1000 + or * 100 + c1 * 10 + c2 + c3 * 10000 + c4 * 100000;
}`, a, b)
			var out string
			and, or := b2i(a != 0 && b != 0), b2i(a != 0 || b != 0)
			out += fmt.Sprintf("%d\n", a)
			if a != 0 {
				out += fmt.Sprintf("%d\n", b)
			}
			out += fmt.Sprintf("%d\n", a)
			if a == 0 {
				out += fmt.Sprintf("%d\n", b)
			}
			out += fmt.Sprintf("%d\n%d\n", and, or)
			c4 := 0
			if b != 0 {
				c4 = 3
			}
			want := int64(and*1000 + or*100 + and*10 + or + (1-and)*10000 + c4*100000)
			r := run(t, src)
			if r.Out != out || r.Ret != want {
				t.Errorf("a=%d b=%d: got out=%q ret=%d want out=%q ret=%d", a, b, r.Out, r.Ret, out, want)
			}
		}
	}
}
