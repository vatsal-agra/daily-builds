import random
import re
import threading
import unittest
from tests.helpers import *


class FuzzTests(unittest.TestCase):
    """Mutated source files must never crash (internal error / traceback) or hang."""

    def test_mutation_fuzz(self):
        srcs = []
        for f in ("nat.lm", "logic.lm", "trees.lm", "even.lm"):
            with open(os.path.join(ROOT, "examples", f), encoding="utf-8") as fh:
                srcs.append(fh.read())
        rnd = random.Random(2026)
        junk = ["(", ")", ".", "{", "}", "|", "=>", "->", "forall", "fun", "elim", "0", "x", "by", "end", ":=", ":", ",", "as", "at", "<-"]
        for n in range(60):
            toks = re.findall(r"\s+|\w+|.", rnd.choice(srcs))
            for _ in range(rnd.randint(1, 4)):
                i = rnd.randrange(len(toks))
                op = rnd.choice(["del", "dup", "swap", "junk"])
                if op == "del": toks[i] = ""
                elif op == "dup": toks[i] *= 2
                elif op == "swap" and i + 1 < len(toks): toks[i], toks[i + 1] = toks[i + 1], toks[i]
                else: toks[i] = rnd.choice(junk)
            src = "".join(toks)
            s = clone_session()
            box = {}

            def go():
                try:
                    s.run(src, "fuzz.lm")
                except BaseException as e:
                    box["exc"] = repr(e)
            th = threading.Thread(target=go, daemon=True)
            th.start(); th.join(30)
            self.assertFalse(th.is_alive(), f"hang on:\n{src[:300]}")
            self.assertNotIn("exc", box, f"crash {box.get('exc')} on:\n{src[:300]}")
            self.assertFalse([e for e in s.errors if "internal error" in e], f"internal error on:\n{src[:300]}")


if __name__ == "__main__":
    unittest.main()
