# Parsimony
Parser-generator laboratory (LL(1), SLR, LALR(1), LR(1), Earley).

**Status: Phase 4 — stretch features done** (LL(1) + grammar transformer, standalone code generator,
yacc-style error recovery, ambiguity witnesses, self-check grammar). Commands:

    python3 -m parsimony check|conflicts|states|parse|compare|ambig|witness|ll1|transform|gen GRAMMAR ...

See PLAN.md and REVIEW.md. Try:

    python3 -m parsimony check examples/slr_fails.pg
    python3 -m parsimony parse examples/expr.pg -e '1 + 2 * 3' --compact
    python3 -m parsimony witness examples/dangling_else.pg
