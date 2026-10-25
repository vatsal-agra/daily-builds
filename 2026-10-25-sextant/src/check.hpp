// Independent validators. They re-derive every property from the raw triangle list using only the
// exact predicates — none of the insertion/flip code is reused — so a bug there cannot hide here.
#pragma once
#include <string>
#include <vector>

#include "triangulation.hpp"
#include "voronoi.hpp"

namespace sextant {

struct CheckReport {
    std::vector<std::string> problems;
    int vertices = 0, triangles = 0, edges = 0, hull_edges = 0;
    double min_angle = 180, max_angle = 0, total_area = 0;
    bool ok() const { return problems.empty(); }
    std::string summary() const;
};

struct CheckOptions {
    bool global_empty_circle = false;  // O(n * triangles) brute-force empty-circumcircle test (Delaunay only)
    bool inside_only = false;          // examine only triangles flagged inside (carved CDT)
};

// Structural + geometric certificate of a triangulation:
//  * every triangle strictly counter-clockwise (exact), every vertex used
//  * adjacency is symmetric and each shared edge is traversed in opposite directions
//  * Euler's formula V - E + F = 1 holds, boundary is one closed loop
//  * every unconstrained interior edge is locally Delaunay (=> Delaunay / constrained Delaunay)
//  * every segment of the PSLG is a mesh edge
//  * (optional) no vertex lies strictly inside any triangle's circumcircle
CheckReport check_triangulation(const Triangulation& dt, const CheckOptions& opt = {});

// Cells tile the box: areas sum to the box area, every cell is convex and contains its site (when
// the site is inside the box), and sampled points are nearest to the site of their cell.
CheckReport check_voronoi(const Triangulation& dt, const std::vector<VoronoiCell>& cells, const Box& box, int samples,
                          unsigned seed);

}  // namespace sextant
