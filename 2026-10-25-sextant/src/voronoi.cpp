#include "voronoi.hpp"

#include <algorithm>
#include <cmath>

namespace sextant {

Box bounding_box(const std::vector<Pt>& pts, double margin) {
    if (pts.empty()) return {0, 0, 1, 1};
    Box b{pts[0].x, pts[0].y, pts[0].x, pts[0].y};
    for (const Pt& p : pts) {
        b.x0 = std::min(b.x0, p.x); b.x1 = std::max(b.x1, p.x);
        b.y0 = std::min(b.y0, p.y); b.y1 = std::max(b.y1, p.y);
    }
    double span = std::max(b.width(), b.height());
    if (span <= 0) span = 1;
    double m = margin * span;
    return {b.x0 - m, b.y0 - m, b.x1 + m, b.y1 + m};
}

double polygon_area(const std::vector<Pt>& poly) {
    // shoelace relative to the first vertex: with absolute coordinates a small polygon far from the
    // origin loses all its digits to cancellation
    if (poly.empty()) return 0;
    double a = 0;
    for (size_t i = 0; i < poly.size(); ++i) {
        double px = poly[i].x - poly[0].x, py = poly[i].y - poly[0].y;
        double qx = poly[(i + 1) % poly.size()].x - poly[0].x, qy = poly[(i + 1) % poly.size()].y - poly[0].y;
        a += px * qy - qx * py;
    }
    return 0.5 * a;
}

Pt polygon_centroid(const std::vector<Pt>& poly) {
    double a = 0, cx = 0, cy = 0;
    // translate to the first vertex for accuracy
    const Pt o = poly.empty() ? Pt{} : poly[0];
    for (size_t i = 0; i < poly.size(); ++i) {
        double px = poly[i].x - o.x, py = poly[i].y - o.y;
        double qx = poly[(i + 1) % poly.size()].x - o.x, qy = poly[(i + 1) % poly.size()].y - o.y;
        double cr = px * qy - qx * py;
        a += cr;
        cx += (px + qx) * cr;
        cy += (py + qy) * cr;
    }
    if (std::fabs(a) < 1e-300) return o;
    return {o.x + cx / (3 * a), o.y + cy / (3 * a)};
}

// Sutherland-Hodgman against the half-plane (q - o) . n <= c.
static std::vector<Pt> clip(const std::vector<Pt>& poly, const Pt& o, double nx, double ny, double c) {
    std::vector<Pt> out;
    size_t m = poly.size();
    for (size_t i = 0; i < m; ++i) {
        const Pt& p = poly[i];
        const Pt& q = poly[(i + 1) % m];
        double dp = (p.x - o.x) * nx + (p.y - o.y) * ny - c;
        double dq = (q.x - o.x) * nx + (q.y - o.y) * ny - c;
        bool pin = dp <= 0, qin = dq <= 0;
        if (pin) out.push_back(p);
        if (pin != qin) {
            double t = dp / (dp - dq);
            out.push_back({p.x + t * (q.x - p.x), p.y + t * (q.y - p.y)});
        }
    }
    return out;
}

std::vector<VoronoiCell> voronoi_cells(const Triangulation& dt, const Box& box) {
    const auto& pts = dt.points();
    std::vector<VoronoiCell> cells(pts.size());
    std::vector<int> hull = dt.boundary();
    std::vector<char> on_hull(pts.size(), 0);
    for (int v : hull) on_hull[v] = 1;
    std::vector<int> sites;
    if (dt.degenerate()) sites = dt.chain();
    else
        for (size_t i = 0; i < pts.size(); ++i)
            if (dt.dup_of()[i] == (int)i) sites.push_back((int)i);
    for (int v : sites) {
        // Work in coordinates relative to the site so tiny cells (near-coincident sites) keep their precision.
        const Pt s0 = pts[v];
        std::vector<Pt> poly = {{box.x0 - s0.x, box.y0 - s0.y}, {box.x1 - s0.x, box.y0 - s0.y},
                                {box.x1 - s0.x, box.y1 - s0.y}, {box.x0 - s0.x, box.y1 - s0.y}};
        std::vector<int> nbr;
        if (dt.degenerate()) {
            auto& ch = dt.chain();
            auto it = std::find(ch.begin(), ch.end(), v);
            if (it != ch.begin()) nbr.push_back(*(it - 1));
            if (it + 1 != ch.end()) nbr.push_back(*(it + 1));
        } else {
            nbr = dt.neighbors(v);
        }
        for (int w : nbr) {
            double dx = pts[w].x - s0.x, dy = pts[w].y - s0.y;
            poly = clip(poly, Pt{0, 0}, dx, dy, 0.5 * (dx * dx + dy * dy));
            if (poly.empty()) break;
        }
        cells[v].site = v;
        // Drop vertices that clipping duplicated up to rounding (relative to the cell's own extent).
        if (poly.size() >= 3) {
            double ext = 0;
            for (const Pt& q : poly) ext = std::max(ext, std::max(std::fabs(q.x), std::fabs(q.y)));
            double eps = 1e-12 * ext;
            std::vector<Pt> clean;
            for (const Pt& q : poly)
                if (clean.empty() || std::fabs(q.x - clean.back().x) > eps || std::fabs(q.y - clean.back().y) > eps) clean.push_back(q);
            while (clean.size() > 1 && std::fabs(clean.front().x - clean.back().x) <= eps &&
                   std::fabs(clean.front().y - clean.back().y) <= eps)
                clean.pop_back();
            poly.swap(clean);
        }
        for (Pt& q : poly) { q.x += s0.x; q.y += s0.y; }
        cells[v].polygon = poly;
        cells[v].unbounded = dt.degenerate() || on_hull[v];
    }
    for (size_t i = 0; i < pts.size(); ++i)
        if (dt.dup_of()[i] != (int)i) cells[i] = cells[dt.dup_of()[i]];
    return cells;
}

std::vector<int> convex_hull(const std::vector<Pt>& pts) {
    std::vector<int> idx;
    for (size_t i = 0; i < pts.size(); ++i) idx.push_back((int)i);
    std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
        return pts[a].x < pts[b].x || (pts[a].x == pts[b].x && pts[a].y < pts[b].y);
    });
    idx.erase(std::unique(idx.begin(), idx.end(), [&](int a, int b) { return pts[a] == pts[b]; }), idx.end());
    if (idx.size() < 3) return idx;
    std::vector<int> h(2 * idx.size());
    size_t k = 0;
    for (size_t i = 0; i < idx.size(); ++i) {
        while (k >= 2 && orient2d(pts[h[k - 2]], pts[h[k - 1]], pts[idx[i]]) <= 0) --k;
        h[k++] = idx[i];
    }
    for (size_t i = idx.size() - 1, t = k + 1; i > 0; --i) {
        while (k >= t && orient2d(pts[h[k - 2]], pts[h[k - 1]], pts[idx[i - 1]]) <= 0) --k;
        h[k++] = idx[i - 1];
    }
    h.resize(k - 1);
    return h;
}

