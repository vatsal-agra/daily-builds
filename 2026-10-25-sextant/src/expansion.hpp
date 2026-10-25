// Floating-point expansion arithmetic (after J. R. Shewchuk, "Adaptive Precision Floating-Point
// Arithmetic and Fast Robust Geometric Predicates", 1997).
//
// An expansion is a vector of doubles, non-overlapping, sorted by increasing magnitude, with zero
// components removed. Its exact value is the sum of the components, and its sign is the sign of the
// last (largest) component. Every operation below is exact barring overflow/underflow.
#pragma once
#include <cmath>
#include <vector>

namespace sextant {

using Exp = std::vector<double>;

// Error-free transforms: a (+) b == x + y exactly, x = fl(a+b).
inline void two_sum(double a, double b, double& x, double& y) {
    x = a + b;
    double bv = x - a;
    double av = x - bv;
    y = (a - av) + (b - bv);
}
inline void two_diff(double a, double b, double& x, double& y) {
    x = a - b;
    double bv = a - x;
    double av = x + bv;
    y = (a - av) + (bv - b);
}
// a * b == x + y exactly (fma yields the rounding error of the product directly).
inline void two_product(double a, double b, double& x, double& y) {
    x = a * b;
    y = std::fma(a, b, -x);
}

inline Exp exp_of(double a) {
    Exp e;
    if (a != 0.0) e.push_back(a);
    return e;
}
inline Exp exp_diff(double a, double b) {
    double x, y;
    two_diff(a, b, x, y);
    Exp e;
    if (y != 0.0) e.push_back(y);
    if (x != 0.0) e.push_back(x);
    return e;
}

// e + b
inline Exp grow(const Exp& e, double b) {
    Exp h;
    h.reserve(e.size() + 1);
    double q = b;
    for (double ei : e) {
        double s, t;
        two_sum(q, ei, s, t);
        q = s;
        if (t != 0.0) h.push_back(t);
    }
    if (q != 0.0 || h.empty()) h.push_back(q);
    if (h.size() == 1 && h[0] == 0.0) h.clear();
    return h;
}

inline Exp add(const Exp& e, const Exp& f) {
    Exp r = e;
    for (double fi : f) r = grow(r, fi);
    return r;
}

inline Exp negate(Exp e) {
    for (double& c : e) c = -c;
    return e;
}

inline Exp sub(const Exp& e, const Exp& f) { return add(e, negate(f)); }

// e * b
inline Exp scale(const Exp& e, double b) {
    Exp h;
    if (e.empty() || b == 0.0) return h;
    h.reserve(2 * e.size());
    double q, hh;
    two_product(e[0], b, q, hh);
    if (hh != 0.0) h.push_back(hh);
    for (size_t i = 1; i < e.size(); ++i) {
        double p1, p0, s, t;
        two_product(e[i], b, p1, p0);
        two_sum(q, p0, s, hh);
        if (hh != 0.0) h.push_back(hh);
        two_sum(p1, s, q, t);
        if (t != 0.0) h.push_back(t);
    }
    if (q != 0.0 || h.empty()) h.push_back(q);
    if (h.size() == 1 && h[0] == 0.0) h.clear();
    return h;
}

inline Exp mul(const Exp& e, const Exp& f) {
    Exp r;
    for (double fi : f) r = add(r, scale(e, fi));
    return r;
}

inline int sign(const Exp& e) {
    if (e.empty()) return 0;
    double top = e.back();
    return top > 0 ? 1 : (top < 0 ? -1 : 0);
}

inline double estimate(const Exp& e) {
    double s = 0;
    for (double c : e) s += c;
    return s;
}

}  // namespace sextant
