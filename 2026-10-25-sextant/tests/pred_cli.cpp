// Reads "o ax ay bx by cx cy" / "i ax ay bx by cx cy dx dy" (hex floats) and prints, per line,
// "<filtered> <exact>" signs. Used by predicate_diff.py to compare against a Fraction oracle.
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>

#include "predicates.hpp"

using namespace sextant;

int main() {
    std::string line;
    while (std::getline(std::cin, line)) {
        std::istringstream ss(line);
        std::string kind;
        ss >> kind;
        double v[8];
        int n = kind == "o" ? 6 : 8;
        for (int i = 0; i < n; ++i) {
            std::string tok;
            ss >> tok;
            v[i] = std::strtod(tok.c_str(), nullptr);
        }
        if (kind == "o") {
            Pt a{v[0], v[1]}, b{v[2], v[3]}, c{v[4], v[5]};
            std::printf("%d %d\n", orient2d(a, b, c), orient2d_exact(a, b, c));
        } else {
            Pt a{v[0], v[1]}, b{v[2], v[3]}, c{v[4], v[5]}, d{v[6], v[7]};
            std::printf("%d %d\n", incircle(a, b, c, d), incircle_exact(a, b, c, d));
        }
    }
    auto& s = predicate_stats();
    std::fprintf(stderr, "orient: %llu fast %llu exact; incircle: %llu fast %llu exact\n", (unsigned long long)s.orient_fast,
                 (unsigned long long)s.orient_exact, (unsigned long long)s.incircle_fast, (unsigned long long)s.incircle_exact);
}
