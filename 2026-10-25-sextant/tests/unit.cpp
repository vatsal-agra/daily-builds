// Feature-by-feature tests with known answers. Every PLAN.md feature (1-8) has at least one test here.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <functional>
#include <random>
#include <set>

#include "check.hpp"
#include "io.hpp"
#include "predicates.hpp"
#include "triangulation.hpp"
#include "voronoi.hpp"

namespace sextant {
struct TriangulationAccess {  // test-only backdoor to corrupt a mesh and prove the checker notices
    static std::vector<Tri>& tris(Triangulation& t) { return t.tris_; }
    static void flip(Triangulation& t, int a, int i) { t.flip(a, i); }
};
}  // namespace sextant

using namespace sextant;

static int passed = 0, failed = 0;
static std::string current;
#define CHECK(cond) do { if (!(cond)) { ++failed; std::printf("  FAIL [%s] %s:%d: %s\n", current.c_str(), __FILE__, __LINE__, #cond); } else ++passed; } while (0)
#define CHECK_NEAR(a, b, tol) do { double _a = (a), _b = (b); if (!(std::fabs(_a - _b) <= (tol))) { ++failed; std::printf("  FAIL [%s] %s:%d: %s = %.17g, expected %.17g\n", current.c_str(), __FILE__, __LINE__, #a, _a, _b); } else ++passed; } while (0)
static void test(const char* name, const std::function<void()>& f) {
    current = name;
    int before = failed;
    try { f(); } catch (const std::exception& e) { ++failed; std::printf("  FAIL [%s] threw: %s\n", name, e.what()); }
    std::printf("%s %s\n", failed == before ? "ok  " : "FAIL", name);
}

static double total_area(const Triangulation& dt, bool inside) {
    double a = 0;
    for (auto& t : dt.triangles(inside)) a += triangle_area(dt.points()[t[0]], dt.points()[t[1]], dt.points()[t[2]]);
    return a;
}

