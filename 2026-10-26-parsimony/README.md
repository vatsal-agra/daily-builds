# Parsimony
Parser-generator laboratory (LL(1), SLR, LALR(1), LR(1), Earley).

**Status: Phase 3 — adversarial review done** (REVIEW.md; 10 findings fixed, #11 lands in Phase 4).
Working: grammar DSL (+EBNF, precedence), analysis (`check`), LR(0)/SLR/LALR/LR(1) tables with
conflict diagnostics (`conflicts`, `states`), shift-reduce parsing with tree/sexp/JSON + trace
(`parse`), Earley with parse counting and enumeration (`ambig`). See PLAN.md. Try:

    python3 -m parsimony check examples/slr_fails.pg
    python3 -m parsimony parse examples/expr.pg -e '1 + 2 * 3' --compact
    python3 -m parsimony ambig examples/ambiguous.pg -e 'n+n+n+n'
