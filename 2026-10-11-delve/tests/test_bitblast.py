import random, sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from delve import terms as tm
from delve.bitblast import Smt

BIN = ["add", "sub", "mul", "and", "or", "xor", "udiv", "urem", "sdiv", "srem", "shl", "lshr", "ashr"]
CMP = ["eq", "ult", "ule", "slt", "sle"]


def build(op, a, b):
    f = {"add": tm.add, "sub": tm.sub, "mul": tm.mul, "and": tm.bvand, "or": tm.bvor, "xor": tm.bvxor}.get(op)
    if f: return f(a, b)
    if op in CMP: return {"eq": tm.eq, "ult": tm.ult, "ule": tm.ule, "slt": tm.slt, "sle": tm.sle}[op](a, b)
    return tm.binop(op, a, b)


class BlastDiff(unittest.TestCase):
    """The bit-blaster must agree with concrete semantics on every operator."""

    def run_width(self, w, n):
        rnd = random.Random(w)
        smt = Smt()
        x, y = tm.var("x", w), tm.var("y", w)
        for op in BIN + CMP:
            term = build(op, x, y)
            for _ in range(n):
                a, b = rnd.getrandbits(w), rnd.getrandbits(w)
                if rnd.random() < .25: b = rnd.choice([0, 1, tm.mask(w), a])
                want = tm.evaluate(term, {"x": a, "y": b})
                # pin inputs and read the term value: solver must be SAT with that value
                pin = [tm.eq(x, tm.const(a, w)), tm.eq(y, tm.const(b, w))]
                tv = tm.const(want, w) if term.w else tm.boolv(want)
                ok, _ = smt.check(pin + [tm.eq(term, tv)])
                self.assertTrue(ok, (op, w, a, b, want))
                bad = tm.lnot(tm.eq(term, tv))
                ok, _ = smt.check(pin + [bad])
                self.assertFalse(ok, (op, w, a, b, want, "alt value accepted"))

    def test_w4(self): self.run_width(4, 40)
    def test_w8(self): self.run_width(8, 25)
    def test_w5_odd(self): self.run_width(5, 25)   # non power-of-two shift widths
    def test_w12(self): self.run_width(12, 6)

    def test_solve_finds_inputs(self):
        smt = Smt()
        x = tm.var("x", 8)
        ok, m = smt.check([tm.eq(tm.mul(x, tm.const(7, 8)), tm.const(91, 8))])
        self.assertTrue(ok); self.assertEqual((m["x"] * 7) & 255, 91)
        ok, _ = smt.check([tm.eq(tm.bvand(x, tm.const(1, 8)), tm.const(1, 8)), tm.eq(tm.add(x, x), tm.const(7, 8))])
        self.assertFalse(ok)

    def test_validity(self):
        smt = Smt()
        x, y = tm.var("x", 8), tm.var("y", 8)
        self.assertTrue(smt.valid(tm.eq(tm.add(x, y), tm.add(y, x))))
        self.assertTrue(smt.valid(tm.eq(tm.mul(x, tm.const(2, 8)), tm.binop("shl", x, tm.const(1, 8)))))
        self.assertFalse(smt.valid(tm.slt(x, tm.add(x, tm.const(1, 8)))))   # overflow at 127


if __name__ == "__main__":
    unittest.main()