double cell_energy(const VoronoiCell& c, const Pt& site) {
    // integral of |x-s|^2 over a polygon: sum over fan triangles from the site.
    double e = 0;
    size_t m = c.polygon.size();
    for (size_t i = 0; i < m; ++i) {
        Pt a{c.polygon[i].x - site.x, c.polygon[i].y - site.y};
        Pt b{c.polygon[(i + 1) % m].x - site.x, c.polygon[(i + 1) % m].y - site.y};
        double cr = a.x * b.y - a.y * b.x;  // 2 * signed area of triangle (0,a,b)
        e += cr / 12.0 * (a.x * a.x + a.y * a.y + a.x * b.x + a.y * b.y + b.x * b.x + b.y * b.y);
    }
    return e;
}

std::vector<Pt> lloyd(const std::vector<Pt>& in, const Box& box, int iterations, LloydReport* rep) {
    std::vector<Pt> pts = in;
    for (int it = 0; it <= iterations; ++it) {
        Triangulation dt = Triangulation::delaunay(pts);
        auto cells = voronoi_cells(dt, box);
        double energy = 0;
        for (size_t i = 0; i < pts.size(); ++i)
            if (dt.dup_of()[i] == (int)i && !cells[i].polygon.empty()) energy += cell_energy(cells[i], pts[i]);
        if (rep) rep->energy.push_back(energy);
        if (it == iterations) break;
        for (size_t i = 0; i < pts.size(); ++i)
            if (dt.dup_of()[i] == (int)i && cells[i].polygon.size() >= 3) pts[i] = polygon_centroid(cells[i].polygon);
        for (size_t i = 0; i < pts.size(); ++i)
            if (dt.dup_of()[i] != (int)i) pts[i] = pts[dt.dup_of()[i]];
    }
    return pts;
}

}  // namespace sextant
