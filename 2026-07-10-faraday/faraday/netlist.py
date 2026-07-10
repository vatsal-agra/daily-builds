"""A small SPICE-like textual netlist format.

Not a literal SPICE-compatible parser (that's a much bigger spec), but the
same shape: one element per line, `<name> <nodes...> <value/spec>`, `*` for
comments, engineering suffixes (`1k`, `4.7u`, `10meg`, ...) on numbers.

    * RC low-pass filter
    V1 in 0 DC 5 AC 1
    R1 in out 1k
    C1 out 0 100n
    .tran 1u 5m
    .end

Element prefixes: R C L V I D (standard SPICE letters) plus O for an ideal
op-amp (`O1 v+ v- vout`), which isn't standard SPICE but has no standard
single-letter equivalent either.
"""

import re

from .elements import (Resistor, Capacitor, Inductor, VSource, ISource,
                        Diode, OpAmp, _pulse, _sine)

_SUFFIXES = [("meg", 1e6), ("t", 1e12), ("g", 1e9), ("k", 1e3), ("m", 1e-3),
             ("u", 1e-6), ("n", 1e-9), ("p", 1e-12), ("f", 1e-15)]

_NUM_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(.*)$")


def parse_value(s):
    s = s.strip()
    m = _NUM_RE.match(s)
    if not m:
        raise ValueError(f"bad numeric value {s!r}")
    value = float(m.group(1))
    rest = m.group(2).lower()
    for suf, mult in _SUFFIXES:
        if rest.startswith(suf):
            return value * mult
    return value


def format_value(v):
    """Round-trippable, human-friendly number formatting for export."""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def _tokenize(line):
    tokens = []
    i, n = 0, len(line)
    while i < n:
        if line[i].isspace():
            i += 1
            continue
        if line[i] == "(":
            depth, j = 1, i + 1
            while j < n and depth > 0:
                depth += 1 if line[j] == "(" else -1 if line[j] == ")" else 0
                j += 1
            if not tokens:
                raise ValueError(f"stray parenthesis group in: {line!r}")
            tokens[-1] += line[i:j]
            i = j
        else:
            j = i
            while j < n and not line[j].isspace() and line[j] != "(":
                j += 1
            tokens.append(line[i:j])
            i = j
    return tokens


def _inner_paren(tok):
    start, end = tok.index("("), tok.rindex(")")
    return tok[start + 1:end]


def _parse_kv(tokens):
    kv = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            kv[k.upper()] = v
    return kv


def _parse_source_spec(name, tokens):
    dc_value, waveform, ac_mag, ac_phase = 0.0, None, 0.0, 0.0
    i = 0
    if i < len(tokens) and tokens[i].upper() == "DC":
        i += 1
        dc_value = parse_value(tokens[i])
        i += 1
    elif i < len(tokens) and tokens[i].upper().startswith("PULSE"):
        parts = [parse_value(p) for p in _inner_paren(tokens[i]).split()]
        if len(parts) != 7:
            raise ValueError(f"{name}: PULSE(...) needs 7 args "
                              f"(v1 v2 delay rise fall width period), got {len(parts)}")
        v1, v2, delay, rise, fall, width, period = parts
        dc_value = v1
        waveform = _pulse(v1, v2, delay, rise, fall, width, period)
        i += 1
    elif i < len(tokens) and tokens[i].upper().startswith("SIN"):
        parts = [parse_value(p) for p in _inner_paren(tokens[i]).split()]
        if len(parts) < 3:
            raise ValueError(f"{name}: SIN(...) needs at least "
                              f"(offset amplitude freq), got {len(parts)}")
        offset, amplitude, freq = parts[0], parts[1], parts[2]
        delay = parts[3] if len(parts) > 3 else 0.0
        damping = parts[4] if len(parts) > 4 else 0.0
        dc_value = offset
        waveform = _sine(offset, amplitude, freq, delay, damping)
        i += 1
    elif i < len(tokens) and tokens[i].upper() != "AC":
        dc_value = parse_value(tokens[i])
        i += 1

    if i < len(tokens) and tokens[i].upper() == "AC":
        i += 1
        if i >= len(tokens):
            raise ValueError(f"{name}: AC needs a magnitude")
        ac_mag = parse_value(tokens[i])
        i += 1
        if i < len(tokens):
            ac_phase = parse_value(tokens[i])
            i += 1
    if i != len(tokens):
        raise ValueError(f"{name}: unexpected trailing tokens {tokens[i:]!r}")
    return dc_value, waveform, ac_mag, ac_phase