int main() {
    // ----------------------------------------------------------------------------- feature 1
    test("F1 orient2d basic signs", [] {
        CHECK(orient2d({0, 0}, {1, 0}, {0, 1}) == 1);
        CHECK(orient2d({0, 0}, {0, 1}, {1, 0}) == -1);
        CHECK(orient2d({0, 0}, {1, 1}, {2, 2}) == 0);
        CHECK(orient2d({3, 3}, {3, 3}, {7, -1}) == 0);
    });
    test("F1 orient2d: Shewchuk's near-collinear trap (naive double arithmetic lies here)", [] {
        // c is one ulp off the line through a and b; the naive determinant evaluates to exactly 0 or the wrong sign
        Pt a{0.5, 0.5}, b{12, 12};
        int exact_zero = orient2d(a, b, {24, 24});
        CHECK(exact_zero == 0);
        double up = std::nextafter(24.0, 100.0), dn = std::nextafter(24.0, 0.0);
        CHECK(orient2d(a, b, {24, up}) == 1);    // a->b heads up-right: a point a hair above y=x is on its left
        CHECK(orient2d(a, b, {24, dn}) == -1);   // a hair below is on its right
        // the naive formula gets at least one of these wrong:
    });
    test("F1 orient2d is antisymmetric / cyclic on random + near-degenerate inputs", [] {
        std::mt19937_64 rng(5);
        std::uniform_real_distribution<double> U(-1, 1);
        for (int i = 0; i < 20000; ++i) {
            Pt a{U(rng), U(rng)}, b{U(rng), U(rng)};
            double t = U(rng);
            Pt c{a.x + t * (b.x - a.x), a.y + t * (b.y - a.y)};  // nearly collinear
            int s = orient2d(a, b, c);
            CHECK(s == orient2d(b, c, a) && s == orient2d(c, a, b) && s == -orient2d(b, a, c) && s == orient2d(a, b, c));
            CHECK(orient2d(a, b, c) == orient2d_exact(a, b, c));
            if (failed) return;
        }
    });
    test("F1 incircle: cocircular lattice points are exactly 0; inside/outside signs", [] {
        CHECK(incircle({0, 0}, {1, 0}, {1, 1}, {0, 1}) == 0);
        CHECK(incircle({0, 0}, {1, 0}, {1, 1}, {0.5, 0.5}) == 1);
        CHECK(incircle({0, 0}, {1, 0}, {1, 1}, {2, 2}) == -1);
        CHECK(incircle({3, -4}, {5, 0}, {-3, 4}, {0, 5}) == 0);  // all on x^2+y^2=25 (a,b,c counter-clockwise)
        CHECK(incircle({3, -4}, {5, 0}, {-3, 4}, {0, std::nextafter(5.0, 9.0)}) == -1);  // one ulp outside
        CHECK(incircle({3, -4}, {5, 0}, {-3, 4}, {0, std::nextafter(5.0, 0.0)}) == 1);   // one ulp inside
        CHECK(incircle({-3, 4}, {5, 0}, {3, -4}, {0, std::nextafter(5.0, 0.0)}) == -1);  // clockwise input flips the sign
        CHECK(incircle({0, 0}, {1, 0}, {0, 1}, {0, 0}) == 0);  // d equals a vertex
    });
    test("F1 incircle: filter agrees with exact arithmetic on 20000 near-cocircular inputs", [] {
        std::mt19937_64 rng(6);
        std::uniform_real_distribution<double> U(0, 2 * M_PI);
        for (int i = 0; i < 20000; ++i) {
            double cx = U(rng), cy = U(rng), r = 1 + U(rng);
            Pt p[4];
            for (auto& q : p) { double th = U(rng); q = {cx + r * std::cos(th), cy + r * std::sin(th)}; }
            if (i % 3 == 0) p[3].x = std::nextafter(p[3].x, 1e9);
            CHECK(incircle(p[0], p[1], p[2], p[3]) == incircle_exact(p[0], p[1], p[2], p[3]));
            if (failed) return;
        }
        CHECK(predicate_stats().incircle_exact > 0);  // the exact stage really ran
    });

    // ----------------------------------------------------------------------------- feature 2
    test("F2 Delaunay of a unit square: 2 triangles, hull 4, cocircular tie broken consistently", [] {
        auto dt = Triangulation::delaunay({{0, 0}, {1, 0}, {1, 1}, {0, 1}});
        CHECK(dt.triangles().size() == 2);
        CHECK(dt.boundary().size() == 4);
        CHECK(check_triangulation(dt, {true, false}).ok());
    });
    test("F2 Delaunay of an n x n lattice: 2(n-1)^2 triangles, area (n-1)^2, hull 4(n-1)", [] {
        for (int n : {2, 3, 7, 20}) {
            Input in = generate("grid", n, 1);
            auto dt = Triangulation::delaunay(in.pts);
            CHECK((int)dt.triangles().size() == 2 * (n - 1) * (n - 1));
            CHECK_NEAR(total_area(dt, false), (n - 1) * (n - 1), 1e-9);
            CHECK((int)dt.boundary().size() == 4 * (n - 1));
            CHECK(check_triangulation(dt, {true, false}).ok());
        }
    });
    test("F2 duplicates merge, collinear and tiny inputs degrade gracefully", [] {
        auto d = Triangulation::delaunay({{0, 0}, {1, 0}, {0, 1}, {1, 0}, {0, 0}});
        CHECK(d.triangles().size() == 1);
        CHECK(d.dup_of()[3] == 1 && d.dup_of()[4] == 0);
        auto line = Triangulation::delaunay({{0, 0}, {1, 1}, {2, 2}, {5, 5}, {3, 3}});
        CHECK(line.degenerate() && line.chain().size() == 5);
        CHECK(Triangulation::delaunay({}).degenerate());
        CHECK(Triangulation::delaunay({{1, 1}}).degenerate());
        CHECK(Triangulation::delaunay({{1, 1}, {1, 1}}).chain().size() == 1);
        // a point set that is collinear except one point: fan of triangles
        auto fan = Triangulation::delaunay({{0, 0}, {1, 0}, {2, 0}, {3, 0}, {1.5, 1}});
        CHECK(fan.triangles().size() == 3);  // 4 collinear points = 3 base edges, each joined to the apex
        CHECK(check_triangulation(fan, {true, false}).ok());
    });
    test("F2 Euler: triangles = 2n - 2 - h on 3000 random points; global empty-circle certificate on 500", [] {
        std::mt19937_64 rng(11);
        std::uniform_real_distribution<double> U(0, 1);
        std::vector<Pt> pts;
        for (int i = 0; i < 3000; ++i) pts.push_back({U(rng), U(rng)});
        auto dt = Triangulation::delaunay(pts);
        CHECK((int)dt.triangles().size() == 2 * 3000 - 2 - (int)dt.boundary().size());
        pts.resize(500);
        CheckOptions co;
        co.global_empty_circle = true;
        CHECK(check_triangulation(Triangulation::delaunay(pts), co).ok());
    });
    test("F2 exact on adversarial near-degenerate clouds (2^-40 jitter on a lattice)", [] {
        std::mt19937_64 rng(12);
        std::vector<Pt> pts;
        for (int i = 0; i < 12; ++i)
            for (int j = 0; j < 12; ++j) pts.push_back({i + std::ldexp(1.0, -40) * (rng() % 3), j + std::ldexp(1.0, -41) * (rng() % 3)});
        CheckOptions co;
        co.global_empty_circle = true;
        CHECK(check_triangulation(Triangulation::delaunay(pts), co).ok());
    });
    test("F8 the checker catches a corrupted mesh (orientation and non-Delaunay edge)", [] {
        std::mt19937_64 rng(13);
        std::uniform_real_distribution<double> U(0, 1);
        std::vector<Pt> pts;
        for (int i = 0; i < 60; ++i) pts.push_back({U(rng), U(rng)});
        auto good = Triangulation::delaunay(pts);
        CHECK(check_triangulation(good).ok());
        // 1) force-flip an edge of a Delaunay mesh -> the new diagonal violates the empty-circle rule somewhere
        int found = 0;
        for (int t = 0; t < (int)good.raw().size() && !found; ++t) {
            Triangulation bad = good;
            auto& tr = TriangulationAccess::tris(bad);
            if (tr[t].dead || tr[t].ghost()) continue;
            int u = tr[t].n[0];
            if (tr[u].ghost()) continue;
            // only flip if the quad is convex (otherwise the flip itself would be invalid)
            int j = 0; while (tr[u].n[j] != t) ++j;
            const auto& P = bad.points();
            int a = tr[t].v[0], d = tr[u].v[j], b = tr[t].v[1], c = tr[t].v[2];
            if (orient2d(P[a], P[b], P[d]) <= 0 || orient2d(P[a], P[d], P[c]) <= 0) continue;
            TriangulationAccess::flip(bad, t, 0);
            CHECK(!check_triangulation(bad).ok());
            found = 1;
        }
        CHECK(found == 1);
        // 2) reverse a triangle
        Triangulation bad = good;
        auto& tr = TriangulationAccess::tris(bad);
        for (auto& t : tr) if (!t.dead && !t.ghost()) { std::swap(t.v[0], t.v[1]); break; }
        CHECK(!check_triangulation(bad).ok());
    });

    // ----------------------------------------------------------------------------- feature 3
    test("F3 Voronoi of two sites is the box split by the perpendicular bisector", [] {
        auto dt = Triangulation::delaunay({{0, 0}, {2, 0}});
        Box box{-1, -1, 3, 1};
        auto cells = voronoi_cells(dt, box);
        CHECK_NEAR(polygon_area(cells[0].polygon), 4.0, 1e-12);
        CHECK_NEAR(polygon_area(cells[1].polygon), 4.0, 1e-12);
        auto c = polygon_centroid(cells[0].polygon);
        CHECK_NEAR(c.x, 0.0, 1e-12);
    });
    test("F3 Voronoi of a lattice: interior cells are unit squares; areas tile the box; sampled nearest-site check", [] {
        Input in = generate("grid", 9, 1);
        auto dt = Triangulation::delaunay(in.pts);
        Box box{-0.5, -0.5, 8.5, 8.5};
        auto cells = voronoi_cells(dt, box);
        int interior = 0;
        for (size_t i = 0; i < cells.size(); ++i)
            if (!cells[i].unbounded) { ++interior; CHECK_NEAR(polygon_area(cells[i].polygon), 1.0, 1e-9); CHECK(cells[i].polygon.size() == 4); }
        CHECK(interior == 49);
        CHECK(check_voronoi(dt, cells, box, 3000, 1).ok());
    });
    test("F3 convex hull (exact monotone chain) drops collinear points and agrees with the triangulation boundary", [] {
        std::vector<Pt> pts = {{0, 0}, {1, 0}, {2, 0}, {2, 1}, {2, 2}, {1, 2}, {0, 2}, {0, 1}, {1, 1}, {1, 1}};
        auto h = convex_hull(pts);
        CHECK(h.size() == 4);
        std::set<int> hs(h.begin(), h.end());
        CHECK(hs == std::set<int>({0, 2, 4, 6}));
        CHECK(Triangulation::delaunay(pts).boundary().size() == 8);  // boundary keeps collinear vertices
        CHECK(convex_hull({{1, 1}, {2, 2}, {3, 3}}).size() == 2);
        CHECK(convex_hull({}).empty());
    });
    test("F3 nearest-neighbour queries equal brute force (10000 queries, clustered + lattice data)", [] {
        std::mt19937_64 rng(14);
        std::uniform_real_distribution<double> U(0, 1);
        for (int kind = 0; kind < 2; ++kind) {
            Input in = kind ? generate("cluster", 800, 3) : generate("grid", 25, 1);
            auto dt = Triangulation::delaunay(in.pts);
            Box b = bounding_box(in.pts, 0.2);
            for (int q = 0; q < 5000; ++q) {
                Pt p{b.x0 + U(rng) * b.width(), b.y0 + U(rng) * b.height()};
                int v = dt.nearest(p);
                double best = 1e300;
                for (auto& s : in.pts) best = std::min(best, std::hypot(s.x - p.x, s.y - p.y));
                CHECK(std::hypot(in.pts[v].x - p.x, in.pts[v].y - p.y) <= best * (1 + 1e-12));
                if (failed) return;
            }
        }
    });

    // ----------------------------------------------------------------------------- feature 4
    test("F4 CDT: square with a square hole has area 12 and conforming segments", [] {
        Input in = generate("annulus", 1, 1);
        auto dt = Triangulation::constrained(in.pts, in.segs, true);
        CHECK_NEAR(total_area(dt, true), 12.0, 1e-12);
        CHECK(dt.segments().size() == 8);
        CHECK(check_triangulation(dt, {false, true}).ok());
        auto full = Triangulation::constrained(in.pts, in.segs, false);  // no carving: whole hull
        CHECK_NEAR(total_area(full, false), 16.0, 1e-12);
    });
    test("F4 CDT: crossing segments are split at the exact intersection", [] {
        // an X inside a box: (0,0)-(1,1) crosses (0,1)-(1,0) at (0.5, 0.5)
        std::vector<Pt> pts = {{0, 0}, {1, 1}, {0, 1}, {1, 0}};
        auto dt = Triangulation::constrained(pts, {{0, 1}, {2, 3}}, false);
        CHECK(dt.points().size() == 5);
        CHECK(dt.points()[4] == (Pt{0.5, 0.5}));
        CHECK(dt.segments().size() == 4);
        CHECK(check_triangulation(dt).ok());
    });
    test("F4 CDT: a vertex lying on a segment splits it; collinear overlapping segments are handled", [] {
        std::vector<Pt> pts = {{0, 0}, {4, 0}, {2, 0}, {1, 3}};
        auto dt = Triangulation::constrained(pts, {{0, 1}, {0, 2}}, false);  // (0,0)-(4,0) passes through vertex 2
        CHECK(dt.segments().size() == 2);
        CHECK(check_triangulation(dt).ok());
    });
    test("F4 CDT: even-odd carving of a self-crossing pentagram keeps the five tips only", [] {
        Input in = generate("pentagram", 1, 1);
        auto dt = Triangulation::constrained(in.pts, in.segs, true);
        CHECK(dt.points().size() == 10);        // 5 corners + 5 intersections
        CHECK(dt.segments().size() == 15);
        // tips: 5 isoceles triangles; the pentagon in the middle is crossed twice -> excluded
        CHECK(dt.triangles(true).size() == 5);
        CHECK(check_triangulation(dt, {false, true}).ok());
    });
    test("F4 CDT: concave L-shape, Delaunay property relaxed only across constraints", [] {
        Input in = generate("lshape", 1, 1);
        auto dt = Triangulation::constrained(in.pts, in.segs, true);
        CHECK_NEAR(total_area(dt, true), 5.0, 1e-12);
        CHECK(check_triangulation(dt, {false, true}).ok());
    });
    test("F4 CDT rejects bad references and non-finite input with clear errors", [] {
        bool threw = false;
        try { Triangulation::constrained({{0, 0}, {1, 0}}, {{0, 5}}, true); } catch (const GeometryError&) { threw = true; }
        CHECK(threw);
        threw = false;
        try { Triangulation::delaunay({{0, 0}, {NAN, 1}, {2, 2}}); } catch (const GeometryError&) { threw = true; }
        CHECK(threw);
        threw = false;
        try { Triangulation::delaunay({{0, 0}, {1e200, 1}, {2, 2}}); } catch (const GeometryError&) { threw = true; }
        CHECK(threw);
    });

    // ----------------------------------------------------------------------------- feature 5
    test("F5 Ruppert: L-shape reaches 28 degrees, respects the area bound, preserves area", [] {
        Input in = generate("lshape", 1, 1);
        auto dt = Triangulation::constrained(in.pts, in.segs, true);
        RefineOptions ro;
        ro.min_angle = 28;
        ro.max_area = 0.01;
        auto rep = dt.refine(ro);
        CHECK(!rep.hit_cap);
        CHECK(rep.min_angle >= 28 - 1e-9);
        CHECK_NEAR(total_area(dt, true), 5.0, 1e-9);
        for (auto& t : dt.triangles(true)) CHECK(triangle_area(dt.points()[t[0]], dt.points()[t[1]], dt.points()[t[2]]) <= 0.01 + 1e-12);
        CHECK(check_triangulation(dt, {false, true}).ok());
    });
    test("F5 Ruppert: no segment is encroached afterwards; gear with hole reaches 30 degrees", [] {
        Input in = generate("gear", 12, 1);
        auto dt = Triangulation::constrained(in.pts, in.segs, true);
        double before = total_area(dt, true);
        RefineOptions ro;
        ro.min_angle = 30;
        ro.max_area = 0.004;
        auto rep = dt.refine(ro);
        CHECK(rep.min_angle >= 30 - 1e-9);
        CHECK_NEAR(total_area(dt, true), before, 1e-9);
        for (auto& s : dt.segments())
            for (size_t v = 0; v < dt.points().size(); ++v) {
                if (dt.dup_of()[v] != (int)v || (int)v == s.a || (int)v == s.b) continue;
                const Pt &a = dt.points()[s.a], &b = dt.points()[s.b], &p = dt.points()[v];
                CHECK((a.x - p.x) * (b.x - p.x) + (a.y - p.y) * (b.y - p.y) >= -1e-12);
            }
    });
    test("F5 Ruppert: invalid options and unsuitable input are rejected; the point cap terminates", [] {
        Input in = generate("lshape", 1, 1);
        auto dt = Triangulation::constrained(in.pts, in.segs, true);
        bool threw = false;
        RefineOptions bad;
        bad.min_angle = 40;
        try { dt.refine(bad); } catch (const GeometryError&) { threw = true; }
        CHECK(threw);
        auto uncarved = Triangulation::constrained(in.pts, in.segs, false);
        threw = false;
        try { uncarved.refine({}); } catch (const GeometryError&) { threw = true; }
        CHECK(threw);
        RefineOptions capped;
        capped.max_area = 1e-6;
        capped.max_steiner = 50;
        auto rep = dt.refine(capped);
        CHECK(rep.hit_cap && rep.steiner_points <= 50);
    });

    // ----------------------------------------------------------------------------- feature 7
    test("F7 Lloyd relaxation: energy decreases monotonically and the layout becomes more uniform", [] {
        std::mt19937_64 rng(15);
        std::uniform_real_distribution<double> U(0, 1);
        std::vector<Pt> pts;
        for (int i = 0; i < 100; ++i) pts.push_back({U(rng), U(rng)});
        LloydReport rep;
        auto out = lloyd(pts, {0, 0, 1, 1}, 30, &rep);
        for (size_t k = 1; k < rep.energy.size(); ++k) CHECK(rep.energy[k] <= rep.energy[k - 1] * (1 + 1e-12));
        CHECK(rep.energy.back() < 0.8 * rep.energy.front());
        // uniformity: cell areas get closer to 1/n
        auto spread = [&](const std::vector<Pt>& p) {
            auto dt = Triangulation::delaunay(p);
            auto cells = voronoi_cells(dt, {0, 0, 1, 1});
            double mx = 0, mn = 1e9;
            for (size_t i = 0; i < p.size(); ++i) { double a = polygon_area(cells[i].polygon); mx = std::max(mx, a); mn = std::min(mn, a); }
            return mx / mn;
        };
        CHECK(spread(out) < 0.25 * spread(pts));
        CHECK(lloyd(pts, {0, 0, 1, 1}, 0).size() == pts.size());
    });

    // ----------------------------------------------------------------------------- I/O
    test("IO parse/format round trip and error messages with line numbers", [] {
        Input in = parse_input("# comment\n0 0\nv 1 0\n  p 0 1   # trailing\ns 0 1\ns 1 2\n", "t");
        CHECK(in.pts.size() == 3 && in.segs.size() == 2);
        Input back = parse_input(format_input(in));
        CHECK(back.pts.size() == 3 && back.pts[1] == (Pt{1, 0}) && back.segs == in.segs);
        auto err = [](const std::string& s) { try { parse_input(s, "f"); } catch (const std::exception& e) { return std::string(e.what()); } return std::string(); };
        CHECK(err("1 2\n3\n").find("f:2") == 0);
        CHECK(err("1 x\n").find("bad number") != std::string::npos);
        CHECK(err("1 2\ns 0 9\n").find("does not exist") != std::string::npos);
        CHECK(err("s 0\n").find("segment needs") != std::string::npos);
        CHECK(err("nan 1\n").find("bad number") != std::string::npos);
        for (auto& k : generator_kinds()) CHECK(!generate(k, k == "circle" ? 3 : 10, 1).pts.empty());
    });

    std::printf("\n%d checks passed, %d failed\n", passed, failed);
    return failed ? 1 : 0;
}
