// Ruppert's Delaunay refinement on a carved constrained Delaunay triangulation.
//
//  * a segment is *encroached* when a vertex lies strictly inside its diametral circle; encroached
//    segments are split at their midpoint (in a CDT it suffices to look at the apexes of the two
//    triangles adjacent to the segment)
//  * a triangle is *bad* when its smallest angle is below the target or its area exceeds the bound;
//    its circumcentre is inserted unless that point would encroach a segment, in which case the
//    segments are split instead
//
// For input with no angle below 60 degrees the algorithm terminates with every angle >= 20.7 degrees;
// with sharper input angles it still improves the mesh but may not reach the target, which the report
// states honestly (and a Steiner-point cap guarantees termination).
#include <algorithm>
#include <cmath>
#include <queue>
#include <unordered_map>

#include "triangulation.hpp"

namespace sextant {

namespace {
inline uint64_t ukey(int a, int b) {
    if (a > b) std::swap(a, b);
    return (uint64_t(uint32_t(a)) << 32) | uint32_t(b);
}
}  // namespace

bool Triangulation::split_segment(int si, std::vector<int>& dirty) {
    Segment s = segs_[si];
    int t, i;
    int a = s.a, b = s.b;
    if (!find_edge(a, b, t, i)) {
        std::swap(a, b);
        if (!find_edge(a, b, t, i)) throw GeometryError("internal: segment is not a mesh edge");
    }
    int u = tris_[t].n[i];
    int j = 0;
    while (tris_[u].n[j] != t) ++j;
    int c = tris_[t].v[i], d = tris_[u].v[j];
    Pt m{0.5 * (pts_[a].x + pts_[b].x), 0.5 * (pts_[a].y + pts_[b].y)};
    if (m == pts_[a] || m == pts_[b]) return false;  // endpoints are adjacent doubles: cannot split further
    // The midpoint is rounded to a double, so it may sit a hair off the segment. All four triangles that
    // the split creates must stay strictly counter-clockwise, otherwise leave the segment alone.
    if (c >= 0 && (orient2d(pts_[c], pts_[a], m) <= 0 || orient2d(pts_[c], m, pts_[b]) <= 0)) return false;
    if (d >= 0 && (orient2d(pts_[d], pts_[b], m) <= 0 || orient2d(pts_[d], m, pts_[a]) <= 0)) return false;
    int vid = add_vertex(m);
    split_edge(t, i, vid, nullptr);
    segs_[si].alive = false;
    segs_.push_back({a, vid, true});
    segs_.push_back({vid, b, true});
    dirty.push_back((int)segs_.size() - 2);
    dirty.push_back((int)segs_.size() - 1);
    return true;
}

RefineReport Triangulation::refine(const RefineOptions& opt) {
    if (!carved_ || !has_triangles_) throw GeometryError("refine needs a carved constrained triangulation (a closed PSLG)");
    if (!(opt.min_angle >= 0 && opt.min_angle <= 34.0)) throw GeometryError("min_angle must be in [0, 34] degrees (Ruppert's algorithm cannot honour more)");
    if (opt.max_area < 0) throw GeometryError("max_area must be >= 0");
    RefineReport rep;

    // Surround the domain with a buffer box so every domain segment has real triangles on both sides;
    // splitting a segment then never has to touch the convex hull. Buffer triangles are 'outside'.
    {
        double x0 = 1e300, y0 = 1e300, x1 = -1e300, y1 = -1e300;
        for (size_t v = 0; v < pts_.size(); ++v) {
            if (dup_of_[v] != (int)v) continue;
            x0 = std::min(x0, pts_[v].x); x1 = std::max(x1, pts_[v].x);
            y0 = std::min(y0, pts_[v].y); y1 = std::max(y1, pts_[v].y);
        }
        double span = std::max({x1 - x0, y1 - y0, 1e-9});
        double cx = 0.5 * (x0 + x1), cy = 0.5 * (y0 + y1), r = 8 * span;
        track_ = false;
        for (Pt c : {Pt{cx - r, cy - r}, Pt{cx + r, cy - r}, Pt{cx + r, cy + r}, Pt{cx - r, cy + r}}) {
            int v = add_vertex(c);
            insert_point(v, true);
        }
    }
    track_ = true;
    changed_.clear();

    std::unordered_map<uint64_t, int> seg_index;
    std::vector<char> unsplittable;
    auto reindex = [&]() {
        seg_index.clear();
        for (size_t i = 0; i < segs_.size(); ++i)
            if (segs_[i].alive) seg_index[ukey(segs_[i].a, segs_[i].b)] = (int)i;
        unsplittable.resize(segs_.size(), 0);
    };
    reindex();

    auto tri_bad = [&](int t) {
        const Tri& T = tris_[t];
        if (T.dead || T.ghost() || !T.inside) return false;
        const Pt &a = pts_[T.v[0]], &b = pts_[T.v[1]], &c = pts_[T.v[2]];
        if (min_angle_deg(a, b, c) < opt.min_angle) return true;
        return opt.max_area > 0 && 0.5 * std::fabs(triangle_area(a, b, c) * 2) > opt.max_area;
    };
    auto tri_key = [&](int t) {  // priority: worst angle first, then biggest area
        const Tri& T = tris_[t];
        const Pt &a = pts_[T.v[0]], &b = pts_[T.v[1]], &c = pts_[T.v[2]];
        return std::make_pair(-min_angle_deg(a, b, c), triangle_area(a, b, c));
    };
    using Item = std::pair<std::pair<double, double>, int>;
    std::priority_queue<Item> tq;  // max-heap on (-minangle, area): smallest angle first, then biggest area
    auto enqueue_tri = [&](int t) {
        if (tri_bad(t)) tq.push({tri_key(t), t});
    };
    for (size_t t = 0; t < tris_.size(); ++t) enqueue_tri((int)t);
    std::vector<int> segq;
    for (size_t i = 0; i < segs_.size(); ++i)
        if (segs_[i].alive) segq.push_back((int)i);

    auto seg_encroached = [&](int si) {
        const Segment& s = segs_[si];
        int t, i;
        for (int dir = 0; dir < 2; ++dir) {
            if (!(dir == 0 ? find_edge(s.a, s.b, t, i) : find_edge(s.b, s.a, t, i))) continue;
            const Tri& T = tris_[t];
            if (!T.inside || T.v[i] < 0) continue;  // only vertices of the meshed domain count
            if (encroaches(pts_[T.v[i]], s)) return true;
        }
        return false;
    };
    auto drain_changed = [&]() {
        for (int t : changed_) {
            if (tris_[t].dead) continue;
            enqueue_tri(t);
            for (int k = 0; k < 3; ++k)
                if (tris_[t].con >> k & 1) {
                    auto it = seg_index.find(ukey(tris_[t].v[(k + 1) % 3], tris_[t].v[(k + 2) % 3]));
                    if (it != seg_index.end()) segq.push_back(it->second);
                }
        }
        changed_.clear();
    };

    auto process_segments = [&]() {
        while (!segq.empty()) {
            int si = segq.back();
            segq.pop_back();
            if (si >= (int)segs_.size() || !segs_[si].alive || unsplittable[si]) continue;
            if (!seg_encroached(si)) continue;
            if (rep.steiner_points >= opt.max_steiner) { rep.hit_cap = true; return; }
            std::vector<int> dirty;
            if (!split_segment(si, dirty)) { unsplittable[si] = 1; continue; }
            ++rep.steiner_points;
            ++rep.segment_splits;
            reindex();
            for (int d : dirty) segq.push_back(d);
            drain_changed();
        }
    };

    process_segments();
    while (!tq.empty() && !rep.hit_cap) {
        int t = tq.top().second;
        tq.pop();
        if (!tri_bad(t)) continue;
        const Tri& T = tris_[t];
        Pt cc = circumcenter(pts_[T.v[0]], pts_[T.v[1]], pts_[T.v[2]]);
        if (!std::isfinite(cc.x) || !std::isfinite(cc.y)) continue;
        // would the circumcentre encroach a segment? then split those instead
        bool progressed = false;
        std::vector<int> hit;
        for (size_t si = 0; si < segs_.size(); ++si)
            if (segs_[si].alive && encroaches(cc, segs_[si])) hit.push_back((int)si);
        if (!hit.empty()) {
            for (int si : hit) {
                if (unsplittable[si]) continue;
                if (rep.steiner_points >= opt.max_steiner) { rep.hit_cap = true; break; }
                std::vector<int> dirty;
                if (!split_segment(si, dirty)) { unsplittable[si] = 1; continue; }
                ++rep.steiner_points;
                ++rep.segment_splits;
                progressed = true;
                reindex();
                for (int d : dirty) segq.push_back(d);
                drain_changed();
                break;  // splitting changes the mesh: re-evaluate the triangle from scratch
            }
            if (progressed) { process_segments(); enqueue_tri(t); }
            continue;
        }
        if (rep.steiner_points >= opt.max_steiner) { rep.hit_cap = true; break; }
        int vid = add_vertex(cc);
        int got = insert_point(vid, true);
        if (got != vid) {  // coincided with an existing vertex: drop the spare slot's role
            continue;
        }
        ++rep.steiner_points;
        drain_changed();
        process_segments();
    }
    track_ = false;
    changed_.clear();
    // compact the segment list
    std::vector<Segment> alive;
    for (const Segment& s : segs_)
        if (s.alive) alive.push_back(s);
    segs_.swap(alive);
    rep.min_angle = 180;
    rep.max_angle = 0;
    for (const Tri& T : tris_) {
        if (T.dead || T.ghost() || !T.inside) continue;
        rep.min_angle = std::min(rep.min_angle, min_angle_deg(pts_[T.v[0]], pts_[T.v[1]], pts_[T.v[2]]));
        rep.max_angle = std::max(rep.max_angle, max_angle_deg(pts_[T.v[0]], pts_[T.v[1]], pts_[T.v[2]]));
    }
    return rep;
}

}  // namespace sextant
