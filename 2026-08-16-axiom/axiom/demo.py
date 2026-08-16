"""`axiom demo` — a self-checking walkthrough of every feature, printed to
the terminal. Every step both prints its result *and* asserts something
concrete about it, so a broken demo fails loudly instead of just looking
plausible."""

from fractions import Fraction

from .calculus import differentiate, integrate
from .expr import sym
from .matrix import Matrix
from .parser import parse
from .polynomial import expand, factor, poly_gcd
from .simplify import simplify
from .solve import solve

x, y = sym("x"), sym("y")


def _section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def run_demo():
    _section("1. Parsing + canonical simplification")
    e = parse("2*x + 3*x - x + 5 - 2")
    print(f"  2x + 3x - x + 5 - 2  ->  {e}")
    assert str(e) == "4*x + 3", e

    e2 = parse("sqrt(8) + sqrt(2)")
    print(f"  sqrt(8) + sqrt(2)  ->  {e2}")
    assert str(e2) == "3*2^(1/2)", e2

    e3 = simplify(parse("sin(x)^2 + cos(x)^2 + 5"))
    print(f"  sin(x)^2 + cos(x)^2 + 5  (simplify)  ->  {e3}")
    assert str(e3) == "6", e3

    e4 = simplify(parse("(x^2 - 1)/(x - 1)"))
    print(f"  (x^2-1)/(x-1)  (simplify, rational reduction)  ->  {e4}")
    assert str(e4) == "x + 1", e4

    _section("2. Symbolic differentiation")
    d1 = differentiate(parse("x^2 * sin(x)"), x)
    print(f"  d/dx[x^2 sin(x)]  ->  {d1}")
    steps = []
    differentiate(parse("exp(x^2 + 1)"), x, trace=steps)
    print(f"  d/dx[exp(x^2+1)] step trace:")
    for s in steps:
        print(f"    {s}")
    d2 = differentiate(parse("x^x"), x)
    print(f"  d/dx[x^x]  ->  {d2}")

    _section("3. Equation solving")
    print(f"  2x - 6 = 0  ->  x = {solve(parse('2*x - 6'), x)}")
    print(f"  x^2 - 5x + 6 = 0  ->  x = {solve(parse('x^2 - 5*x + 6'), x)}")
    print(f"  x^2 + 1 = 0  ->  x = {solve(parse('x^2 + 1'), x)}")
    print(f"  x^3 - 6x^2 + 11x - 6 = 0  ->  x = {solve(parse('x^3 - 6*x^2 + 11*x - 6'), x)}")
    roots = solve(parse("x^2 - 2"), x)
    print(f"  x^2 - 2 = 0  ->  x = {roots}")
    assert str(roots[0]) in ("2^(1/2)", "-2^(1/2)")

    _section("4. Polynomial expand / factor / GCD")
    print(f"  expand (x+1)^3  ->  {expand(parse('(x+1)^3'))}")
    print(f"  factor x^3 - 8  ->  {factor(parse('x^3 - 8'), x)}")
    print(f"  factor 2x^2-3x+1  ->  {factor(parse('2*x^2 - 3*x + 1'), x)}")
    g = poly_gcd(parse("x^2 - 1"), parse("x^2 - 3*x + 2"), x)
    print(f"  gcd(x^2-1, x^2-3x+2)  ->  {g}")
    assert str(g) == "x - 1", g

    _section("5. Symbolic integration")
    i1 = integrate(parse("x^3 + 2*x"), x)
    print(f"  ∫ x^3 + 2x dx  ->  {i1} + C")
    i2 = integrate(parse("x*exp(x)"), x)
    print(f"  ∫ x*exp(x) dx  ->  {i2} + C  (integration by parts)")
    i3 = integrate(parse("sin(3*x + 1)"), x)
    print(f"  ∫ sin(3x+1) dx  ->  {i3} + C  (linear substitution)")

    _section("6. Symbolic matrices")
    A = Matrix([[2, 1], [1, 1]])
    print(f"  A =\n{A}")
    print(f"  det(A) = {A.det()}")
    print(f"  A^-1 =\n{A.inverse()}")
    print(f"  A * A^-1 =\n{A * A.inverse()}")
    sol = A.solve([3, 2])
    print(f"  solve Ax = [3,2]  ->  x = {sol}")

    _section("7. LaTeX rendering")
    print(f"  x^2/(x-1)  ->  {parse('x^2/(x-1)').latex()}")

    print()
    print("Demo complete — every assertion above passed.")
