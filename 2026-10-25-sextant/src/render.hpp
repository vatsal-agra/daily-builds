#pragma once
#include <array>
#include <string>
#include <vector>

#include "predicates.hpp"
#include "triangulation.hpp"
#include "voronoi.hpp"

namespace sextant {

struct Scene {
    std::string title;
    std::vector<Pt> pts;
    std::vector<char> is_site;                     // pts that are real vertices (not duplicates)
    std::vector<std::array<int, 3>> tris;
    std::vector<std::pair<int, int>> segs;         // constrained segments
    std::vector<VoronoiCell> cells;                // optional
    std::vector<int> hull;                         // optional (indices, ccw)
    Box box{0, 0, 1, 1};
    bool has_box = false;
};

Scene scene_from(const Triangulation& dt, bool inside_only, const std::string& title);

struct SvgOptions {
    bool fill_by_angle = true;   // colour triangles by their minimum angle
    bool show_points = true;
    int width = 900;
};
std::string render_svg(const Scene& s, const SvgOptions& opt = {});
// Self-contained interactive page (see viewer.cpp).
std::string render_html(const Scene& s);

}  // namespace sextant
