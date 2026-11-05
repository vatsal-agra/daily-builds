"""Differential helper: assemble each corpus line with GNU as and Ferrule, report mismatches."""
import subprocess, sys, tempfile, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ferrule.asm import assemble

HDR = ".intel_syntax noprefix\n.text\n"


def gas_bytes(src, d):
    s, o, b = (os.path.join(d, n) for n in ("x.s", "x.o", "x.bin"))
    open(s, "w").write(HDR + src + "\n")
    r = subprocess.run(["as", "--64", "-msyntax=intel", "-mnaked-reg", "-o", o, s], capture_output=True, text=True)
    if r.returncode:
        return None
    subprocess.run(["objcopy", "-O", "binary", "-j", ".text", o, b], check=True)
    return open(b, "rb").read()


def ferrule_bytes(src):
    obj = assemble(HDR + src + "\n", "x.s")
    return next(s for s in obj.sections if s.name == ".text").data


def run(lines):
    bad = []
    with tempfile.TemporaryDirectory() as d:
        for ln in lines:
            ln = ln.strip()
            if not ln or ln.startswith((".", "#", ";")) or ln.endswith(":"):
                continue
            g = gas_bytes(ln, d)
            try:
                f = ferrule_bytes(ln)
            except Exception as ex:
                f = f"ERR {ex}"
            if g != f:
                bad.append((ln, g.hex() if g is not None else None, f.hex() if isinstance(f, bytes) else f))
    return bad


if __name__ == "__main__":
    lines = open(sys.argv[1]).read().splitlines()
    bad = run(lines)
    for b in bad:
        print(b)
    print(f"{len(bad)} mismatches of {len(lines)} lines")
