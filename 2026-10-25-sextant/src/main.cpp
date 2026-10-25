#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>

#include "check.hpp"
#include "io.hpp"
#include "predicates.hpp"
#include "render.hpp"
#include "triangulation.hpp"
#include "voronoi.hpp"

using namespace sextant;

namespace {

const char* kUsage = R"(sextant — exact-predicate computational geometry

usage: sextant <command> [args] [options]

  gen <kind> [N] [--seed S]        write a generated point set / PSLG to stdout
                                   kinds: uniform grid circle cluster spiral line degenerate
                                          star gear annulus pentagram comb lshape
  delaunay <file>                  Delaunay triangulation of a point set
  voronoi  <file>                  Voronoi diagram clipped to a box     [--margin F]
  hull     <file>                  exact convex hull (and triangulation boundary cross-check)
  cdt      <file>                  constrained Delaunay triangulation of a PSLG  [--no-carve]
  nearest  <file> X Y              nearest site via greedy descent on the Delaunay graph
  check    <file>                  build, then run the full independent certificate
  predicates                       self-test of the exact predicates on adversarial inputs

common options:
  --svg FILE      write an SVG picture            --stats    print predicate-filter statistics
  --mesh FILE     dump the exact mesh (hex floats) for tests/verify_mesh.py
  --verify        run the independent checker on the result (exit 1 on failure)
  '-' as <file> reads standard input
)";

struct Args {
    std::vector<std::string> pos;
    std::map<std::string, std::string> opt;
    bool flag(const std::string& k) const { return opt.count(k) > 0; }
    std::string get(const std::string& k, const std::string& d = "") const {
        auto it = opt.find(k);
        return it == opt.end() ? d : it->second;
    }
    double num(const std::string& k, double d) const {
        auto it = opt.find(k);
        if (it == opt.end()) return d;
        char* e = nullptr;
        double v = std::strtod(it->second.c_str(), &e);
        if (it->second.empty() || *e) throw std::runtime_error("--" + k + " needs a number, got '" + it->second + "'");
        return v;
    }
};

Args parse_args(int argc, char** argv) {
    static const std::set<std::string> flags = {"stats", "verify", "no-carve", "help"};
    Args a;
    for (int i = 2; i < argc; ++i) {
        std::string s = argv[i];
        if (s.size() > 2 && s[0] == '-' && s[1] == '-') {
            std::string k = s.substr(2);
            if (flags.count(k)) a.opt[k] = "1";
            else {
                if (i + 1 >= argc) throw std::runtime_error("option --" + k + " needs a value");
                a.opt[k] = argv[++i];
            }
        } else {
            a.pos.push_back(s);
        }
    }
    return a;
}

void write_file(const std::string& path, const std::string& content) {
    std::ofstream f(path);
    if (!f) throw std::runtime_error("cannot write '" + path + "'");
    f << content;
}

void print_stats() {
    auto& s = predicate_stats();
    auto pct = [](uint64_t a, uint64_t b) { return a + b ? 100.0 * (double)b / (double)(a + b) : 0.0; };
    std::printf("predicates: orient2d %llu fast / %llu exact (%.2f%% exact), incircle %llu fast / %llu exact (%.2f%% exact)\n",
                (unsigned long long)s.orient_fast, (unsigned long long)s.orient_exact, pct(s.orient_fast, s.orient_exact),
                (unsigned long long)s.incircle_fast, (unsigned long long)s.incircle_exact, pct(s.incircle_fast, s.incircle_exact));
}

int finish_check(const Triangulation& dt, const Args& a, bool inside_only, bool delaunay_global) {
    if (!a.flag("verify")) return 0;
    CheckOptions co;
    co.inside_only = inside_only;
    co.global_empty_circle = delaunay_global && dt.points().size() <= 3000;
    CheckReport r = check_triangulation(dt, co);
    std::printf("verify: %s\n", r.summary().c_str());
    return r.ok() ? 0 : 1;
}

// Exact dump (hex floats) for independent verification by tests/verify_mesh.py.
void write_mesh(const std::string& path, const Triangulation& dt, bool inside_only) {
    std::ostringstream o;
    char b[128];
    for (size_t i = 0; i < dt.points().size(); ++i) {
        std::snprintf(b, sizeof b, "v %zu %a %a\n", i, dt.points()[i].x, dt.points()[i].y);
        o << b;
    }
    for (auto& t : dt.triangles(inside_only)) o << "t " << t[0] << " " << t[1] << " " << t[2] << "\n";
    for (auto& s : dt.segments()) o << "s " << s.a << " " << s.b << "\n";
    write_file(path, o.str());
}

Scene scene_with_hull(const Triangulation& dt, bool inside_only, const std::string& title) {
    Scene s = scene_from(dt, inside_only, title);
    s.hull = dt.boundary();
    return s;
}

