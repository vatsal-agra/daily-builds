// Voronoi diagram, convex hull, centroidal relaxation — all derived from a Delaunay triangulation.
#pragma once
#include <vector>

#include "predicates.hpp"
#include "triangulation.hpp"

namespace sextant {

struct Box {
    double x0, y0, x1, y1;
    double width() const { return x1 - x0; }
    double height() const { return y1 - y0; }
};

// Bounding box of the points, grown by `margin` (fraction of the larger side, at least a tiny absolute).
Box bounding_box(const std::vector<Pt>& pts, double margin);

struct VoronoiCell {
    int site = -1;               // vertex index
    std::vector<Pt> polygon;     // counter-clockwise, clipped to the box; empty if outside the box
    bool unbounded = false;      // true if the unclipped cell extends to infinity (hull site)
};

// One cell per distinct input site (duplicates share the canonical site's cell).
std::vector<VoronoiCell> voronoi_cells(const Triangulation& dt, const Box& box);

// Exact convex hull by Andrew's monotone chain on the exact orient2d predicate. Counter-clockwise,
// no collinear points, no duplicates. Independent of the triangulation.
std::vector<int> convex_hull(const std::vector<Pt>& pts);

double polygon_area(const std::vector<Pt>& poly);  // signed
Pt polygon_centroid(const std::vector<Pt>& poly);

struct LloydReport {
    std::vector<double> energy;  // quantisation energy before each iteration + final
};
// Lloyd relaxation: move every site to the centroid of its (box-clipped) Voronoi cell.
std::vector<Pt> lloyd(const std::vector<Pt>& pts, const Box& box, int iterations, LloydReport* rep = nullptr);

// Quantisation energy sum_i integral over cell_i of |x - site_i|^2 dA (exact for polygons).
double cell_energy(const VoronoiCell& c, const Pt& site);

}  // namespace sextant
