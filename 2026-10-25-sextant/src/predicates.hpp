// Exact geometric predicates. Both return the *correct sign* for every finite double input whose
// intermediate values neither overflow nor underflow (|coordinate differences| in ~[1e-140, 1e140]).
#pragma once
#include <cstdint>

namespace sextant {

struct Pt {
    double x = 0, y = 0;
    bool operator==(const Pt& o) const { return x == o.x && y == o.y; }
};

// +1 if a,b,c are in counter-clockwise order, -1 if clockwise, 0 if exactly collinear.
int orient2d(const Pt& a, const Pt& b, const Pt& c);

// +1 if d lies strictly inside the circle through a,b,c (given in counter-clockwise order),
// -1 if strictly outside, 0 if exactly on it. For clockwise a,b,c the sign is reversed.
int incircle(const Pt& a, const Pt& b, const Pt& c, const Pt& d);

// Statistics (how often each stage of the filter cascade decided the answer).
struct PredicateStats {
    uint64_t orient_fast = 0, orient_exact = 0, incircle_fast = 0, incircle_exact = 0;
};
PredicateStats& predicate_stats();
void reset_predicate_stats();

// Always-exact variants (skip the filter) — used by the tests to check the filter itself.
int orient2d_exact(const Pt& a, const Pt& b, const Pt& c);
int incircle_exact(const Pt& a, const Pt& b, const Pt& c, const Pt& d);

}  // namespace sextant
