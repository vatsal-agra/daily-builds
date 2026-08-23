"""
WASM binary -> WAT-like text disassembler.

Deliberately built against the *decoder* (interpreter.decode_module), not
against our own codegen's instruction lists — so it proves the decoder is a
real, general binary-format reader rather than something secretly coupled
to the exact shape our own encoder happens to produce.
"""

from .interpreter import decode_module, EXPORT_KIND_FUNC


def disassemble(wasm_bytes):
    mod = decode_module(wasm_bytes)
    lines = [";; Runic disassembly", "(module"]

    idx_to_export_name = {}
    for name, (kind, idx) in mod["exports"].items():
        if kind == EXPORT_KIND_FUNC:
            idx_to_export_name.setdefault(idx, []).append(name)

    if mod["memory_pages"] is not None:
        lines.append(f"  (memory {mod['memory_pages']})")
    for seg in mod["data"]:
        preview = ", ".join(str(b) for b in seg["bytes"][:16])
        more = "..." if len(seg["bytes"]) > 16 else ""
        lines.append(f"  (data (i32.const {seg['offset']}) \"{len(seg['bytes'])} bytes: {preview}{more}\")")

    for fidx, body in enumerate(mod["code"]):
        nparams, _nresults = mod["types"][mod["func_typeidx"][fidx]]
        names = idx_to_export_name.get(fidx, [])
        label = names[0] if names else f"$f{fidx}"
        params = " ".join(f"(param $p{i} i32)" for i in range(nparams))
        lines.append(f"  (func ${label} {params} (result i32)")
        if body["num_locals"]:
            locs = " ".join(f"(local $l{i} i32)" for i in range(body["num_locals"]))
            lines.append(f"    {locs}")
        depth = 2
        for op, imm in body["instrs"]:
            if op in ("end", "else"):
                depth -= 1
            indent = "  " * depth
            if imm is None:
                lines.append(f"{indent}{op}")
            elif op in ("block", "loop", "if"):
                tag = "i32" if imm == 0x7F else ""
                lines.append(f"{indent}{op} {tag}".rstrip())
            elif op == "i32.const":
                lines.append(f"{indent}{op} {imm}")
            elif op in ("br", "br_if"):
                lines.append(f"{indent}{op} {imm}")
            elif op == "call":
                callee_names = idx_to_export_name.get(imm, [f"f{imm}"])
                lines.append(f"{indent}{op} ${callee_names[0]}")
            elif op in ("local.get", "local.set", "local.tee"):
                lines.append(f"{indent}{op} {imm}")
            elif op in ("i32.load", "i32.store"):
                align, offset = imm
                lines.append(f"{indent}{op} offset={offset} align={align}")
            else:
                lines.append(f"{indent}{op} {imm}")
            if op in ("block", "loop", "if"):
                depth += 1
        lines.append("  )")

    lines.append(")")
    return "\n".join(lines)
