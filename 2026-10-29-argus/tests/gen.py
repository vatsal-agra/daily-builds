"""Random Argus program generator used by the fuzz tests."""
import random


def rand_program(rng, nprocs=None, loops=False):
    nprocs = nprocs or rng.randint(2, 3)
    H = rng.randint(2, 4)
    out = [f"var g[2] : 0..8 = 0;", f"var h : 0..{H + 3} = 0;"]
    for k in range(nprocs):
        body = []
        for _ in range(rng.randint(2, 5)):
            body.append(rand_stmt(rng, H, loops))
        out.append(f"proc P{k}() {{ var a : 0..20 = 0; var b : 0..20 = 0;\n  " + "\n  ".join(body) + "\n}")
        out.append(f"run P{k}();")
    out.append(f"invariant inv: h <= {rng.randint(1, H + 1)};")
    return "\n".join(out)


def rand_stmt(rng, H, loops):
    r = rng.random()
    idx = rng.choice(["0", "1", "1", "a"])
    if r < 0.15:
        return f"a = a + {rng.randint(1, 2)};"
    if r < 0.25:
        return f"b = a * 2;"
    if r < 0.38:
        return f"g[{idx}] = a + 1;"
    if r < 0.50:
        return f"a = g[{idx}];"
    if r < 0.60:
        return "atomic { h = h + 1; }"
    if r < 0.68:
        return f"if (a > {rng.randint(0, 2)}) {{ h = h + 1; }} else {{ b = b + 1; }}"
    if r < 0.74:
        return f"if (h > {rng.randint(0, H)}) {{ a = 1; }}"
    if r < 0.80:
        return f"await h >= {rng.randint(0, H)};"
    if r < 0.87:
        return f"assert {rng.choice(['a', 'h', 'g[0]'])} <= {rng.randint(0, 3)};"
    if r < 0.93:
        return "either { a = 1; } or { b = 2; }"
    return "while (a < 3) { a = a + 1; b = b + a; }"


def rand_loop_program(rng):
    """Small cyclic programs for liveness cross-checking (finite state)."""
    nprocs = rng.randint(2, 3)
    out = ["var x : 0..2 = 0;", "var y : 0..2 = 0;", "var z = 0;"]
    for k in range(nprocs):
        alts = []
        for _ in range(rng.randint(1, 3)):
            alts.append("{ " + rand_loop_stmt(rng) + " }")
        guard = rng.choice(["", "", "await x != 2;", "await y == 0;", "await z == 0;"])
        body = f"either {alts[0]}" + "".join(f" or {a}" for a in alts[1:]) if len(alts) > 1 else alts[0][2:-2]
        tail = rng.choice(["", "", "z = 1;"])
        out.append(f"proc Q{k}() {{ loop {{ {guard} {body} {tail} }} }}" if rng.random() < 0.8 else
                   f"proc Q{k}() {{ {guard} {body} z = 1; }}")
        out.append(f"run Q{k}();")
    return "\n".join(out)


def rand_loop_stmt(rng):
    r = rng.random()
    if r < 0.3:
        return "x = (x + 1) % 3;"
    if r < 0.5:
        return "y = (y + 2) % 3;"
    if r < 0.65:
        return "x = 0;"
    if r < 0.8:
        return "y = x;"
    if r < 0.9:
        return "skip;"
    return "z = 1 - z;"
