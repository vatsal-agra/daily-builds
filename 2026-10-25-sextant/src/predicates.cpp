#include "predicates.hpp"

#include <cmath>

#include "expansion.hpp"

namespace sextant {

namespace {
constexpr double kEps = 1.1102230246251565e-16;  // 2^-53
constexpr double kOrientBound = (3.0 + 16.0 * kEps) * kEps;
constexpr double kIncircleBound = (10.0 + 96.0 * kEps) * kEps;
PredicateStats g_stats;
}  // namespace

PredicateStats& predicate_stats() { return g_stats; }
void reset_predicate_stats() { g_stats = PredicateStats{}; }

int orient2d_exact(const Pt& a, const Pt& b, const Pt& c) {
    Exp acx = exp_diff(a.x, c.x), acy = exp_diff(a.y, c.y);
    Exp bcx = exp_diff(b.x, c.x), bcy = exp_diff(b.y, c.y);
    Exp det = sub(mul(acx, bcy), mul(acy, bcx));
    return sign(det);
}

int orient2d(const Pt& a, const Pt& b, const Pt& c) {
    double detleft = (a.x - c.x) * (b.y - c.y);
    double detright = (a.y - c.y) * (b.x - c.x);
    double det = detleft - detright;
    double detsum;
    if (detleft > 0.0) {
        if (detright <= 0.0) { ++g_stats.orient_fast; return det > 0 ? 1 : (det < 0 ? -1 : 0); }
        detsum = detleft + detright;
    } else if (detleft < 0.0) {
        if (detright >= 0.0) { ++g_stats.orient_fast; return det > 0 ? 1 : (det < 0 ? -1 : 0); }
        detsum = -detleft - detright;
    } else {
        if (detright == 0.0) {
            // Both products zero in floating point: could still hide underflow-free exact
            // non-zero only if a difference is exactly zero, in which case the det is truly 0.
            // (A product is 0 only if a factor is 0 — barring underflow — so det == 0 exactly.)
            ++g_stats.orient_fast;
            return 0;
        }
        ++g_stats.orient_fast;
        return detright > 0 ? -1 : 1;
    }
    double errbound = kOrientBound * detsum;
    if (det >= errbound || -det >= errbound) { ++g_stats.orient_fast; return det > 0 ? 1 : -1; }
    ++g_stats.orient_exact;
    return orient2d_exact(a, b, c);
}

int incircle_exact(const Pt& a, const Pt& b, const Pt& c, const Pt& d) {
    Exp adx = exp_diff(a.x, d.x), ady = exp_diff(a.y, d.y);
    Exp bdx = exp_diff(b.x, d.x), bdy = exp_diff(b.y, d.y);
    Exp cdx = exp_diff(c.x, d.x), cdy = exp_diff(c.y, d.y);
    Exp alift = add(mul(adx, adx), mul(ady, ady));
    Exp blift = add(mul(bdx, bdx), mul(bdy, bdy));
    Exp clift = add(mul(cdx, cdx), mul(cdy, cdy));
    Exp bc = sub(mul(bdx, cdy), mul(cdx, bdy));
    Exp ca = sub(mul(cdx, ady), mul(adx, cdy));
    Exp ab = sub(mul(adx, bdy), mul(bdx, ady));
    Exp det = add(add(mul(alift, bc), mul(blift, ca)), mul(clift, ab));
    return sign(det);
}

int incircle(const Pt& a, const Pt& b, const Pt& c, const Pt& d) {
    double adx = a.x - d.x, bdx = b.x - d.x, cdx = c.x - d.x;
    double ady = a.y - d.y, bdy = b.y - d.y, cdy = c.y - d.y;
    double bdxcdy = bdx * cdy, cdxbdy = cdx * bdy;
    double cdxady = cdx * ady, adxcdy = adx * cdy;
    double adxbdy = adx * bdy, bdxady = bdx * ady;
    double alift = adx * adx + ady * ady;
    double blift = bdx * bdx + bdy * bdy;
    double clift = cdx * cdx + cdy * cdy;
    double det = alift * (bdxcdy - cdxbdy) + blift * (cdxady - adxcdy) + clift * (adxbdy - bdxady);
    double permanent = (std::fabs(bdxcdy) + std::fabs(cdxbdy)) * alift +
                       (std::fabs(cdxady) + std::fabs(adxcdy)) * blift +
                       (std::fabs(adxbdy) + std::fabs(bdxady)) * clift;
    double errbound = kIncircleBound * permanent;
    if (det > errbound || -det > errbound) { ++g_stats.incircle_fast; return det > 0 ? 1 : -1; }
    ++g_stats.incircle_exact;
    return incircle_exact(a, b, c, d);
}

}  // namespace sextant