int cmd_delaunay(const Args& a) {
    if (a.pos.size() != 1) throw std::runtime_error("delaunay needs exactly one input file");
    Input in = read_input_file(a.pos[0]);
    auto t0 = std::chrono::steady_clock::now();
    Triangulation dt = Triangulation::delaunay(in.pts);
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    if (dt.degenerate()) {
        std::printf("%zu points, %zu distinct: %s — no triangles\n", in.pts.size(), dt.chain().size(),
                    dt.chain().size() < 3 ? "fewer than 3 distinct points" : "all collinear");
    } else {
        size_t dups = 0;
        for (size_t i = 0; i < in.pts.size(); ++i) dups += dt.dup_of()[i] != (int)i;
        std::printf("%zu points (%zu duplicates merged), %zu triangles, %zu hull vertices, %d flips, %.1f ms\n", in.pts.size(), dups,
                    dt.triangles().size(), dt.boundary().size(), dt.num_flips(), ms);
    }
    if (a.flag("svg")) write_file(a.get("svg"), render_svg(scene_with_hull(dt, false, "Delaunay triangulation"), {}));
    if (a.flag("mesh")) write_mesh(a.get("mesh"), dt, false);
    if (a.flag("stats")) print_stats();
    return finish_check(dt, a, false, true);
}

int cmd_voronoi(const Args& a) {
    if (a.pos.size() != 1) throw std::runtime_error("voronoi needs exactly one input file");
    Input in = read_input_file(a.pos[0]);
    double margin = a.num("margin", 0.1);
    if (!(margin >= 0) || margin > 1e6) throw std::runtime_error("--margin must be between 0 and 1e6");
    if (in.pts.empty()) { std::printf("0 sites, nothing to draw\n"); return 0; }
    Triangulation dt = Triangulation::delaunay(in.pts);
    Box box = bounding_box(in.pts, margin);
    auto cells = voronoi_cells(dt, box);
    size_t unb = 0, sites = 0;
    for (size_t i = 0; i < cells.size(); ++i)
        if (dt.dup_of()[i] == (int)i) { ++sites; unb += cells[i].unbounded; }
    std::printf("%zu sites, %zu cells (%zu unbounded, clipped to [%.4g,%.4g]x[%.4g,%.4g])\n", sites, sites, unb, box.x0, box.x1, box.y0, box.y1);
    int rc = 0;
    if (a.flag("verify")) {
        CheckReport r = check_voronoi(dt, cells, box, 2000, 1);
        std::printf("verify voronoi: %s\n", r.ok() ? "OK (areas tile the box, cells convex, 2000 nearest-site samples agree)" : r.summary().c_str());
        rc = r.ok() ? 0 : 1;
    }
    if (a.flag("svg")) {
        Scene s = scene_from(dt, false, "Voronoi diagram over Delaunay triangulation");
        s.cells = cells; s.box = box; s.has_box = true;
        SvgOptions o; o.fill_by_angle = false;
        write_file(a.get("svg"), render_svg(s, o));
    }
    if (a.flag("stats")) print_stats();
    return rc;
}

int cmd_hull(const Args& a) {
    if (a.pos.size() != 1) throw std::runtime_error("hull needs exactly one input file");
    Input in = read_input_file(a.pos[0]);
    auto h = convex_hull(in.pts);
    std::printf("hull: %zu vertices\n", h.size());
    for (int v : h) std::printf("%d %.17g %.17g\n", v, in.pts[v].x, in.pts[v].y);
    int rc = 0;
    Triangulation dt = Triangulation::delaunay(in.pts);
    if (!dt.degenerate()) {
        // cross-check: strict hull vertices == triangulation boundary vertices that are not collinear
        std::vector<int> b = dt.boundary(), strict;
        for (size_t i = 0; i < b.size(); ++i) {
            int p = b[(i + b.size() - 1) % b.size()], q = b[i], r = b[(i + 1) % b.size()];
            if (orient2d(in.pts[p], in.pts[q], in.pts[r]) != 0) strict.push_back(q);
        }
        std::set<int> A, B;
        for (int v : h) A.insert(dt.dup_of()[v]);
        for (int v : strict) B.insert(v);
        bool same = A == B;
        std::printf("cross-check vs triangulation boundary: %s\n", same ? "identical" : "MISMATCH");
        if (!same) rc = 1;
    }
    if (a.flag("svg")) {
        Scene s = scene_from(dt, false, "Convex hull");
        s.hull = h; s.tris.clear();
        write_file(a.get("svg"), render_svg(s, {}));
    }
    return rc;
}

