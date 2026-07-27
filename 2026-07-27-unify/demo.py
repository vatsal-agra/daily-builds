#!/usr/bin/env python3
"""Runnable verification demo: exercises every feature from PLAN.md end to
end and asserts the result is actually correct, not just "didn't crash".

Run with: python3 demo.py
Exits 0 and prints "ALL CHECKS PASSED" iff every feature works; otherwise
prints exactly which check failed and exits 1.
"""

import json
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer

from unify.cli import run_source, check_source
from unify.repl import ReplState, process_statement, load_prelude
from unify.web.server import run_inference, Handler

CHECKS_RUN = []


def check(name, condition):
    CHECKS_RUN.append((name, bool(condition)))
    status = "ok" if condition else "FAIL"
    print(f"  [{status}] {name}")
    return condition


def section(title):
    print(f"\n=== {title} ===")


def main():
    # ---- Feature 1: lexer + parser --------------------------------------
    section("Feature 1: lexer + parser (examples/*.uy)")
    for fname, expect_ok, expect_type, expect_value in [
        ("examples/factorial.uy", True, "int", "3628800"),
        ("examples/polymorphism.uy", True, "(int, bool)", "(1, true)"),
        ("examples/list_ops.uy", True, "int list", "[2; 4; 6; 8]"),
        ("examples/options.uy", True, "int", "42"),
        ("examples/type_error.uy", False, None, None),
    ]:
        with open(fname) as f:
            source = f.read()
        ok, output = run_source(source)
        check(f"{fname}: ok={expect_ok}", ok == expect_ok)
        if expect_ok:
            check(f"{fname}: type == {expect_type}", f"type: {expect_type}" in output)
            check(f"{fname}: value == {expect_value}", f"value: {expect_value}" in output)
        else:
            check(f"{fname}: reports a diagnostic, not a crash", output.startswith("error:"))

    # ---- Feature 2: Algorithm W type inference ---------------------------
    section("Feature 2: Algorithm W inference (unification, occurs check, let-polymorphism)")
    ok, out = check_source("let id = fun x -> x in (id 1, id true)")
    check("let-polymorphism: id used at int AND bool", ok and "(int, bool)" in out)

    ok, out = check_source("fun x -> x x")
    check("occurs check rejects self-application (infinite type)", not ok and "infinite type" in out)

    ok, out = check_source("1 + true")
    check("type mismatch reports expected/found correctly", not ok and "expected int, found bool" in out)

    ok, out = check_source(
        "let rec len l = match l with | [] -> 0 | _ :: t -> 1 + len t in "
        "(len [1,2,3], len [true,false])"
    )
    check("recursive function is polymorphic across call sites", ok and "(int, int)" in out)

    # ---- Feature 3: tree-walking evaluator --------------------------------
    section("Feature 3: evaluator (recursion, closures, patterns, laziness)")
    ok, out = run_source("let rec fib n = if n < 2 then n else fib (n-1) + fib (n-2) in fib 15")
    check("recursive fib(15) == 610", ok and "value: 610" in out)

    ok, out = run_source("true || (1 / 0 = 0)")
    check("&& / || short-circuit (no division-by-zero here)", ok and "value: true" in out)

    ok, out = run_source("(fun x -> x) = (fun y -> y)")
    check("comparing functions is a clean runtime error, not a silent False", not ok and "compared" in out)

    ok, out = run_source("match None with | Some x -> x")
    check("non-exhaustive match fails cleanly at runtime", not ok and "non-exhaustive" in out)

    # ---- Feature 4: precise diagnostics -----------------------------------
    section("Feature 4: diagnostics (span-anchored, no raw tracebacks)")
    ok, out = check_source("1 + true")
    check("error message has a caret pointing at the culprit", "^" in out and "-->" in out)

    from unify.cli import read_source
    _src, err = read_source("/no/such/file.uy")
    check("missing file -> clean message, not a traceback", err is not None and "cannot read" in err)

    ok, out = run_source(
        "let rec sumto n = if n = 0 then 0 else n + sumto (n - 1) in sumto 500000"
    )
    check("deep recursion -> clean message, not a raw traceback", not ok and "recursion too deep" in out)

    # ---- Stretch 1: REPL with persisted, polymorphic bindings + prelude ---
    section("Stretch feature: REPL (persistent env, prelude, polymorphism across statements)")
    state = ReplState()
    loaded = load_prelude(state)
    check("prelude loads all 7 bindings", loaded == ["map", "filter", "foldl", "length", "append", "reverse", "assoc"])

    ok, msg = process_statement(state, "let inc = fun x -> x + 1")
    ok2, msg2 = process_statement(state, "map inc [1,2,3]")
    check("prelude map() works on a freshly defined function", ok and ok2 and "[2; 3; 4]" in msg2)

    ok, msg = process_statement(state, "let id = fun x -> x")
    ok2, msg2 = process_statement(state, "(id 1, id true)")
    check("polymorphic binding persists AND generalizes across statements", ok and ok2 and "(1, true)" in msg2)

    ok, msg = process_statement(state, "let bad = 1 + true")
    ok2, msg2 = process_statement(state, "inc 41")
    check("a failed statement doesn't corrupt later ones", not ok and ok2 and "42" in msg2)

    # ---- Stretch 2: web visualizer (real HTTP server, zero client logic) -
    section("Stretch feature: web visualizer (server-backed, real http.server)")
    result = run_inference("let id = fun x -> x in (id 1, id true)")
    check("run_inference: correct type", result["ok"] and result["type"] == "(int, bool)")
    check("run_inference: derivation tree present", result["derivation"]["label"] == "Let")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.2)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            check("GET / returns 200", resp.status == 200)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/infer",
            data=json.dumps({"source": "1 + 2"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read())
        check("POST /api/infer over real HTTP returns correct type", payload["type"] == "int")
        check("POST /api/infer over real HTTP returns correct value", payload["value"] == "3")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    # ---- Summary -----------------------------------------------------------
    section("Summary")
    failed = [name for name, ok in CHECKS_RUN if not ok]
    print(f"{len(CHECKS_RUN) - len(failed)}/{len(CHECKS_RUN)} checks passed.")
    if failed:
        print("FAILED:")
        for name in failed:
            print(f"  - {name}")
        print("\nSOME CHECKS FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
