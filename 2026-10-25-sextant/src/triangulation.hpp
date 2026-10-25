// Triangle mesh with ghost triangles. Vertex id -1 is the point at infinity: every hull edge a->b
// (interior on its left) has a "ghost" triangle (b, a, -1) on its right, so the mesh is a closed
// surface and every triangle has three neighbours. That makes insertion, flipping and cavity growth
// uniform — there is no special-casing of the convex hull.
#pragma once
#include <array>
#include <cstdint>
#include <random>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

#include "predicates.hpp"

namespace sextant {

struct GeometryError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct Tri {
    int v[3] = {-1, -1, -1};  // counter-clockwise; at most one may be -1 (ghost)
    int n[3] = {-1, -1, -1};  // n[i] = neighbour across the edge opposite v[i]
    uint8_t con = 0;          // bit i set => edge opposite v[i] is a constrained segment
    bool dead = false;
    bool inside = false;      // inside the carved domain (set by carve())
    bool ghost() const { return v[0] < 0 || v[1] < 0 || v[2] < 0; }
};

struct Segment {
    int a, b;
    bool alive = true;
};

struct RefineOptions {
    double min_angle = 20.0;   // degrees
    double max_area = 0.0;     // 0 = no area bound
    int max_steiner = 200000;  // safety cap on inserted points
};
struct RefineReport {
    int steiner_points = 0, segment_splits = 0;
    double min_angle = 0, max_angle = 0;
    bool hit_cap = false;
};

class Triangulation {
public:
    // ---- construction -------------------------------------------------------------------
    // Delaunay triangulation of `pts`. Duplicate points are merged (dup_of[i] = canonical index).
    static Triangulation delaunay(const std::vector<Pt>& pts);

    // Constrained Delaunay triangulation of a PSLG. Crossing segments are split at their
    // intersection (a new vertex is appended); `carve` removes everything outside the (even-odd)
    // closed regions bounded by the segments.
    static Triangulation constrained(const std::vector<Pt>& pts,
                                     const std::vector<std::pair<int, int>>& segs, bool carve);

    // ---- queries ------------------------------------------------------------------------
    const std::vector<Pt>& points() const { return pts_; }
    const std::vector<int>& dup_of() const { return dup_of_; }
    const std::vector<Segment>& segments() const { return segs_; }
    bool degenerate() const { return !has_triangles_; }  // all points collinear / fewer than 3
    // Live non-ghost triangles; if `inside_only`, only those inside the carved domain.
    std::vector<std::array<int, 3>> triangles(bool inside_only = false) const;
    // Convex hull of the point set as seen by the triangulation (includes collinear boundary points).
    std::vector<int> boundary() const;
    // Vertices adjacent to v in the triangulation (ccw order).
    std::vector<int> neighbors(int v) const;
    // Index of the nearest input vertex to q (greedy descent on the Delaunay graph).
    int nearest(const Pt& q) const;
    // For degenerate (collinear) input: vertex indices sorted along the line.
    const std::vector<int>& chain() const { return chain_; }
    bool carved() const { return carved_; }
    const std::vector<Tri>& raw() const { return tris_; }

    // ---- quality mesh generation (refine.cpp) -------------------------------------------
    RefineReport refine(const RefineOptions& opt);

    // ---- statistics ---------------------------------------------------------------------
    int num_flips() const { return flips_; }

private:
    friend struct TriangulationAccess;
    std::vector<Pt> pts_;
    std::vector<int> dup_of_;
    std::vector<Tri> tris_;
    std::vector<int> free_;
    std::vector<int> vtri_;  // some live triangle incident to each vertex
    std::vector<Segment> segs_;
    std::vector<int> chain_;
    std::vector<uint32_t> stamp_, rej_;
    uint32_t cur_stamp_ = 0;
    int hint_ = 0;
    int flips_ = 0;
    bool has_triangles_ = false;
    bool carved_ = false;
    std::mt19937 rng_{12345};

    // mesh primitives
    int new_tri();
    void kill(int t);
    static int idx_of(const Tri& t, int v);
    void set_tri(int t, int a, int b, int c);
    void replace_neighbor(int x, int oldn, int newn);
    bool in_circle_region(int t, const Pt& p) const;  // Bowyer-Watson cavity predicate
    int locate(const Pt& p, int start, bool& duplicate, int& dup_vertex);
    int find_ring_ghost(int g, const Pt& p);
    int insert_point(int vid, bool respect_constraints, std::vector<int>* created = nullptr);
    void split_edge(int t, int i, int vid, std::vector<int>* created);
    void flip(int t, int i);
    void legalize(std::vector<std::pair<int, int>>& stack, std::vector<int>* touched = nullptr);
    bool locally_delaunay(int t, int i) const;
    bool find_edge(int p, int q, int& t, int& i) const;  // tri containing directed edge p->q
    void mark_constraint(int p, int q);
    bool is_constrained(int p, int q) const;
    void build(const std::vector<Pt>& pts);
    void carve_domain();
    bool encroaches(const Pt& p, const Segment& s) const;
    int add_vertex(const Pt& p);
    void link_all(const std::vector<int>& tris);
};

// Circumcentre and related measures in double precision (used by Voronoi and refinement).
Pt circumcenter(const Pt& a, const Pt& b, const Pt& c);
double triangle_area(const Pt& a, const Pt& b, const Pt& c);  // signed
double min_angle_deg(const Pt& a, const Pt& b, const Pt& c);
double max_angle_deg(const Pt& a, const Pt& b, const Pt& c);

}  // namespace sextant
