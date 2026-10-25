// Hostile fuzzing: tiny integer lattices (massively cocircular / collinear / duplicated), random
// segment soups (crossings, overlaps, T-junctions, zero-length, repeated), brute-force oracles.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <map>
#include <set>

#include "check.hpp"
#include "io.hpp"
#include "triangulation.hpp"
#include "voronoi.hpp"

using namespace sextant;

static int failures = 0;
#define EXPECT(cond, ...) do { if (!(cond)) { ++failures; std::printf("FAIL: "); std::printf(__VA_ARGS__); std::printf("\n"); if (failures > 10) std::exit(1); } } while (0)

static void dump(const char* tag, const std::vector<Pt>& p, const std::vector<std::pair<int, int>>& s) {
    std::printf("--- %s\n", tag);
    for (auto& q : p) std::printf("%.17g %.17g\n", q.x, q.y);
    for (auto& g : s) std::printf("s %d %d\n", g.first, g.second);
}

static void fuzz_points(int iters, unsigned seed) {
    std::mt19937 rng(seed);
    for (int it = 0; it < iters; ++it) {
        int g = 1 + rng() % 6, n = 1 + rng() % 45;
        bool jitter = rng() % 4 == 0;
        std::vector<Pt> pts;
        for (int i = 0; i < n; ++i) {
            double x = (double)(rng() % (g + 1)), y = (double)(rng() % (g + 1));
            if (jitter && rng() % 3 == 0) { x += std::ldexp(1.0, -30) * (rng() % 5); y += std::ldexp(1.0, -35) * (rng() % 5); }
            pts.push_back({x, y});
        }
        try {
            Triangulation dt = Triangulation::delaunay(pts);
            CheckOptions co;
            co.global_empty_circle = true;
            CheckReport r = check_triangulation(dt, co);
            if (!r.ok()) { EXPECT(false, "points iter %d: %s", it, r.summary().c_str()); dump("points", pts, {}); }
            // nearest vs brute force
            for (int q = 0; q < 5; ++q) {
                Pt qp{(rng() % 1000) / 1000.0 * (g + 2) - 0.5, (rng() % 1000) / 1000.0 * (g + 2) - 0.5};
                int v = dt.nearest(qp);
                double best = 1e300;
                for (auto& p : pts) best = std::min(best, (p.x - qp.x) * (p.x - qp.x) + (p.y - qp.y) * (p.y - qp.y));
                double got = (pts[v].x - qp.x) * (pts[v].x - qp.x) + (pts[v].y - qp.y) * (pts[v].y - qp.y);
                EXPECT(got <= best * (1 + 1e-12) + 1e-300, "nearest iter %d: got %g best %g", it, got, best);
            }
            // hull agreement
            if (!dt.degenerate()) {
                auto h = convex_hull(pts);
                std::vector<int> b = dt.boundary(), strict;
                for (size_t i = 0; i < b.size(); ++i) {
                    int p = b[(i + b.size() - 1) % b.size()], q = b[i], rr = b[(i + 1) % b.size()];
                    if (orient2d(pts[p], pts[q], pts[rr]) != 0) strict.push_back(q);
                }
                std::set<int> A, B;
                for (int v : h) A.insert(dt.dup_of()[v]);
                for (int v : strict) B.insert(v);
                EXPECT(A == B, "hull mismatch iter %d", it);
            }
            Box box = bounding_box(pts, 0.25);
            CheckReport v = check_voronoi(dt, voronoi_cells(dt, box), box, 200, it);
            if (!v.ok()) { EXPECT(false, "voronoi iter %d: %s", it, v.summary().c_str()); dump("voronoi", pts, {}); }
        } catch (const std::exception& e) {
            EXPECT(false, "points iter %d threw: %s", it, e.what());
            dump("points", pts, {});
        }
    }
}

