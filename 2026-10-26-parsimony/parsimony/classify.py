"""Decide which classical grammar classes a grammar belongs to."""
from __future__ import annotations

from typing import List, Tuple

from .api import Language

ORDER = [("LR(0)", "lr0"), ("SLR(1)", "slr"), ("LALR(1)", "lalr"), ("LR(1)", "lr1")]


def classify(lang: Language) -> List[Tuple[str, bool, str]]:
    """Rows of (class, is-member, detail). LR rows honour %left/%right precedence."""
    rows = []
    try:
        from .ll1 import build_ll1
        twin = lang.ll1_language()
        t = build_ll1(twin.grammar, twin.analysis)
        rows.append(("LL(1)", not t.conflicts, f"{len(t.conflicts)} conflict(s)" if t.conflicts else "predictive table is conflict-free"))
    except ImportError:
        pass
    for name, m in ORDER:
        t = lang.table(m)
        detail = f"{t.n_states} states, {len(t.conflicts)} unresolved conflict(s)"
        if t.resolved:
            detail += f", {len(t.resolved)} settled by precedence"
        rows.append((name, not t.conflicts, detail))
    return rows


def format_classification(rows) -> str:
    out = ["grammar classes:"]
    for name, ok, detail in rows:
        out.append(f"  {'✔' if ok else '✘'} {name:<8} {detail}")
    members = [n for n, ok, d in rows if ok and n != "LL(1)"]
    if members:
        via = any("precedence" in d for n, ok, d in rows if n == members[0])
        out.append(f"→ smallest LR class: {members[0]}" + (" (given the %left/%right/%prec declarations)" if via else ""))
    else:
        out.append("→ not LR(1): ambiguous or inherently non-deterministic — use `ambig`/Earley")
    return "\n".join(out)
