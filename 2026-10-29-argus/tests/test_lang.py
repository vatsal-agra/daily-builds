import unittest

from argus.lang import ArgusError, parse_ltl_text
from argus.model import build
from argus.safety import check_safety
from argus.trace import validate


def ok(src, **kw):
    r = check_safety(build(src, kw))
    return r


class SemanticsTests(unittest.TestCase):
    def passes(self, src):
        r = ok(src)
        self.assertTrue(r.ok, [v.message or v.kind for v in r.violations])
        return r

    def fails(self, src, kind):
        m = build(src)
        r = check_safety(m)
        self.assertEqual([v.kind for v in r.violations], [kind])
        validate(m, r.violations[0])
        return r

    def test_exact_state_counts(self):
        # two independent 3-statement processes: a 4 x 4 grid of program counters
        self.assertEqual(self.passes("proc P() { skip; skip; skip; } run P(); run P();").states, 16)
        # an atomic block is one step: 2 x 2
        self.assertEqual(self.passes("proc P() { atomic { skip; skip; skip; } } run P(); run P();").states, 4)
        # three processes, 2 statements each -> 3^3
        self.assertEqual(self.passes("proc P() { skip; skip; } for i in 0..2 { run P(); }").states, 27)

    def test_operator_precedence_is_c_like(self):
        self.passes("""var x = 0; var y = 0; var z = 0; var w = 0;
        proc P() { x = 1 & 3 == 3; y = 1 + 2 * 3 == 7 ? 10 : 20; z = 5 & 3 | 8 ^ 1; w = !0 + 1 << 2; }
        proc Q() { await w != 0; assert x == 1, "x"; assert y == 10, "y"; assert z == 9, "z"; assert w == 8, "w"; }
        run P(); run Q();""")

    def test_division_modulo_truncate_toward_zero(self):
        self.passes("""var a = 0; var b = 0; var c = 0; var d = 0; var done = 0;
        proc P() { a = 7 / 2; b = (0 - 7) / 2; c = (0 - 7) % 3; d = 7 % (0 - 3); done = 1; }
        proc Q() { await done == 1; assert a == 3 && b == (0 - 3) && c == (0 - 1) && d == 1, "div"; }
        run P(); run Q();""")

    def test_guarded_choice(self):
        base = "var x = 0; proc P() { either { await x == 1; x = 5; } or { x = 2; } } run P();"
        self.passes(base + " invariant never5: x != 5;")
        self.fails(base + " proc Q() { x = 1; } run Q(); invariant never5: x != 5;", "invariant")

    def test_nondet_explores_every_value(self):
        self.fails("proc P() { var v = 0; nondet v in 1..3; assert v != 2, \"two\"; } run P();", "assert")
        self.passes("proc P() { var v = 0; nondet v in 1..3; assert v >= 1 && v <= 3; } run P();")

    def test_break_continue_structure(self):
        self.passes("""var n = 0;
        proc P() { loop { n = n + 1; either { break; } or { if (n > 2) { break; } } } assert n >= 1; assert n <= 3; }
        run P();""")

    def test_else_if_chain(self):
        self.passes("""var r = 0; var x = 5;
        proc P() { if (x < 3) { r = 1; } else if (x < 6) { r = 2; } else { r = 3; } assert r == 2; }
        run P();""")

    def test_channels_fifo_multifield_and_array_targets(self):
        self.passes("""chan q[2] of 2; var out[3] = 0; var n = 0;
        proc S() { send(q, 1, 10); send(q, 2, 20); send(q, 3, 30); }
        proc R() { var k = 0; var v = 0; while (n < 3) { recv(q, k, v); out[k - 1] = v; n = n + 1; }
                   assert out[0] == 10 && out[1] == 20 && out[2] == 30, "fifo"; }
        run S(); run R();""")

    def test_channel_capacity_blocks_sender(self):
        self.fails("chan q[1]; proc S() { send(q, 1); send(q, 2); } run S();", "deadlock")

    def test_head_len_empty_full(self):
        self.passes("""chan q[2]; var ok = 0;
        proc P() { assert empty(q); send(q, 7); send(q, 8); assert full(q) && len(q) == 2 && head(q) == 7;
                   ok = 1; }
        run P();""")

    def test_ranges_catch_overflow(self):
        self.fails("var c : 0..3 = 0; proc P() { loop { c = c + 1; } } run P();", "error")

    def test_local_ranges_and_params(self):
        self.passes("proc P(k) { var t : 0..9 = k * 2; assert t == 6; } run P(3);")

    def test_label_semantics(self):
        m = build("proc P() { label a: skip; if (1 == 1) { label b: skip; } label z: }"
                  " run P();")
        p = m.procs[0]
        self.assertEqual(set(p.labels), {"a", "b", "z"})
        self.assertEqual(p.labels["z"], p.end_node)

    def test_qualified_names_and_at_in_invariants(self):
        self.fails("""proc P() { var t = 0; t = 1; label here: t = 2; } run P();
        invariant seen: !(at(P0, here) && P0.t == 1);""", "invariant")

    def test_for_run_and_defines(self):
        r = self.passes("const N = 3; var c[N] = 0; proc P(i) { c[i] = 1; } for i in 0..N-1 { run P(i); }"
                        " invariant bounded: c[0] + c[1] + c[2] <= N;")
        self.assertEqual(r.states, 8)
        self.assertEqual(ok("const N = 3; var c[N] = 0; proc P(i) { c[i] = 1; } for i in 0..N-1 { run P(i); }",
                            N=2).states, 4)

    def test_ltl_parse_forms(self):
        for f in ["[] <> p", "<> [] p", "p U q", "p R q", "p W q", "X X p", "p -> q", "p <-> !q",
                  "always (eventually (p))", "next p", "!(p && q) || r", "(x + 1) == 2 && y"]:
            parse_ltl_text(f)
        for bad in ["p U", "[] ", "(p", "p q"]:
            with self.assertRaises(ArgusError):
                parse_ltl_text(bad)

    def test_comments_and_whitespace(self):
        self.passes("/* block\n comment */ var x = 1; // line\nproc P() { assert x == 1; } run P();")


if __name__ == "__main__":
    unittest.main()
