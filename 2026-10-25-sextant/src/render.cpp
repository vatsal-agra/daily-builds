#include "render.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <sstream>

namespace sextant {

Scene scene_from(const Triangulation& dt, bool inside_only, const std::string& title) {
    Scene s;
    s.title = title;
    s.pts = dt.points();
    s.is_site.assign(s.pts.size(), 0);
    for (size_t i = 0; i < s.pts.size(); ++i) s.is_site[i] = dt.dup_of()[i] == (int)i;
    s.tris = dt.triangles(inside_only);
    for (auto& g : dt.segments()) s.segs.push_back({g.a, g.b});
    return s;
}

static std::string fmt(double v) {
    char b[48];
    std::snprintf(b, sizeof b, "%.4g", v);
    return b;
}

// Sequential colour ramp (min angle 0..60 deg): red -> amber -> green-teal. Used for the quality map.
static std::string ramp(double angle) {
    double t = std::max(0.0, std::min(1.0, angle / 60.0));
    struct C { double r, g, b; };
    C lo{214, 77, 62}, mid{236, 190, 84}, hi{66, 160, 138};
    C a = t < 0.5 ? lo : mid, b = t < 0.5 ? mid : hi;
    double u = t < 0.5 ? t * 2 : (t - 0.5) * 2;
    char buf[32];
    std::snprintf(buf, sizeof buf, "#%02x%02x%02x", (int)(a.r + (b.r - a.r) * u), (int)(a.g + (b.g - a.g) * u),
                  (int)(a.b + (b.b - a.b) * u));
    return buf;
}

std::string render_svg(const Scene& s, const SvgOptions& opt) {
    double x0 = 1e300, y0 = 1e300, x1 = -1e300, y1 = -1e300;
    auto grow = [&](double x, double y) { x0 = std::min(x0, x); x1 = std::max(x1, x); y0 = std::min(y0, y); y1 = std::max(y1, y); };
    for (size_t i = 0; i < s.pts.size(); ++i) grow(s.pts[i].x, s.pts[i].y);
    if (s.has_box) { grow(s.box.x0, s.box.y0); grow(s.box.x1, s.box.y1); }
    if (s.pts.empty()) { x0 = y0 = 0; x1 = y1 = 1; }
    double w = std::max(x1 - x0, 1e-12), h = std::max(y1 - y0, 1e-12);
    double pad = 0.04 * std::max(w, h);
    x0 -= pad; y0 -= pad; w += 2 * pad; h += 2 * pad;
    double scale = opt.width / w;
    int H = (int)(h * scale);
    auto X = [&](double x) { return (x - x0) * scale; };
    auto Y = [&](double y) { return (y1 + pad - y) * scale; };  // y up
    std::ostringstream o;
    o << "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 " << opt.width << " " << H << "' width='" << opt.width
      << "' height='" << H << "' font-family='system-ui,sans-serif'>\n";
    o << "<rect width='100%' height='100%' fill='#fbfaf7'/>\n";
    if (!s.cells.empty()) {
        o << "<g fill='none' stroke='#5b7fb5' stroke-width='1.2' stroke-linejoin='round'>\n";
        for (auto& c : s.cells) {
            if (c.polygon.size() < 3) continue;
            if (c.site >= 0 && !s.is_site[c.site]) continue;
            o << "<polygon points='";
            for (auto& p : c.polygon) o << fmt(X(p.x)) << "," << fmt(Y(p.y)) << " ";
            o << "'/>\n";
        }
        o << "</g>\n";
    }
    if (!s.tris.empty()) {
        o << "<g stroke='#3a3a3a' stroke-width='0.6' stroke-linejoin='round' opacity='" << (s.cells.empty() ? "1" : "0.55") << "'>\n";
        for (auto& t : s.tris) {
            const Pt &a = s.pts[t[0]], &b = s.pts[t[1]], &c = s.pts[t[2]];
            o << "<polygon fill='" << (opt.fill_by_angle ? ramp(min_angle_deg(a, b, c)) : "none") << "' fill-opacity='0.55' points='"
              << fmt(X(a.x)) << "," << fmt(Y(a.y)) << " " << fmt(X(b.x)) << "," << fmt(Y(b.y)) << " " << fmt(X(c.x)) << ","
              << fmt(Y(c.y)) << "'/>\n";
        }
        o << "</g>\n";
    }
    if (!s.segs.empty()) {
        o << "<g stroke='#1d1d1d' stroke-width='2.2' stroke-linecap='round'>\n";
        for (auto& g : s.segs)
            o << "<line x1='" << fmt(X(s.pts[g.first].x)) << "' y1='" << fmt(Y(s.pts[g.first].y)) << "' x2='"
              << fmt(X(s.pts[g.second].x)) << "' y2='" << fmt(Y(s.pts[g.second].y)) << "'/>\n";
        o << "</g>\n";
    }
    if (!s.hull.empty()) {
        o << "<polygon fill='none' stroke='#c4572d' stroke-width='2' stroke-dasharray='6 4' points='";
        for (int v : s.hull) o << fmt(X(s.pts[v].x)) << "," << fmt(Y(s.pts[v].y)) << " ";
        o << "'/>\n";
    }
    if (opt.show_points && s.pts.size() <= 4000) {
        o << "<g fill='#1d1d1d'>\n";
        for (size_t i = 0; i < s.pts.size(); ++i)
            if (s.is_site[i]) o << "<circle cx='" << fmt(X(s.pts[i].x)) << "' cy='" << fmt(Y(s.pts[i].y)) << "' r='2.2'/>\n";
        o << "</g>\n";
    }
    o << "<text x='12' y='" << H - 12 << "' font-size='13' fill='#555'>" << s.title << "</text>\n</svg>\n";
    return o.str();
}

}  // namespace sextant