static void fuzz_cdt(int iters, unsigned seed) {
    std::mt19937 rng(seed);
    for (int it = 0; it < iters; ++it) {
        int g = 2 + rng() % 7, n = 3 + rng() % 14, m = 1 + rng() % 12;
        std::vector<Pt> pts;
        for (int i = 0; i < n; ++i) pts.push_back({(double)(rng() % (g + 1)), (double)(rng() % (g + 1))});
        std::vector<std::pair<int, int>> segs;
        for (int i = 0; i < m; ++i) segs.push_back({(int)(rng() % n), (int)(rng() % n)});
        bool carve = rng() % 2;
        try {
            Triangulation dt = Triangulation::constrained(pts, segs, carve);
            CheckOptions co;
            co.inside_only = carve;
            CheckReport r = check_triangulation(dt, co);
            if (!r.ok()) { EXPECT(false, "cdt iter %d: %s", it, r.summary().c_str()); dump("cdt", pts, segs); continue; }
            if (dt.degenerate()) continue;
            // every input segment must be representable as a chain of constrained mesh edges
            std::map<int, std::vector<int>> adj;
            for (auto& s : dt.segments()) { adj[s.a].push_back(s.b); adj[s.b].push_back(s.a); }
            for (auto& s : segs) {
                int a = dt.dup_of()[s.first], b = dt.dup_of()[s.second];
                if (a == b) continue;
                std::set<int> seen{a};
                std::vector<int> st{a};
                while (!st.empty()) { int u = st.back(); st.pop_back(); for (int w : adj[u]) if (seen.insert(w).second) st.push_back(w); }
                EXPECT(seen.count(b), "cdt iter %d: segment %d-%d not realised", it, s.first, s.second);
            }
        } catch (const GeometryError& e) {
            // crossing segments with rounded intersections may be legitimately rejected; but on small
            // integer lattices a failure is worth a look
            EXPECT(false, "cdt iter %d threw: %s", it, e.what());
            dump("cdt", pts, segs);
        } catch (const std::exception& e) {
            EXPECT(false, "cdt iter %d std exception: %s", it, e.what());
            dump("cdt", pts, segs);
        }
    }
}

static void fuzz_cdt_float(int iters, unsigned seed) {
    std::mt19937_64 rng(seed);
    std::uniform_real_distribution<double> U(0, 1);
    int rejected = 0;
    for (int it = 0; it < iters; ++it) {
        int n = 4 + rng() % 40, m = 2 + rng() % 40;
        std::vector<Pt> pts;
        for (int i = 0; i < n; ++i) pts.push_back({U(rng), U(rng)});
        std::vector<std::pair<int, int>> segs;
        for (int i = 0; i < m; ++i) segs.push_back({(int)(rng() % n), (int)(rng() % n)});
        bool carve = rng() % 2;
        try {
            Triangulation dt = Triangulation::constrained(pts, segs, carve);
            CheckOptions co;
            co.inside_only = carve;
            CheckReport r = check_triangulation(dt, co);
            if (!r.ok()) { EXPECT(false, "cdt-float iter %d: %s", it, r.summary().c_str()); dump("cdt-float", pts, segs); }
        } catch (const GeometryError& e) {
            ++rejected;
            if (rejected <= 3) std::printf("note: cdt-float iter %d rejected: %s\n", it, e.what());
        }
    }
    EXPECT(rejected * 100 <= iters, "cdt-float: %d of %d inputs rejected", rejected, iters);
}

