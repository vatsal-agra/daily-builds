"""Renders a decoded Module IR back to readable `.kwat`-flavored text —
used to sanity-check round-tripping and as a `kiln disasm` subcommand."""

from .wasm.types import VALTYPE_NAMES


def _fmt_blocktype(bt):
    if bt is None:
        return ""
    if bt in VALTYPE_NAMES:
        return f" (result {VALTYPE_NAMES[bt]})"
    return f" (type {bt})"


def _render_instrs(instrs, indent):
    out = []
    pad = "  " * indent
    for instr in instrs:
        if instr.op in ("block", "loop"):
            out.append(f"{pad}{instr.op}{_fmt_blocktype(instr.imm)}")
            out.extend(_render_instrs(instr.body, indent + 1))
            out.append(f"{pad}end")
        elif instr.op == "if":
            out.append(f"{pad}if{_fmt_blocktype(instr.imm)}")
            out.extend(_render_instrs(instr.body, indent + 1))
            if instr.else_body is not None:
                out.append(f"{pad}else")
                out.extend(_render_instrs(instr.else_body, indent + 1))
            out.append(f"{pad}end")
        elif instr.imm is None:
            out.append(f"{pad}{instr.op}")
        elif instr.op == "br_table":
            labels, default = instr.imm
            out.append(f"{pad}br_table {' '.join(map(str, labels))} {default}")
        elif instr.op.endswith(("load", "load8_s", "load8_u", "load16_s", "load16_u",
                                 "load32_s", "load32_u", "store", "store8", "store16", "store32")):
            align, offset = instr.imm
            out.append(f"{pad}{instr.op} offset={offset} align={align}")
        else:
            out.append(f"{pad}{instr.op} {instr.imm}")
    return out


def disassemble(module):
    lines = ["(module"]
    for i, t in enumerate(module.types):
        params = " ".join(VALTYPE_NAMES[p] for p in t.params)
        results = " ".join(VALTYPE_NAMES[r] for r in t.results)
        lines.append(f"  ;; type {i}: (param {params}) -> (result {results})")
    for imp in module.imports:
        lines.append(f"  (import \"{imp.module}\" \"{imp.name}\" ({imp.kind}))")
    for i, f in enumerate(module.functions):
        fidx = module.num_imported_funcs() + i
        lines.append(f"  (func ${fidx} (type {f.type_index})")
        lines.extend(_render_instrs(f.body, 2))
        lines.append("  )")
    for e in module.exports:
        lines.append(f"  (export \"{e.name}\" ({e.kind} {e.index}))")
    lines.append(")")
    return "\n".join(lines)
