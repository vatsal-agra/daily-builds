"""Warren: a from-scratch Prolog compiling to a real Warren Abstract
Machine (WAM)."""
import sys

# Several bridge functions between the parser/golden-model Term
# representation and the WAM heap (term_vars, copy_term, unify,
# heap_unify, reify, push_term_cached, unify_heap_with_term, and the
# pretty-printer) walk terms with plain Python recursion, one frame per
# list cell / nested structure level -- so a long list (Prolog lists are
# right-nested cons cells) can exhaust Python's default recursion limit
# well within normal-sized data. Real WAM heap operations don't have
# this problem (their "recursion" is just heap-address arithmetic), but
# these particular bridge points do; raising the limit is the pragmatic
# fix documented in REVIEW.md. `warren.cli` additionally runs on a
# larger OS thread stack so the raised limit doesn't just trade a clean
# RecursionError for a hard segfault.
sys.setrecursionlimit(200_000)