// Random star-shaped polygons (optionally with a hole): refine, then re-verify structure, conformity
// (no segment encroached by a domain vertex) and that Lloyd energy never increases.
static void fuzz_refine(int iters, unsigned seed) {
    std::mt19937_64 rng(seed);
    std::uniform_real_distribution<double> U(0, 1);
    int capped = 0, missed = 0;
    for (int it = 0; it < iters; ++it) {
        int n = 5 + rng() % 14;
        std::vector<Pt> pts;
        std::vector<std::pair<int, int>> segs;
        for (int i = 0; i < n; ++i) {
            double a = 2 * M_PI * (i + 0.6 * U(rng)) / n, r = 0.5 + 0.5 * U(rng);
            pts.push_back({r * std::cos(a), r * std::sin(a)});
            segs.push_back({i, (i + 1) % n});
        }
        if (rng() % 2) {  // hole
            int m = 3 + rng() % 5, base = (int)pts.size();
            for (int i = 0; i < m; ++i) {
                double a = 2 * M_PI * i / m;
                pts.push_back({0.2 * std::cos(a), 0.2 * std::sin(a)});
                segs.push_back({base + i, base + (i + 1) % m});
            }
        }
        RefineOptions ro;
        ro.min_angle = 15 + (double)(rng() % 120) / 10.0;
        ro.max_area = (rng() % 2) ? 0.0 : 0.002 + 0.01 * U(rng);
        ro.max_steiner = 20000;
        try {
            Triangulation dt = Triangulation::constrained(pts, segs, true);
            RefineReport rep = dt.refine(ro);
            CheckOptions co;
            co.inside_only = true;
            CheckReport r = check_triangulation(dt, co);
            if (!r.ok()) { EXPECT(false, "refine iter %d: %s", it, r.summary().c_str()); dump("refine", pts, segs); continue; }
            if (rep.hit_cap) { ++capped; continue; }
            for (const Segment& sg : dt.segments())
                for (size_t v = 0; v < dt.points().size(); ++v) {
                    if (dt.dup_of()[v] != (int)v || (int)v == sg.a || (int)v == sg.b) continue;
                    const Pt &pa = dt.points()[sg.a], &pb = dt.points()[sg.b], &pv = dt.points()[v];
                    double dot = (pa.x - pv.x) * (pb.x - pv.x) + (pa.y - pv.y) * (pb.y - pv.y);
                    if (dot < -1e-12) { EXPECT(false, "refine iter %d: segment %d-%d encroached by vertex %zu", it, sg.a, sg.b, v); break; }
                }
            if (rep.min_angle + 1e-9 < ro.min_angle) ++missed;  // allowed for sharp input angles, but counted
            if (ro.max_area > 0)
                for (auto& t : dt.triangles(true))
                    EXPECT(std::fabs(triangle_area(dt.points()[t[0]], dt.points()[t[1]], dt.points()[t[2]])) <= ro.max_area * (1 + 1e-9),
                           "refine iter %d: triangle exceeds area bound", it);
        } catch (const std::exception& e) {
            EXPECT(false, "refine iter %d threw: %s", it, e.what());
            dump("refine", pts, segs);
        }
    }
    std::printf("refine: %d runs, %d hit the point cap, %d missed the angle target (sharp input angles)\n", iters, capped, missed);
}

static void fuzz_lloyd(int iters, unsigned seed) {
    std::mt19937_64 rng(seed);
    std::uniform_real_distribution<double> U(0, 1);
    for (int it = 0; it < iters; ++it) {
        int n = 3 + rng() % 60;
        std::vector<Pt> pts;
        for (int i = 0; i < n; ++i) pts.push_back({U(rng), U(rng)});
        Box box{0, 0, 1, 1};
        LloydReport rep;
        lloyd(pts, box, 8, &rep);
        for (size_t k = 1; k < rep.energy.size(); ++k)
            EXPECT(rep.energy[k] <= rep.energy[k - 1] * (1 + 1e-9), "lloyd iter %d: energy rose %.12g -> %.12g at step %zu", it, rep.energy[k - 1], rep.energy[k], k);
    }
}

int main(int argc, char** argv) {
    int iters = argc > 1 ? std::atoi(argv[1]) : 3000;
    unsigned seed = argc > 2 ? (unsigned)std::atoi(argv[2]) : 1;
    fuzz_points(iters, seed);
    fuzz_cdt(iters, seed + 100);
    fuzz_cdt_float(iters, seed + 200);
    fuzz_refine(std::max(50, iters / 10), seed + 300);
    fuzz_lloyd(std::max(20, iters / 40), seed + 400);
    std::printf("fuzz: %d iterations x 3 modes, %d failure(s)\n", iters, failures);
    return failures ? 1 : 0;
}