int cmd_cdt(const Args& a) {
    if (a.pos.size() != 1) throw std::runtime_error("cdt needs exactly one input file");
    Input in = read_input_file(a.pos[0]);
    bool carve = !a.flag("no-carve");
    Triangulation dt = Triangulation::constrained(in.pts, in.segs, carve);
    size_t extra = dt.points().size() - in.pts.size();
    std::printf("%zu input vertices (+%zu from segment intersections), %zu segments after splitting, %zu triangles%s\n", in.pts.size(), extra,
                dt.segments().size(), dt.triangles(carve).size(), carve ? " inside the domain" : "");
    if (a.flag("mesh")) write_mesh(a.get("mesh"), dt, carve);
    if (carve && dt.triangles(true).empty() && !dt.degenerate())
        std::printf("note: no triangle is inside the domain — the segments do not enclose a region (use --no-carve to keep the full triangulation)\n");
    if (a.flag("svg")) write_file(a.get("svg"), render_svg(scene_from(dt, carve, "Constrained Delaunay triangulation"), {}));
    if (a.flag("stats")) print_stats();
    return finish_check(dt, a, carve, false);
}

int cmd_nearest(const Args& a) {
    if (a.pos.size() != 3) throw std::runtime_error("nearest needs <file> X Y");
    Input in = read_input_file(a.pos[0]);
    Pt q{0, 0};
    {
        char *e1 = nullptr, *e2 = nullptr;
        q.x = std::strtod(a.pos[1].c_str(), &e1);
        q.y = std::strtod(a.pos[2].c_str(), &e2);
        if (*e1 || *e2 || !std::isfinite(q.x) || !std::isfinite(q.y)) throw std::runtime_error("nearest: X and Y must be finite numbers");
    }
    if (in.pts.empty()) throw std::runtime_error("nearest: the input has no points");
    Triangulation dt = Triangulation::delaunay(in.pts);
    int v = dt.nearest(q);
    std::printf("nearest site: #%d (%.17g, %.17g), distance %.12g\n", v, in.pts[v].x, in.pts[v].y,
                std::hypot(in.pts[v].x - q.x, in.pts[v].y - q.y));
    if (a.flag("verify")) {
        double best = 1e300;
        for (auto& p : in.pts) best = std::min(best, std::hypot(p.x - q.x, p.y - q.y));
        bool ok = std::fabs(best - std::hypot(in.pts[v].x - q.x, in.pts[v].y - q.y)) <= 1e-12 * std::max(1.0, best);
        std::printf("verify: brute force distance %.12g — %s\n", best, ok ? "OK" : "MISMATCH");
        return ok ? 0 : 1;
    }
    return 0;
}

int cmd_check(const Args& a) {
    if (a.pos.size() != 1) throw std::runtime_error("check needs exactly one input file");
    Input in = read_input_file(a.pos[0]);
    bool pslg = !in.segs.empty();
    Triangulation dt = pslg ? Triangulation::constrained(in.pts, in.segs, true) : Triangulation::delaunay(in.pts);
    CheckOptions co;
    co.global_empty_circle = !pslg && in.pts.size() <= 3000;
    co.inside_only = pslg;
    CheckReport r = check_triangulation(dt, co);
    std::printf("%s\n", r.summary().c_str());
    if (!pslg) {
        Box box = bounding_box(in.pts, 0.1);
        CheckReport v = check_voronoi(dt, voronoi_cells(dt, box), box, 1000, 7);
        std::printf("voronoi: %s\n", v.ok() ? "OK" : v.summary().c_str());
        if (!v.ok()) return 1;
    }
    return r.ok() ? 0 : 1;
}

int cmd_gen(const Args& a) {
    if (a.pos.empty()) throw std::runtime_error("gen needs a kind");
    int n = 100;
    if (a.pos.size() > 1) {
        char* e = nullptr;
        long v = std::strtol(a.pos[1].c_str(), &e, 10);
        if (a.pos[1].empty() || *e || v < 1 || v > 50000000) throw std::runtime_error("gen: count must be an integer in 1..50000000, got '" + a.pos[1] + "'");
        n = (int)v;
    }
    if (a.pos.size() > 2) throw std::runtime_error("gen: unexpected argument '" + a.pos[2] + "'");
    Input in = generate(a.pos[0], n, (unsigned)a.num("seed", 1));
    std::cout << format_input(in);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2 || std::string(argv[1]) == "--help" || std::string(argv[1]) == "help") {
        std::fputs(kUsage, stdout);
        return argc < 2 ? 2 : 0;
    }
    std::string cmd = argv[1];
    try {
        Args a = parse_args(argc, argv);
        if (cmd == "gen") return cmd_gen(a);
        if (cmd == "delaunay") return cmd_delaunay(a);
        if (cmd == "voronoi") return cmd_voronoi(a);
        if (cmd == "hull") return cmd_hull(a);
        if (cmd == "cdt") return cmd_cdt(a);
        if (cmd == "nearest") return cmd_nearest(a);
        if (cmd == "check") return cmd_check(a);
        std::fprintf(stderr, "sextant: unknown command '%s'\n\n%s", cmd.c_str(), kUsage);
        return 2;
    } catch (const GeometryError& e) {
        std::fprintf(stderr, "sextant: geometry error: %s\n", e.what());
        return 3;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "sextant: %s\n", e.what());
        return 2;
    }
}
