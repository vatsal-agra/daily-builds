#pragma once
#include <string>
#include <utility>
#include <vector>

#include "predicates.hpp"

namespace sextant {

struct Input {
    std::vector<Pt> pts;
    std::vector<std::pair<int, int>> segs;
};

// Text format (one item per line, '#' starts a comment):
//   x y            a vertex          (also:  v x y)
//   s i j          a segment between 0-based vertex indices i and j
Input parse_input(const std::string& text, const std::string& name = "<input>");
Input read_input_file(const std::string& path);  // "-" reads stdin
std::string format_input(const Input& in);

// Generators for test and demo data. Throws std::invalid_argument for unknown kinds.
Input generate(const std::string& kind, int n, unsigned seed);
std::vector<std::string> generator_kinds();

}  // namespace sextant