def parse_netlist(text):
    """Returns (elements, directives). directives is a list of
    (command, args) tuples for lines starting with '.' (e.g. '.tran')."""
    elements = []
    directives = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(";", 1)[0].strip()  # ';' starts an end-of-line comment
        if not line or line.startswith("*"):
            continue
        if line.startswith("."):
            parts = line[1:].split()
            directives.append((parts[0].lower(), parts[1:]))
            continue
        try:
            tokens = _tokenize(line)
            if len(tokens) < 3:
                raise ValueError("expected at least: name node1 node2 ...")
            name = tokens[0]
            prefix = name[0].upper()
            if prefix == "R":
                elements.append(Resistor(name, tokens[1], tokens[2], parse_value(tokens[3])))
            elif prefix == "C":
                kv = _parse_kv(tokens[4:])
                ic = parse_value(kv["IC"]) if "IC" in kv else 0.0
                elements.append(Capacitor(name, tokens[1], tokens[2], parse_value(tokens[3]), ic=ic))
            elif prefix == "L":
                kv = _parse_kv(tokens[4:])
                ic = parse_value(kv["IC"]) if "IC" in kv else 0.0
                elements.append(Inductor(name, tokens[1], tokens[2], parse_value(tokens[3]), ic=ic))
            elif prefix == "V":
                dc_v, wf, ac_m, ac_p = _parse_source_spec(name, tokens[3:])
                elements.append(VSource(name, tokens[1], tokens[2], dc_v, wf, ac_m, ac_p))
            elif prefix == "I":
                dc_v, wf, ac_m, ac_p = _parse_source_spec(name, tokens[3:])
                elements.append(ISource(name, tokens[1], tokens[2], dc_v, wf, ac_m, ac_p))
            elif prefix == "D":
                kv = _parse_kv(tokens[3:])
                elements.append(Diode(
                    name, tokens[1], tokens[2],
                    Is=parse_value(kv["IS"]) if "IS" in kv else 1e-14,
                    n=parse_value(kv["N"]) if "N" in kv else 1.0,
                    Vt=parse_value(kv["VT"]) if "VT" in kv else 0.025852,
                ))
            elif prefix == "O":
                if len(tokens) < 4:
                    raise ValueError("op-amp needs: name n+ n- n_out")
                elements.append(OpAmp(name, tokens[1], tokens[2], tokens[3]))
            else:
                raise ValueError(f"unknown element prefix {prefix!r} (expected R/C/L/V/I/D/O)")
        except (ValueError, IndexError) as exc:
            raise ValueError(f"netlist line {lineno}: {raw.strip()!r}: {exc}") from exc
    return elements, directives


def to_netlist(elements, directives=None, title=None):
    lines = [f"* {title}"] if title else []
    for e in elements:
        if isinstance(e, Resistor):
            lines.append(f"{e.name} {e.n1} {e.n2} {format_value(e.resistance)}")
        elif isinstance(e, Capacitor):
            ic = f" IC={format_value(e.ic)}" if e.ic else ""
            lines.append(f"{e.name} {e.n1} {e.n2} {format_value(e.capacitance)}{ic}")
        elif isinstance(e, Inductor):
            ic = f" IC={format_value(e.ic)}" if e.ic else ""
            lines.append(f"{e.name} {e.n1} {e.n2} {format_value(e.inductance)}{ic}")
        elif isinstance(e, (VSource, ISource)):
            spec = f"DC {format_value(e.dc_value)}"
            ac = f" AC {format_value(e.ac_mag)}" if e.ac_mag else ""
            lines.append(f"{e.name} {e.n_pos} {e.n_neg} {spec}{ac}")
        elif isinstance(e, Diode):
            lines.append(f"{e.name} {e.n_pos} {e.n_neg} IS={e.Is} N={e.n}")
        elif isinstance(e, OpAmp):
            lines.append(f"{e.name} {e.n_plus} {e.n_minus} {e.n_out}")
        else:
            raise TypeError(f"cannot serialize element type {type(e)!r}")  # pragma: no cover
    for cmd, args in directives or []:
        lines.append(f".{cmd} {' '.join(args)}")
    return "\n".join(lines) + "\n"
