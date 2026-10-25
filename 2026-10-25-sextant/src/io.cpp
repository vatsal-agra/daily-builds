#include "io.hpp"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>

namespace sextant {

static double parse_double(const std::string& s, const std::string& where) {
    char* end = nullptr;
    double v = std::strtod(s.c_str(), &end);
    if (s.empty() || *end != 0 || !std::isfinite(v)) throw std::runtime_error(where + ": bad number '" + s + "'");
    return v;
}
static int parse_int(const std::string& s, const std::string& where) {
    char* end = nullptr;
    long v = std::strtol(s.c_str(), &end, 10);
    if (s.empty() || *end != 0 || v < 0 || v > 100000000) throw std::runtime_error(where + ": bad index '" + s + "'");
    return (int)v;
}

Input parse_input(const std::string& text, const std::string& name) {
    Input in;
    std::istringstream ss(text);
    std::string line;
    int ln = 0;
    while (std::getline(ss, line)) {
        ++ln;
        auto h = line.find('#');
        if (h != std::string::npos) line.resize(h);
        std::istringstream ls(line);
        std::vector<std::string> tok;
        for (std::string t; ls >> t;) tok.push_back(t);
        if (tok.empty()) continue;
        std::string where = name + ":" + std::to_string(ln);
        if (tok[0] == "s") {
            if (tok.size() != 3) throw std::runtime_error(where + ": segment needs two indices ('s i j')");
            in.segs.push_back({parse_int(tok[1], where), parse_int(tok[2], where)});
            continue;
        }
        if (tok[0] == "v" || tok[0] == "p") tok.erase(tok.begin());
        if (tok.size() != 2) throw std::runtime_error(where + ": expected 'x y', got " + std::to_string(tok.size()) + " fields");
        in.pts.push_back({parse_double(tok[0], where), parse_double(tok[1], where)});
    }
    for (auto& s : in.segs)
        if (s.first >= (int)in.pts.size() || s.second >= (int)in.pts.size())
            throw std::runtime_error(name + ": segment " + std::to_string(s.first) + "-" + std::to_string(s.second) +
                                     " references a vertex that does not exist (" + std::to_string(in.pts.size()) + " vertices)");
    return in;
}

Input read_input_file(const std::string& path) {
    std::ostringstream buf;
    if (path == "-") buf << std::cin.rdbuf();
    else {
        std::ifstream f(path);
        if (!f) throw std::runtime_error("cannot open '" + path + "'");
        buf << f.rdbuf();
    }
    return parse_input(buf.str(), path == "-" ? "<stdin>" : path);
}

std::string format_input(const Input& in) {
    std::ostringstream o;
    o.precision(17);
    for (auto& p : in.pts) o << p.x << " " << p.y << "\n";
    for (auto& s : in.segs) o << "s " << s.first << " " << s.second << "\n";
    return o.str();
}

std::vector<std::string> generator_kinds() {
    return {"uniform", "grid", "circle", "cluster", "spiral", "line", "degenerate", "star", "gear", "annulus",
            "pentagram", "comb", "lshape"};
}

static void add_polygon(Input& in, const std::vector<Pt>& poly) {
    int base = (int)in.pts.size();
    for (auto& p : poly) in.pts.push_back(p);
    for (size_t i = 0; i < poly.size(); ++i) in.segs.push_back({base + (int)i, base + (int)((i + 1) % poly.size())});
}

Input generate(const std::string& kind, int n, unsigned seed) {
    Input in;
    std::mt19937_64 rng(seed);
    std::uniform_real_distribution<double> U(0, 1);
    if (n < 1) throw std::invalid_argument("count must be >= 1");
    if (kind == "uniform") {
        for (int i = 0; i < n; ++i) in.pts.push_back({U(rng), U(rng)});
    } else if (kind == "grid") {  // n x n integer lattice: every unit square is cocircular
        for (int i = 0; i < n; ++i)
            for (int j = 0; j < n; ++j) in.pts.push_back({(double)i, (double)j});
    } else if (kind == "circle") {  // all lattice points on x^2+y^2 = R^2: massively cocircular, exactly
        long R2 = 1;
        for (int i = 0; i < std::max(1, n); ++i) R2 *= 5;  // 5^n has many representations as a sum of squares
        if (n > 12) throw std::invalid_argument("circle: n <= 12");
        long R = (long)std::floor(std::sqrt((double)R2));
        for (long x = -R; x <= R; ++x) {
            long y2 = R2 - x * x;
            if (y2 < 0) continue;
            long y = (long)std::llround(std::sqrt((double)y2));
            if (y * y == y2) {
                in.pts.push_back({(double)x, (double)y});
                if (y != 0) in.pts.push_back({(double)x, (double)-y});
            }
        }
    } else if (kind == "cluster") {
        std::normal_distribution<double> G(0, 1);
        int k = std::max(1, n / 200 + 3);
        std::vector<Pt> centers;
        for (int i = 0; i < k; ++i) centers.push_back({U(rng) * 10, U(rng) * 10});
        for (int i = 0; i < n; ++i) {
            const Pt& c = centers[rng() % k];
            in.pts.push_back({c.x + 0.05 * G(rng), c.y + 0.05 * G(rng)});
        }
    } else if (kind == "spiral") {
        for (int i = 0; i < n; ++i) {
            double t = 0.1 * i;
            in.pts.push_back({t * std::cos(t) * 0.1, t * std::sin(t) * 0.1});
        }
    } else if (kind == "line") {
        for (int i = 0; i < n; ++i) in.pts.push_back({(double)i, 2.0 * i + 1});
    } else if (kind == "degenerate") {  // everything that breaks naive code, mixed together
        int s = std::max(2, (int)std::sqrt((double)n));
        for (int i = 0; i < s; ++i)
            for (int j = 0; j < s; ++j) in.pts.push_back({(double)i, (double)j});
        for (int i = 0; i < s; ++i) in.pts.push_back({(double)i, (double)i});                   // duplicates on the lattice
        for (int i = 0; i < s; ++i) in.pts.push_back({s + 1.0 + i, 0.5 * (s + 1.0 + i)});        // collinear tail
        for (int i = 0; i < s; ++i) {                                                           // near-degenerate slivers
            double e = std::ldexp(1.0, -40 - i);
            in.pts.push_back({0.5 + e * i, 0.5 + e * i * i});
        }
        for (int i = 0; i < s; ++i) in.pts.push_back({U(rng) * s, U(rng) * s});
    } else if (kind == "star") {  // star polygon, concave
        int m = std::max(5, n);
        std::vector<Pt> poly;
        for (int i = 0; i < m; ++i) {
            double a = 2 * M_PI * i / m, r = (i % 2) ? 0.45 : 1.0;
            poly.push_back({r * std::cos(a), r * std::sin(a)});
        }
        add_polygon(in, poly);
    } else if (kind == "gear") {
        int teeth = std::max(6, n);
        std::vector<Pt> poly;
        for (int i = 0; i < teeth; ++i) {
            double a0 = 2 * M_PI * i / teeth, w = 2 * M_PI / teeth;
            double rs[4] = {0.8, 1.0, 1.0, 0.8};
            double fs[4] = {0.0, 0.15, 0.45, 0.6};
            for (int k = 0; k < 4; ++k) poly.push_back({rs[k] * std::cos(a0 + fs[k] * w), rs[k] * std::sin(a0 + fs[k] * w)});
        }
        add_polygon(in, poly);
        int m = std::max(8, teeth);
        std::vector<Pt> hole;
        for (int i = 0; i < m; ++i) hole.push_back({0.3 * std::cos(2 * M_PI * i / m), 0.3 * std::sin(2 * M_PI * i / m)});
        add_polygon(in, hole);
    } else if (kind == "annulus") {  // square with a square hole (even-odd carving)
        add_polygon(in, {{0, 0}, {4, 0}, {4, 4}, {0, 4}});
        add_polygon(in, {{1, 1}, {3, 1}, {3, 3}, {1, 3}});
    } else if (kind == "pentagram") {  // self-crossing: 5 proper intersections
        std::vector<Pt> p;
        for (int i = 0; i < 5; ++i) p.push_back({std::cos(2 * M_PI * i / 5 + M_PI / 2), std::sin(2 * M_PI * i / 5 + M_PI / 2)});
        for (auto& q : p) in.pts.push_back(q);
        for (int i = 0; i < 5; ++i) in.segs.push_back({i, (i + 2) % 5});
    } else if (kind == "comb") {  // comb with n teeth: long thin triangles
        int m = std::max(2, n);
        std::vector<Pt> poly;
        poly.push_back({0, 0});
        poly.push_back({(double)(2 * m + 1), 0});
        poly.push_back({(double)(2 * m + 1), 3});
        for (int i = m - 1; i >= 0; --i) {
            double x = 2 * i + 1;
            poly.push_back({x + 1, 3});
            poly.push_back({x + 1, 1});
            poly.push_back({x, 1});
            poly.push_back({x, 3});
        }
        poly.push_back({0, 3});
        // drop consecutive duplicates
        std::vector<Pt> clean;
        for (auto& q : poly)
            if (clean.empty() || !(clean.back() == q)) clean.push_back(q);
        if (clean.size() > 1 && clean.front() == clean.back()) clean.pop_back();
        add_polygon(in, clean);
    } else if (kind == "lshape") {
        add_polygon(in, {{0, 0}, {3, 0}, {3, 1}, {1, 1}, {1, 3}, {0, 3}});
    } else {
        throw std::invalid_argument("unknown generator '" + kind + "'");
    }
    return in;
}

}  // namespace sextant
