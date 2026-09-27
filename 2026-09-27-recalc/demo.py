"""A narrated, self-checking walkthrough of every Recalc feature, run via
`python3 recalc.py demo` and by `demo.sh`. Each section asserts the exact
result it claims, so a broken build fails loudly here instead of just
looking plausible in a screenshot.
"""

from engine import csvio, refs
from engine.sheet import Sheet


def A(addr):
    r = refs.parse_cell_ref(addr)
    return (r.col, r.row)


def section(title):
    print()
    print(f"=== {title} ===")


def check(label, actual, expected):
    status = "ok" if actual == expected else "FAIL"
    print(f"  [{status}] {label}: {actual!r}")
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def run_demo():
    section("Formula language: precedence, refs, functions")
    s = Sheet()
    s.set_cell(*A("A1"), "10")
    s.set_cell(*A("A2"), "20")
    s.set_cell(*A("A3"), "30")
    s.set_cell(*A("B1"), "=SUM(A1:A3)")
    s.set_cell(*A("B2"), "=AVERAGE(A1:A3)")
    s.set_cell(*A("B3"), "=(A1+A2)*2-A3/3")
    check("SUM(A1:A3)", s.get_display(*A("B1")), "60")
    check("AVERAGE(A1:A3)", s.get_display(*A("B2")), "20")
    check("(A1+A2)*2-A3/3", s.get_display(*A("B3")), "50")
    s.set_cell(*A("C1"), "=-2^2")
    check("-2^2 (unary binds tighter than ^, like real spreadsheets)", s.get_display(*A("C1")), "4")

    section("Dependency graph: editing A1 ripples through the whole chain")
    s.set_cell(*A("D1"), "=B1+B2")
    check("D1 before edit", s.get_display(*A("D1")), "80")
    s.set_cell(*A("A1"), "100")
    check("B1 after A1 edit", s.get_display(*A("B1")), "150")
    check("D1 after A1 edit (transitively recomputed)", s.get_display(*A("D1")), "200")

    section("Cycle detection")
    s.set_cell(*A("E1"), "=F1+1")
    s.set_cell(*A("F1"), "=E1+1")
    check("E1 in a cycle", s.get_display(*A("E1")), "#CYCLE!")
    check("F1 in a cycle", s.get_display(*A("F1")), "#CYCLE!")
    s.set_cell(*A("F1"), "5")
    check("E1 recovers once the cycle is broken", s.get_display(*A("E1")), "6")

    section("Error propagation")
    s.set_cell(*A("G1"), "=1/0")
    s.set_cell(*A("G2"), "=G1*2")
    check("1/0", s.get_display(*A("G1")), "#DIV/0!")
    check("error propagates through *2", s.get_display(*A("G2")), "#DIV/0!")
    s.set_cell(*A("G3"), "=IFERROR(G1,\"caught\")")
    check("IFERROR catches it", s.get_display(*A("G3")), "caught")

    section("VLOOKUP over a small price table")
    s.set_cell(*A("H1"), "apple");  s.set_cell(*A("I1"), "1.50")
    s.set_cell(*A("H2"), "banana"); s.set_cell(*A("I2"), "0.75")
    s.set_cell(*A("H3"), "cherry"); s.set_cell(*A("I3"), "4.20")
    s.set_cell(*A("J1"), '=VLOOKUP("banana",H1:I3,2,FALSE)')
    check("VLOOKUP banana price", s.get_display(*A("J1")), "0.75")

    section("Copy/paste: relative refs shift, $-locked refs don't")
    s.set_cell(*A("K1"), "=A1*10")
    s.set_cell(*A("L1"), "=$A$1*10")
    s.copy_paste(A("K1"), A("K1"), A("K2"))
    s.copy_paste(A("L1"), A("L1"), A("L2"))
    check("K2 formula (A1 -> A2)", s.get_raw(*A("K2")), "=A2*10")
    check("L2 formula ($A$1 stays locked)", s.get_raw(*A("L2")), "=$A$1*10")

    section("Fill: drag a formula down a column")
    s.set_cell(*A("M1"), "1"); s.set_cell(*A("M2"), "2"); s.set_cell(*A("M3"), "3")
    s.set_cell(*A("N1"), "=M1*100")
    s.fill(*A("N1"), A("N1"), A("N3"))
    check("N2 filled", s.get_display(*A("N2")), "200")
    check("N3 filled", s.get_display(*A("N3")), "300")

    section("Undo / redo")
    s.set_cell(*A("O1"), "1")
    s.set_cell(*A("O1"), "2")
    s.undo()
    check("O1 after undo", s.get_display(*A("O1")), "1")
    s.redo()
    check("O1 after redo", s.get_display(*A("O1")), "2")

    section("CSV import / export round trip")
    csv_text = "1,2,=A1+B1\n3,4,=A2+B2\n"
    s2 = Sheet()
    csvio.import_csv(s2, csv_text)
    exported = csvio.export_csv(s2)
    check("re-exported CSV matches computed values", exported, "1,2,3\n3,4,7\n")

    section("Incremental engine matches a full from-scratch recompute")
    s3 = Sheet()
    s3.set_cell(*A("A1"), "1")
    s3.set_cell(*A("B1"), "=A1+1")
    s3.set_cell(*A("C1"), "=B1+1")
    before = {k: s3.get_display(*k) for k in s3.cells}
    s3.recompute_all()
    after = {k: s3.get_display(*k) for k in s3.cells}
    check("incremental == full recompute", before, after)

    print()
    print("Recalc demo: all sections passed.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run_demo())
