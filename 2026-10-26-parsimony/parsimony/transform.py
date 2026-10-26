"""Grammar transformations that push a grammar toward LL(1):
immediate + indirect left-recursion elimination (Paull's algorithm) and left factoring."""
from __future__ import annotations

from typing import Dict, List, Tuple

from .analysis import Analysis
from .grammar import Grammar, GrammarError, Production

Alt = List[str]


def make_ll1_friendly(g: Grammar) -> Tuple[Grammar, List[str]]:
    """Return (new grammar, human-readable log). Language is preserved; tree shape is not
    (left-recursive lists become right-leaning helper chains, which are hidden in trees)."""
    an = Analysis(g)
    if an.cyclic():
        raise GrammarError("cannot transform a cyclic grammar (A ⇒+ A): remove the cycle first")
    log: List[str] = []
    rules: Dict[str, List[Alt]] = {nt: [list(p.rhs) for p in g.by_lhs.get(nt, [])] for nt in g.nonterminals}
    order = list(g.nonterminals)
    hidden = set(g.hidden)

    def fresh(base: str, tag: str) -> str:
        i, name = 1, f"{base}_{tag}"
        while name in rules:
            i += 1; name = f"{base}_{tag}{i}"
        rules[name] = []; order.append(name); hidden.add(name)
        return name

    # --- left recursion (Paull); only nonterminals that actually take part in a left-recursive
    # cycle are touched, so already-LL-friendly rules are left exactly as written.
    in_cycle = {nt for comp in an.left_recursive() for nt in comp}
    cyc_order = [nt for nt in order if nt in in_cycle]
    for i, a in enumerate(list(cyc_order)):
        for b in cyc_order[:i]:
            if b not in rules or not rules[a]:
                continue
            new, substituted = [], False
            for alt in rules[a]:
                if alt and alt[0] == b:
                    substituted = True
                    new.extend(beta + alt[1:] for beta in rules[b])
                else:
                    new.append(alt)
            if substituted:
                log.append(f"substituted {b} into the leftmost position of {a}")
                rules[a] = new
        rec = [alt[1:] for alt in rules[a] if alt and alt[0] == a]
        if rec:
            base = [alt for alt in rules[a] if not (alt and alt[0] == a)]
            tail = fresh(a, "tail")
            rules[a] = [beta + [tail] for beta in base] if base else []
            rules[tail] = [alpha + [tail] for alpha in rec] + [[]]
            log.append(f"eliminated left recursion of {a}: new helper {tail}")

    # --- left factoring (to a fixpoint)
    changed = True
    while changed:
        changed = False
        for a in list(order):
            groups: Dict[str, List[Alt]] = {}
            for alt in rules[a]:
                groups.setdefault(alt[0] if alt else "", []).append(alt)
            for first, alts in groups.items():
                if first == "" or len(alts) < 2:
                    continue
                k = 1
                while all(len(x) > k for x in alts) and len({x[k] for x in alts}) == 1:
                    k += 1
                prefix = alts[0][:k]
                helper = fresh(a, "f")
                rules[helper] = [x[k:] for x in alts]
                rules[a] = [x for x in rules[a] if x not in alts] + [prefix + [helper]]
                log.append(f"left-factored {a}: common prefix '{' '.join(prefix)}' → {helper}")
                changed = True
                break
            if changed:
                break

    prods: List[Production] = []
    nts = [nt for nt in order if rules.get(nt)]
    for nt in nts:
        seen = []
        for alt in rules[nt]:
            if alt not in seen:
                seen.append(alt)
                prods.append(Production(len(prods), nt, tuple(alt)))
    if not log:
        log.append("nothing to do: no left recursion and no common prefixes")
    return g.copy_with(prods, nts, hidden), log
