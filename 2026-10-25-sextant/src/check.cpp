#include "check.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <random>
#include <set>
#include <sstream>

namespace sextant {

std::string CheckReport::summary() const {
    std::ostringstream o;
    o << (ok() ? "OK" : "FAILED") << ": " << vertices << " vertices, " << edges << " edges, " << triangles
      << " triangles, " << hull_edges << " hull edges";
    if (triangles) o << ", angles " << min_angle << ".." << max_angle << " deg";
    for (size_t i = 0; i < problems.size() && i < 8; ++i) o << "\n  - " << problems[i];
    if (problems.size() > 8) o << "\n  - ... " << problems.size() - 8 << " more";
    return o.str();
}

CheckReport check_triangulation(const Triangulation& dt, const CheckOptions& opt) {
    CheckReport r;
    const auto& pts = dt.points();
    const auto& raw = dt.raw();
    auto bad = [&](const std::string& s) { r.problems.push_back(s); };

    if (dt.degenerate()) {
        // chain must be strictly collinear and sorted
        const auto& ch = dt.chain();
        r.vertices = (int)ch.size();
        for (size_t k = 2; k < ch.size(); ++k)
            if (orient2d(pts[ch[0]], pts[ch[1]], pts[ch[k]]) != 0) bad("degenerate chain is not collinear");
        return r;
    }

    std::map<std::pair<int, int>, int> directed;  // directed edge -> count (real triangles only)
    std::set<int> used;
    int F = 0;
    for (size_t t = 0; t < raw.size(); ++t) {
        const Tri& T = raw[t];
        if (T.dead) continue;
        for (int i = 0; i < 3; ++i) {
            if (T.n[i] < 0 || T.n[i] >= (int)raw.size() || raw[T.n[i]].dead) {
                bad("triangle " + std::to_string(t) + " has an invalid neighbour");
                return r;
            }
            // symmetric adjacency, and the twin traverses the shared edge in the opposite direction
            const Tri& U = raw[T.n[i]];
            int a = T.v[(i + 1) % 3], b = T.v[(i + 2) % 3];
            bool found = false;
            for (int j = 0; j < 3; ++j)
                if (U.n[j] == (int)t && U.v[(j + 1) % 3] == b && U.v[(j + 2) % 3] == a) found = true;
            if (!found) bad("adjacency of triangle " + std::to_string(t) + " is not mirrored");
            if ((T.con >> i & 1) != 0) {
                bool mirrored = false;
                for (int j = 0; j < 3; ++j)
                    if (U.n[j] == (int)t && (U.con >> j & 1)) mirrored = true;
                if (!mirrored) bad("constraint flag of triangle " + std::to_string(t) + " is not mirrored");
            }
        }
        if (T.ghost()) continue;
        if (opt.inside_only && !T.inside) continue;
        ++F;
        for (int i = 0; i < 3; ++i) used.insert(T.v[i]);
        if (orient2d(pts[T.v[0]], pts[T.v[1]], pts[T.v[2]]) <= 0)
            bad("triangle " + std::to_string(t) + " is not strictly counter-clockwise");
        for (int i = 0; i < 3; ++i) ++directed[{T.v[i], T.v[(i + 1) % 3]}];
        r.total_area += triangle_area(pts[T.v[0]], pts[T.v[1]], pts[T.v[2]]);
        r.min_angle = std::min(r.min_angle, min_angle_deg(pts[T.v[0]], pts[T.v[1]], pts[T.v[2]]));
        r.max_angle = std::max(r.max_angle, max_angle_deg(pts[T.v[0]], pts[T.v[1]], pts[T.v[2]]));
    }
    r.triangles = F;
    for (auto& [e, c] : directed)
        if (c != 1) bad("directed edge used " + std::to_string(c) + " times");
    int hull = 0;
    std::set<std::pair<int, int>> undirected;
    for (auto& [e, c] : directed) {
        undirected.insert({std::min(e.first, e.second), std::max(e.first, e.second)});
        if (!directed.count({e.second, e.first})) ++hull;
    }
    r.edges = (int)undirected.size();
    r.hull_edges = hull;
    r.vertices = (int)used.size();
    if (!opt.inside_only) {
        for (size_t i = 0; i < pts.size(); ++i)
            if (dt.dup_of()[i] == (int)i && !used.count((int)i)) bad("vertex " + std::to_string(i) + " is not in any triangle");
        // Euler: V - E + F == 1 for a triangulated disc
        if (r.vertices - r.edges + F != 1) bad("Euler characteristic V-E+F != 1");
    }

    // local Delaunay property on every unconstrained interior edge (real triangles only)
    for (size_t t = 0; t < raw.size(); ++t) {
        const Tri& T = raw[t];
        if (T.dead || T.ghost() || (opt.inside_only && !T.inside)) continue;
        for (int i = 0; i < 3; ++i) {
            if (T.con >> i & 1) continue;
            const Tri& U = raw[T.n[i]];
            if (U.ghost() || (opt.inside_only && !U.inside)) continue;
            int j = 0;
            while (U.n[j] != (int)t) ++j;
            if (incircle(pts[T.v[0]], pts[T.v[1]], pts[T.v[2]], pts[U.v[j]]) > 0)
                bad("edge of triangle " + std::to_string(t) + " is not locally Delaunay");
        }
    }
    // every segment is an edge
    for (const Segment& s : dt.segments())
        if (!undirected.count({std::min(s.a, s.b), std::max(s.a, s.b)}) && !opt.inside_only)
            bad("segment " + std::to_string(s.a) + "-" + std::to_string(s.b) + " is not a mesh edge");

    if (opt.global_empty_circle) {
        std::vector<int> verts;
        for (size_t i = 0; i < pts.size(); ++i)
            if (dt.dup_of()[i] == (int)i) verts.push_back((int)i);
        for (size_t t = 0; t < raw.size(); ++t) {
            const Tri& T = raw[t];
            if (T.dead || T.ghost()) continue;
            for (int v : verts) {
                if (v == T.v[0] || v == T.v[1] || v == T.v[2]) continue;
                if (incircle(pts[T.v[0]], pts[T.v[1]], pts[T.v[2]], pts[v]) > 0) {
                    bad("vertex " + std::to_string(v) + " lies inside the circumcircle of triangle " + std::to_string(t));
                    break;
                }
            }
        }
    }
    // area of the mesh equals the area of the convex hull (only meaningful for the uncarved mesh)
    if (!opt.inside_only) {
        auto h = dt.boundary();
        std::vector<Pt> hp;
        for (int v : h) hp.push_back(pts[v]);
        double ha = polygon_area(hp);
        if (std::fabs(ha - r.total_area) > 1e-9 * std::max(1.0, std::fabs(ha))) bad("triangle areas do not sum to the hull area");
    }
    return r;
}

CheckReport check_voronoi(const Triangulation& dt, const std::vector<VoronoiCell>& cells, const Box& box, int samples,
                          unsigned seed) {
    CheckReport r;
    const auto& pts = dt.points();
    auto bad = [&](const std::string& s) { r.problems.push_back(s); };
    double total = 0;
    std::vector<int> sites;
    for (size_t i = 0; i < pts.size(); ++i)
        if (dt.dup_of()[i] == (int)i) sites.push_back((int)i);
    r.vertices = (int)sites.size();
    if (sites.empty()) return r;
    for (int v : sites) {
        const auto& poly = cells[v].polygon;
        // A site with a neighbour closer than ~1e-6 of the box can have a sliver cell thinner than double
        // precision resolves at absolute coordinates; those may legitimately collapse, everything else must not.
        bool crowded = false;
        for (int w : dt.neighbors(v))
            if (std::hypot(pts[w].x - pts[v].x, pts[w].y - pts[v].y) < 1e-6 * std::max(box.width(), box.height())) crowded = true;
        if (poly.size() < 3) {
            if (!crowded) bad("cell of site " + std::to_string(v) + " is empty");
            continue;
        }
        double a = polygon_area(poly);
        if (a <= 0 && !crowded && std::min(box.width(), box.height()) > 1e6 * 2.2e-16 * std::max(std::fabs(pts[v].x), std::fabs(pts[v].y))) bad("cell of site " + std::to_string(v) + " has non-positive area");
        total += a;
        for (size_t i = 0; i < poly.size(); ++i) {
            const Pt& p = poly[i];
            const Pt& q = poly[(i + 1) % poly.size()];
            const Pt& s = poly[(i + 2) % poly.size()];
            double cr = (q.x - p.x) * (s.y - q.y) - (q.y - p.y) * (s.x - q.x);
            if (!crowded && cr < -1e-9 * box.width() * box.height()) { bad("cell of site " + std::to_string(v) + " is not convex"); break; }
        }
    }
    double barea = box.width() * box.height();
    double mag = 0;
    for (int v : sites) mag = std::max(mag, std::max(std::fabs(pts[v].x), std::fabs(pts[v].y)));
    // A box thinner than 1e6 ulps of the coordinates cannot hold meaningful polygon areas in doubles.
    if (std::min(box.width(), box.height()) < 1e6 * 2.2e-16 * mag) return r;
    if (std::fabs(total - barea) > 1e-7 * barea) bad("cell areas sum to " + std::to_string(total) + " but the box is " + std::to_string(barea));
    std::mt19937_64 rng(seed);
    std::uniform_real_distribution<double> ux(box.x0, box.x1), uy(box.y0, box.y1);
    for (int s = 0; s < samples && !sites.empty(); ++s) {
        Pt q{ux(rng), uy(rng)};
        int best = -1;
        double bd = 1e300;
        for (int v : sites) {
            double d = (pts[v].x - q.x) * (pts[v].x - q.x) + (pts[v].y - q.y) * (pts[v].y - q.y);
            if (d < bd) { bd = d; best = v; }
        }
        // q must be inside the cell of `best` (or on its boundary within tolerance)
        const auto& poly = cells[best].polygon;
        bool inside = poly.size() >= 3;
        double tol = 1e-9 * (box.width() + box.height());
        for (size_t i = 0; inside && i < poly.size(); ++i) {
            const Pt& p = poly[i];
            const Pt& w = poly[(i + 1) % poly.size()];
            double len = std::hypot(w.x - p.x, w.y - p.y);
            if (len < 1e-12 * (box.width() + box.height())) continue;
            double cr = ((w.x - p.x) * (q.y - p.y) - (w.y - p.y) * (q.x - p.x)) / std::max(len, 1e-300);
            if (cr < -tol) inside = false;
        }
        if (!inside) { bad("sample point not inside the cell of its nearest site " + std::to_string(best)); break; }
    }
    return r;
}

}  // namespace sextant
