"""Entropy analysis and a side-by-side codec comparison table.

Compares every codec's *actual* container size against the information-theoretic
lower bounds (order-0 and order-1 entropy) and names the winner. This is both a
useful tool and a sanity oracle: a coder that beats its model's entropy bound (or
that expands random data well past the container overhead) would be a red flag.
"""
from __future__ import annotations

from . import codecs, container, entropy


def measure(data: bytes):
    """Return a dict of analysis numbers for ``data``."""
    n = len(data)
    results = []
    for name in codecs.ALL_NAMES:
        blob = container.pack(name, data)
        # confirm correctness while we are here
        ok = container.unpack(blob) == data
        results.append((name, len(blob), ok))
    return {
        "length": n,
        "distinct": len(set(data)),
        "h0": entropy.order0_entropy(data),
        "h1": entropy.order1_entropy(data),
        "ideal0": entropy.ideal_bytes(data, 0),
        "ideal1": entropy.ideal_bytes(data, 1),
        "codecs": results,
    }


def _bar(frac: float, width: int = 24) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * width)
    return "█" * filled + "·" * (width - filled)


def report(data: bytes, label: str = "input") -> str:
    m = measure(data)
    n = m["length"]
    lines = []
    lines.append(f"Shannon analysis — {label}")
    lines.append("=" * 60)
    lines.append(f"length          : {n} bytes")
    lines.append(f"distinct symbols: {m['distinct']}")
    if n:
        lines.append(f"order-0 entropy : {m['h0']:.3f} bits/byte  "
                     f"(ideal ≥ {m['ideal0']:.0f} bytes)")
        lines.append(f"order-1 entropy : {m['h1']:.3f} bits/byte  "
                     f"(ideal ≥ {m['ideal1']:.0f} bytes)")
    lines.append("")
    lines.append(f"{'codec':9s} {'bytes':>8s} {'ratio':>7s}  bar (vs original)")
    lines.append("-" * 60)
    results = sorted(m["codecs"], key=lambda r: r[1])
    best_name = results[0][0]
    for name, size, ok in results:
        ratio = (size / n) if n else 0.0
        flag = "" if ok else "  !! ROUND-TRIP FAILED"
        star = " *" if name == best_name else "  "
        lines.append(f"{name:9s} {size:8d} {ratio:7.3f}  {_bar(ratio)}{star}{flag}")
    lines.append("-" * 60)
    if n:
        best_size = results[0][1]
        lines.append(f"winner: {best_name} ({best_size} bytes, "
                     f"{(1 - best_size / n) * 100:.1f}% smaller than original)")
        # how close is the best entropy coder to its bound?
        a0 = next(s for nm, s, _ in m["codecs"] if nm == "arith0")
        if m["ideal0"] > 0:
            lines.append(f"arith0 overhead vs order-0 bound: "
                         f"{(a0 - m['ideal0']) / m['ideal0'] * 100:+.1f}%")
    return "\n".join(lines)
