#include "triangulation.hpp"

#include <algorithm>
#include <cmath>
#include <deque>
#include <map>
#include <numeric>
#include <set>

namespace sextant {

namespace {
constexpr double kMaxCoord = 1e75;
inline int nx(int i) { return i == 2 ? 0 : i + 1; }
inline int pv(int i) { return i == 0 ? 2 : i - 1; }
inline uint64_t ekey(int a, int b) { return (uint64_t(uint32_t(a + 1)) << 32) | uint32_t(b + 1); }
inline uint64_t ukey(int a, int b) { return a < b ? ekey(a, b) : ekey(b, a); }

uint32_t spread(uint32_t v) {
    v &= 0xFFFF;
    v = (v | (v << 8)) & 0x00FF00FF;
    v = (v | (v << 4)) & 0x0F0F0F0F;
    v = (v | (v << 2)) & 0x33333333;
    v = (v | (v << 1)) & 0x55555555;
    return v;
}
}  // namespace

// ---------------------------------------------------------------------------------------------
// geometry helpers
// ---------------------------------------------------------------------------------------------
Pt circumcenter(const Pt& a, const Pt& b, const Pt& c) {
    double bx = b.x - a.x, by = b.y - a.y, cx = c.x - a.x, cy = c.y - a.y;
    double d = 2.0 * (bx * cy - by * cx);
    double b2 = bx * bx + by * by, c2 = cx * cx + cy * cy;
    return {a.x + (cy * b2 - by * c2) / d, a.y + (bx * c2 - cx * b2) / d};
}
double triangle_area(const Pt& a, const Pt& b, const Pt& c) {
    return 0.5 * ((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x));
}
static double angle_at(const Pt& p, const Pt& q, const Pt& r) {  // angle at p between q and r
    double ux = q.x - p.x, uy = q.y - p.y, vx = r.x - p.x, vy = r.y - p.y;
    double cr = std::fabs(ux * vy - uy * vx), dt = ux * vx + uy * vy;
    return std::atan2(cr, dt) * 180.0 / M_PI;
}
double min_angle_deg(const Pt& a, const Pt& b, const Pt& c) {
    return std::min({angle_at(a, b, c), angle_at(b, c, a), angle_at(c, a, b)});
}
double max_angle_deg(const Pt& a, const Pt& b, const Pt& c) {
    return std::max({angle_at(a, b, c), angle_at(b, c, a), angle_at(c, a, b)});
}

// ---------------------------------------------------------------------------------------------
// mesh primitives
// ---------------------------------------------------------------------------------------------
int Triangulation::new_tri() {
    int t;
    if (!free_.empty()) {
        t = free_.back();
        free_.pop_back();
        tris_[t] = Tri{};
    } else {
        t = (int)tris_.size();
        tris_.emplace_back();
        stamp_.push_back(0);
        rej_.push_back(0);
    }
    return t;
}
void Triangulation::kill(int t) {
    tris_[t].dead = true;
    free_.push_back(t);
}
int Triangulation::idx_of(const Tri& t, int v) {
    for (int i = 0; i < 3; ++i)
        if (t.v[i] == v) return i;
    return -1;
}
void Triangulation::set_tri(int t, int a, int b, int c) {
    Tri& T = tris_[t];
    T.v[0] = a; T.v[1] = b; T.v[2] = c;
    for (int i = 0; i < 3; ++i)
        if (T.v[i] >= 0) vtri_[T.v[i]] = t;
}
void Triangulation::replace_neighbor(int x, int oldn, int newn) {
    for (int k = 0; k < 3; ++k)
        if (tris_[x].n[k] == oldn) { tris_[x].n[k] = newn; return; }
    throw GeometryError("internal: neighbour back-pointer missing");
}
int Triangulation::add_vertex(const Pt& p) {
    pts_.push_back(p);
    dup_of_.push_back((int)pts_.size() - 1);
    vtri_.push_back(-1);
    return (int)pts_.size() - 1;
}

void Triangulation::link_all(const std::vector<int>& tris) {
    std::unordered_map<uint64_t, std::pair<int, int>> edges;
    for (int t : tris)
        for (int i = 0; i < 3; ++i)
            edges[ekey(tris_[t].v[nx(i)], tris_[t].v[pv(i)])] = {t, i};
    for (int t : tris)
        for (int i = 0; i < 3; ++i) {
            auto it = edges.find(ekey(tris_[t].v[pv(i)], tris_[t].v[nx(i)]));
            if (it == edges.end()) throw GeometryError("internal: open edge while linking");
            tris_[t].n[i] = it->second.first;
        }
}

// Is p inside the "circumcircle" of t, in the sense Bowyer-Watson needs? For a ghost triangle
// (b,a,-1) that is the open half-plane right of hull edge a->b, plus the open segment ab itself.
bool Triangulation::in_circle_region(int t, const Pt& p) const {
    const Tri& T = tris_[t];
    int k = -1;
    for (int i = 0; i < 3; ++i)
        if (T.v[i] < 0) k = i;
    if (k < 0) return incircle(pts_[T.v[0]], pts_[T.v[1]], pts_[T.v[2]], p) > 0;
    const Pt& e0 = pts_[T.v[nx(k)]];
    const Pt& e1 = pts_[T.v[pv(k)]];
    int o = orient2d(e0, e1, p);
    if (o > 0) return true;
    if (o < 0) return false;
    // collinear: inside iff strictly between the endpoints
    double dx = e1.x - e0.x, dy = e1.y - e0.y;
    double s = (p.x - e0.x) * dx + (p.y - e0.y) * dy;
    return s > 0 && s < dx * dx + dy * dy;
}

int Triangulation::find_ring_ghost(int g, const Pt& p) {
    // g is a ghost that failed the region test; the hull is a cycle of ghosts, search it.
    int cur = g;
    size_t limit = tris_.size() + 4;
    for (size_t step = 0; step < limit; ++step) {
        if (in_circle_region(cur, p)) return cur;
        const Tri& T = tris_[cur];
        int k = -1;
        for (int i = 0; i < 3; ++i)
            if (T.v[i] < 0) k = i;
        cur = T.n[nx(k)];
        if (cur == g) break;
    }
    throw GeometryError("internal: point could not be located outside the hull");
}

int Triangulation::locate(const Pt& p, int start, bool& duplicate, int& dup_vertex) {
    duplicate = false;
    dup_vertex = -1;
    int t = start;
    if (tris_[t].dead) {
        t = -1;
        for (size_t i = 0; i < tris_.size(); ++i)
            if (!tris_[i].dead) { t = (int)i; break; }
    }
    if (tris_[t].ghost()) {
        for (int i = 0; i < 3; ++i)
            if (tris_[t].v[i] < 0) t = tris_[t].n[i];
    }
    size_t limit = 8 * tris_.size() + 64, steps = 0;
    while (steps++ < limit) {
        const Tri& T = tris_[t];
        if (T.ghost()) return t;
        int r = (int)(rng_() % 3);
        bool moved = false;
        for (int k = 0; k < 3; ++k) {
            int i = (r + k) % 3;
            if (orient2d(pts_[T.v[nx(i)]], pts_[T.v[pv(i)]], p) < 0) {
                t = T.n[i];
                moved = true;
                break;
            }
        }
        if (!moved) {
            for (int i = 0; i < 3; ++i)
                if (pts_[T.v[i]] == p) { duplicate = true; dup_vertex = T.v[i]; }
            return t;
        }
    }
    // Should be unreachable with exact predicates; fall back to a linear scan to stay correct.
    for (size_t i = 0; i < tris_.size(); ++i) {
        const Tri& T = tris_[i];
        if (T.dead) continue;
        if (T.ghost()) { if (in_circle_region((int)i, p)) return (int)i; continue; }
        if (orient2d(pts_[T.v[0]], pts_[T.v[1]], p) >= 0 && orient2d(pts_[T.v[1]], pts_[T.v[2]], p) >= 0 &&
            orient2d(pts_[T.v[2]], pts_[T.v[0]], p) >= 0) {
            for (int k = 0; k < 3; ++k)
                if (pts_[T.v[k]] == p) { duplicate = true; dup_vertex = T.v[k]; }
            return (int)i;
        }
    }
    throw GeometryError("internal: locate failed");
}

// ---------------------------------------------------------------------------------------------
// insertion
// ---------------------------------------------------------------------------------------------
int Triangulation::insert_point(int vid, bool respect, std::vector<int>* created) {
    const Pt p = pts_[vid];
    bool dup;
    int dv;
    int t = locate(p, hint_, dup, dv);
    if (dup) return dv;
    if (tris_[t].ghost() && !in_circle_region(t, p)) t = find_ring_ghost(t, p);
    if (!tris_[t].ghost() && respect) {
        for (int i = 0; i < 3; ++i)
            if ((tris_[t].con >> i & 1) && orient2d(pts_[tris_[t].v[nx(i)]], pts_[tris_[t].v[pv(i)]], p) == 0) {
                split_edge(t, i, vid, created);
                return vid;
            }
    }

    // ---- grow the cavity -------------------------------------------------------------------
    ++cur_stamp_;
    std::vector<int> cavity{t}, queue{t};
    stamp_[t] = cur_stamp_;
    while (!queue.empty()) {
        int c = queue.back();
        queue.pop_back();
        for (int i = 0; i < 3; ++i) {
            int nb = tris_[c].n[i];
            if (stamp_[nb] == cur_stamp_ || rej_[nb] == cur_stamp_) continue;
            if (respect && (tris_[c].con >> i & 1)) continue;
            if (in_circle_region(nb, p)) {
                stamp_[nb] = cur_stamp_;
                cavity.push_back(nb);
                queue.push_back(nb);
            } else {
                rej_[nb] = cur_stamp_;
            }
        }
    }

    struct BEdge { int u, w, outside, k; uint8_t con; bool inside; };
    std::vector<BEdge> boundary;
    for (int guard = 0;; ++guard) {
        boundary.clear();
        for (int c : cavity) {
            if (stamp_[c] != cur_stamp_) continue;
            for (int i = 0; i < 3; ++i) {
                int nb = tris_[c].n[i];
                if (stamp_[nb] == cur_stamp_) continue;
                int k = 0;
                while (tris_[nb].n[k] != c) ++k;
                boundary.push_back({tris_[c].v[nx(i)], tris_[c].v[pv(i)], nb, k,
                                    (uint8_t)(tris_[c].con >> i & 1), tris_[c].inside});
            }
        }
        // Star-shapedness guard: a cavity edge that p does not strictly see means the cavity grew
        // across a constraint it should not have; give that triangle back.
        bool changed = false;
        for (const BEdge& e : boundary) {
            if (e.u < 0 || e.w < 0) continue;
            if (orient2d(pts_[e.u], pts_[e.w], p) <= 0) {
                int owner = -1;
                for (int c : cavity)
                    if (stamp_[c] == cur_stamp_ && c != t) {
                        const Tri& T = tris_[c];
                        for (int i = 0; i < 3; ++i)
                            if (T.v[nx(i)] == e.u && T.v[pv(i)] == e.w) owner = c;
                    }
                if (owner < 0) throw GeometryError("internal: insertion point on cavity boundary");
                stamp_[owner] = 0;
                rej_[owner] = cur_stamp_;
                changed = true;
                break;
            }
        }
        if (!changed) break;
        if (guard > 100000) throw GeometryError("internal: cavity repair did not converge");
    }
    std::vector<int> live;
    for (int c : cavity)
        if (stamp_[c] == cur_stamp_) live.push_back(c);

    for (int c : live) kill(c);
    std::unordered_map<int, int> by_start, by_end;
    std::vector<int> fresh;
    for (const BEdge& e : boundary) {
        int nt = new_tri();
        set_tri(nt, e.u, e.w, vid);
        Tri& T = tris_[nt];
        T.n[2] = e.outside;
        T.con = (uint8_t)(e.con << 2);
        T.inside = (e.u < 0 || e.w < 0) ? false : e.inside;
        tris_[e.outside].n[e.k] = nt;
        by_start[e.u] = nt;
        by_end[e.w] = nt;
        fresh.push_back(nt);
    }
    for (int nt : fresh) {
        Tri& T = tris_[nt];
        auto a = by_start.find(T.v[1]);  // neighbour across (w -> p) starts at w
        auto b = by_end.find(T.v[0]);    // neighbour across (p -> u) ends at u
        if (a == by_start.end() || b == by_end.end() || by_start.size() != fresh.size())
            throw GeometryError("internal: cavity boundary is not a simple cycle");
        T.n[0] = a->second;
        T.n[1] = b->second;
        if (!T.ghost()) hint_ = nt;
        stamp_[nt] = 0;
        rej_[nt] = 0;
    }
    if (created) created->insert(created->end(), fresh.begin(), fresh.end());
    return vid;
}

void Triangulation::split_edge(int t, int i, int vid, std::vector<int>* created) {
    int u = tris_[t].n[i];
    int c = tris_[t].v[i], a = tris_[t].v[nx(i)], b = tris_[t].v[pv(i)];
    int j = 0;
    while (tris_[u].n[j] != t) ++j;
    int d = tris_[u].v[j];
    if (tris_[u].v[nx(j)] != b || tris_[u].v[pv(j)] != a) throw GeometryError("internal: split_edge mismatch");
    int n_bc = tris_[t].n[nx(i)], n_ca = tris_[t].n[pv(i)];
    int n_ad = tris_[u].n[nx(j)], n_db = tris_[u].n[pv(j)];
    uint8_t f = tris_[t].con >> i & 1;
    uint8_t k_bc = tris_[t].con >> nx(i) & 1, k_ca = tris_[t].con >> pv(i) & 1;
    uint8_t k_ad = tris_[u].con >> nx(j) & 1, k_db = tris_[u].con >> pv(j) & 1;
    bool in_t = tris_[t].inside, in_u = tris_[u].inside;

    int t1 = t, u1 = u;
    int t2 = new_tri();
    int u2 = new_tri();
    stamp_[t2] = stamp_[u2] = rej_[t2] = rej_[u2] = 0;
    set_tri(t1, c, a, vid);
    set_tri(t2, c, vid, b);
    set_tri(u1, d, b, vid);
    set_tri(u2, d, vid, a);
    auto fill = [&](int x, int n0, int n1, int n2, int b0, int b1, int b2, bool ins) {
        Tri& T = tris_[x];
        T.n[0] = n0; T.n[1] = n1; T.n[2] = n2;
        T.con = (uint8_t)(b0 | b1 << 1 | b2 << 2);
        T.inside = T.ghost() ? false : ins;
    };
    fill(t1, u2, t2, n_ca, f, 0, k_ca, in_t);  // opp c = (a,p) ; opp a = (p,c) ; opp p = (c,a)
    fill(t2, u1, n_bc, t1, f, k_bc, 0, in_t);  // opp c = (p,b) ; opp p = (b,c) ; opp b = (c,p)
    fill(u1, t2, u2, n_db, f, 0, k_db, in_u);  // opp d = (b,p) ; opp b = (p,d) ; opp p = (d,b)
    fill(u2, t1, n_ad, u1, f, k_ad, 0, in_u);  // opp d = (p,a) ; opp p = (a,d) ; opp a = (d,p)
    replace_neighbor(n_bc, t, t2);
    replace_neighbor(n_ad, u, u2);
    hint_ = t1;
    if (tris_[hint_].ghost()) hint_ = t2;
    if (created) created->insert(created->end(), {t1, t2, u1, u2});
    std::vector<std::pair<int, int>> st{{t1, 2}, {t2, 1}, {u1, 2}, {u2, 1}};
    legalize(st);
}

bool Triangulation::locally_delaunay(int t, int i) const {
    const Tri& T = tris_[t];
    if (T.ghost() || (T.con >> i & 1)) return true;
    const Tri& U = tris_[T.n[i]];
    if (U.ghost()) return true;
    int j = 0;
    while (U.n[j] != t) ++j;
    return incircle(pts_[T.v[0]], pts_[T.v[1]], pts_[T.v[2]], pts_[U.v[j]]) <= 0;
}

void Triangulation::flip(int t, int i) {
    int u = tris_[t].n[i];
    int j = 0;
    while (tris_[u].n[j] != t) ++j;
    int a = tris_[t].v[i], b = tris_[t].v[nx(i)], c = tris_[t].v[pv(i)];
    int d = tris_[u].v[j];
    int n_ab = tris_[t].n[pv(i)], n_ca = tris_[t].n[nx(i)];
    uint8_t c_ab = tris_[t].con >> pv(i) & 1, c_ca = tris_[t].con >> nx(i) & 1;
    int n_bd = tris_[u].n[nx(j)], n_dc = tris_[u].n[pv(j)];
    uint8_t c_bd = tris_[u].con >> nx(j) & 1, c_dc = tris_[u].con >> pv(j) & 1;
    bool ins = tris_[t].inside;
    set_tri(t, a, b, d);
    set_tri(u, a, d, c);
    Tri& T = tris_[t];
    Tri& U = tris_[u];
    T.n[0] = n_bd; T.n[1] = u; T.n[2] = n_ab;
    T.con = (uint8_t)(c_bd | c_ab << 2);
    U.n[0] = n_dc; U.n[1] = n_ca; U.n[2] = t;
    U.con = (uint8_t)(c_dc | c_ca << 1);
    T.inside = U.inside = ins;
    replace_neighbor(n_bd, u, t);
    replace_neighbor(n_ca, t, u);
    ++flips_;
}

void Triangulation::legalize(std::vector<std::pair<int, int>>& st, std::vector<int>* touched) {
    while (!st.empty()) {
        auto [t, i] = st.back();
        st.pop_back();
        if (tris_[t].dead || locally_delaunay(t, i)) continue;
        int u = tris_[t].n[i];
        flip(t, i);
        st.push_back({t, 0});
        st.push_back({t, 2});
        st.push_back({u, 0});
        st.push_back({u, 1});
        if (touched) { touched->push_back(t); touched->push_back(u); }
    }
}

bool Triangulation::find_edge(int p, int q, int& t, int& i) const {
    int start = vtri_[p];
    if (start < 0 || tris_[start].dead) return false;
    int cur = start;
    size_t limit = tris_.size() + 4;
    for (size_t step = 0; step < limit; ++step) {
        const Tri& T = tris_[cur];
        int k = idx_of(T, p);
        if (k < 0) throw GeometryError("internal: stale vertex-triangle pointer");
        if (T.v[nx(k)] == q) { t = cur; i = pv(k); return true; }
        cur = T.n[nx(k)];
        if (cur == start) break;
    }
    return false;
}

void Triangulation::mark_constraint(int p, int q) {
    int t, i;
    if (!find_edge(p, q, t, i)) throw GeometryError("internal: constraint edge missing");
    tris_[t].con |= (uint8_t)(1 << i);
    int u = tris_[t].n[i];
    int j = 0;
    while (tris_[u].n[j] != t) ++j;
    tris_[u].con |= (uint8_t)(1 << j);
}
bool Triangulation::is_constrained(int p, int q) const {
    int t, i;
    return find_edge(p, q, t, i) && (tris_[t].con >> i & 1);
}

// ---------------------------------------------------------------------------------------------
// construction
// ---------------------------------------------------------------------------------------------
void Triangulation::build(const std::vector<Pt>& in) {
    pts_ = in;
    const int n = (int)pts_.size();
    for (const Pt& p : pts_)
        if (!std::isfinite(p.x) || !std::isfinite(p.y)) throw GeometryError("non-finite coordinate");
        else if (std::fabs(p.x) > kMaxCoord || std::fabs(p.y) > kMaxCoord)
            throw GeometryError("coordinate magnitude exceeds 1e75 (the exact predicates guarantee no overflow only below that)");
    dup_of_.resize(n);
    vtri_.assign(n, -1);
    std::iota(dup_of_.begin(), dup_of_.end(), 0);
    std::vector<int> idx(n);
    std::iota(idx.begin(), idx.end(), 0);
    std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
        return pts_[a].x < pts_[b].x || (pts_[a].x == pts_[b].x && pts_[a].y < pts_[b].y);
    });
    std::vector<int> uniq;
    for (int k = 0; k < n; ++k) {
        if (k > 0 && pts_[idx[k]] == pts_[idx[k - 1]]) dup_of_[idx[k]] = dup_of_[idx[k - 1]];
        else uniq.push_back(idx[k]);
    }
    // collinear / tiny inputs: no triangles
    auto all_collinear = [&]() {
        if (uniq.size() < 3) return true;
        for (size_t k = 2; k < uniq.size(); ++k)
            if (orient2d(pts_[uniq[0]], pts_[uniq[1]], pts_[uniq[k]]) != 0) return false;
        return true;
    };
    if (all_collinear()) {
        chain_ = uniq;
        has_triangles_ = false;
        return;
    }
    // Morton order for locality
    double minx = 1e300, miny = 1e300, maxx = -1e300, maxy = -1e300;
    for (int v : uniq) {
        minx = std::min(minx, pts_[v].x); maxx = std::max(maxx, pts_[v].x);
        miny = std::min(miny, pts_[v].y); maxy = std::max(maxy, pts_[v].y);
    }
    double sx = maxx > minx ? 65535.0 / (maxx - minx) : 0, sy = maxy > miny ? 65535.0 / (maxy - miny) : 0;
    std::vector<std::pair<uint32_t, int>> keyed;
    for (int v : uniq) {
        uint32_t qx = (uint32_t)((pts_[v].x - minx) * sx), qy = (uint32_t)((pts_[v].y - miny) * sy);
        keyed.push_back({spread(qx) | (spread(qy) << 1), v});
    }
    std::sort(keyed.begin(), keyed.end());
    std::vector<int> order;
    for (auto& kv : keyed) order.push_back(kv.second);

    int p0 = order[0], p1 = order[1], p2 = -1;
    for (size_t k = 2; k < order.size(); ++k)
        if (orient2d(pts_[p0], pts_[p1], pts_[order[k]]) != 0) { p2 = order[k]; break; }
    if (orient2d(pts_[p0], pts_[p1], pts_[p2]) < 0) std::swap(p1, p2);
    std::vector<int> first;
    int t0 = new_tri();
    set_tri(t0, p0, p1, p2);
    first.push_back(t0);
    int tv[3] = {p0, p1, p2};
    for (int e = 0; e < 3; ++e) {
        int a = tv[e], b = tv[(e + 1) % 3];
        int g = new_tri();
        set_tri(g, b, a, -1);
        first.push_back(g);
    }
    link_all(first);
    has_triangles_ = true;
    hint_ = t0;
    for (int v : order)
        if (v != p0 && v != p1 && v != p2) insert_point(v, false);
}

Triangulation Triangulation::delaunay(const std::vector<Pt>& pts) {
    Triangulation T;
    T.build(pts);
    return T;
}

std::vector<std::array<int, 3>> Triangulation::triangles(bool inside_only) const {
    std::vector<std::array<int, 3>> out;
    for (const Tri& T : tris_) {
        if (T.dead || T.ghost()) continue;
        if (inside_only && !T.inside) continue;
        out.push_back({T.v[0], T.v[1], T.v[2]});
    }
    return out;
}

std::vector<int> Triangulation::boundary() const {
    std::unordered_map<int, int> next;
    for (const Tri& T : tris_) {
        if (T.dead || !T.ghost()) continue;
        int k = idx_of(T, -1);
        // ghost (b,a,-1) up to rotation: real hull edge is a->b, i.e. v[k+2] -> v[k+1]
        next[T.v[pv(k)]] = T.v[nx(k)];
    }
    std::vector<int> out;
    if (next.empty()) return out;
    int start = next.begin()->first, cur = start;
    do {
        out.push_back(cur);
        cur = next.at(cur);
    } while (cur != start && out.size() <= next.size());
    return out;
}

std::vector<int> Triangulation::neighbors(int v) const {
    std::vector<int> out;
    int start = vtri_[v];
    if (start < 0) return out;
    int cur = start;
    size_t limit = tris_.size() + 4;
    for (size_t s = 0; s < limit; ++s) {
        const Tri& T = tris_[cur];
        int k = idx_of(T, v);
        if (T.v[nx(k)] >= 0) out.push_back(T.v[nx(k)]);
        cur = T.n[nx(k)];
        if (cur == start) break;
    }
    return out;
}

int Triangulation::nearest(const Pt& q) const {
    if (!has_triangles_) {
        int best = -1;
        double bd = 1e300;
        for (int v : chain_) {
            double d = (pts_[v].x - q.x) * (pts_[v].x - q.x) + (pts_[v].y - q.y) * (pts_[v].y - q.y);
            if (d < bd) { bd = d; best = v; }
        }
        return best;
    }
    auto d2 = [&](int v) {
        return (pts_[v].x - q.x) * (pts_[v].x - q.x) + (pts_[v].y - q.y) * (pts_[v].y - q.y);
    };
    int cur = -1;
    for (size_t i = 0; i < pts_.size(); ++i)
        if (dup_of_[i] == (int)i && vtri_[i] >= 0 && !tris_[vtri_[i]].dead) { cur = (int)i; break; }
    double cd = d2(cur);
    for (bool improved = true; improved;) {
        improved = false;
        for (int w : neighbors(cur)) {
            double dw = d2(w);
            if (dw < cd) { cd = dw; cur = w; improved = true; }
        }
    }
    return cur;
}

// ---------------------------------------------------------------------------------------------
// constrained triangulation
// ---------------------------------------------------------------------------------------------
Triangulation Triangulation::constrained(const std::vector<Pt>& in, const std::vector<std::pair<int, int>>& segs_in,
                                         bool carve) {
    Triangulation T;
    std::vector<Pt> pts = in;
    for (auto& s : segs_in)
        if (s.first < 0 || s.second < 0 || s.first >= (int)in.size() || s.second >= (int)in.size())
            throw GeometryError("segment references a vertex index out of range");
    // canonical ids for duplicate input points
    std::map<std::pair<double, double>, int> canon;
    std::vector<int> cid(in.size());
    for (size_t i = 0; i < in.size(); ++i) {
        if (!std::isfinite(in[i].x) || !std::isfinite(in[i].y)) throw GeometryError("non-finite coordinate");
        auto key = std::make_pair(in[i].x + 0.0, in[i].y + 0.0);
        auto it = canon.find(key);
        if (it == canon.end()) it = canon.emplace(key, (int)i).first;
        cid[i] = it->second;
    }
    std::vector<std::pair<int, int>> segs;
    std::set<uint64_t> seen;
    for (auto& s : segs_in) {
        int a = cid[s.first], b = cid[s.second];
        if (a == b || !seen.insert(ukey(a, b)).second) continue;
        segs.push_back({a, b});
    }
    // Planarise: split properly crossing segments at their intersection point. Candidate pairs come
    // from a uniform grid over segment bounding boxes, so the cost is O(S + K) rather than O(S^2) per
    // round; rounding the intersection to a double can create a new crossing, so repeat to a fixed point.
    for (int round = 0;; ++round) {
        if (round > 64) throw GeometryError("segment planarisation did not converge");
        const size_t S = segs.size();
        if (S < 2) break;
        double gx0 = 1e300, gy0 = 1e300, gx1 = -1e300, gy1 = -1e300;
        for (auto& [a, b] : segs)
            for (int v : {a, b}) {
                gx0 = std::min(gx0, pts[v].x); gx1 = std::max(gx1, pts[v].x);
                gy0 = std::min(gy0, pts[v].y); gy1 = std::max(gy1, pts[v].y);
            }
        int G = std::max(1, std::min(512, (int)std::sqrt((double)S)));
        double cw = std::max((gx1 - gx0) / G, 1e-300), ch = std::max((gy1 - gy0) / G, 1e-300);
        auto cell = [&](double v, double lo, double w) { return std::max(0, std::min(G - 1, (int)((v - lo) / w))); };
        std::vector<std::vector<int>> grid((size_t)G * G);
        for (size_t i = 0; i < S; ++i) {
            auto [a, b] = segs[i];
            int cx0 = cell(std::min(pts[a].x, pts[b].x), gx0, cw), cx1 = cell(std::max(pts[a].x, pts[b].x), gx0, cw);
            int cy0 = cell(std::min(pts[a].y, pts[b].y), gy0, ch), cy1 = cell(std::max(pts[a].y, pts[b].y), gy0, ch);
            for (int cy = cy0; cy <= cy1; ++cy)
                for (int cx = cx0; cx <= cx1; ++cx) grid[(size_t)cy * G + cx].push_back((int)i);
        }
        std::set<uint64_t> tested;
        std::vector<std::vector<std::pair<double, int>>> cuts(S);  // per segment: (parameter, vertex id)
        bool any = false;
        for (auto& bucket : grid)
            for (size_t u = 0; u < bucket.size(); ++u)
                for (size_t w = u + 1; w < bucket.size(); ++w) {
                    int i = bucket[u], j = bucket[w];
                    if (!tested.insert(((uint64_t)i << 32) | (uint32_t)j).second) continue;
                    auto [a, b] = segs[i];
                    auto [c, d] = segs[j];
                    if (a == c || a == d || b == c || b == d) continue;
                    int o1 = orient2d(pts[a], pts[b], pts[c]), o2 = orient2d(pts[a], pts[b], pts[d]);
                    int o3 = orient2d(pts[c], pts[d], pts[a]), o4 = orient2d(pts[c], pts[d], pts[b]);
                    if (o1 * o2 >= 0 || o3 * o4 >= 0) continue;
                    double rx = pts[b].x - pts[a].x, ry = pts[b].y - pts[a].y;
                    double sx = pts[d].x - pts[c].x, sy = pts[d].y - pts[c].y;
                    double denom = rx * sy - ry * sx;
                    double tt = ((pts[c].x - pts[a].x) * sy - (pts[c].y - pts[a].y) * sx) / denom;
                    double uu = ((pts[c].x - pts[a].x) * ry - (pts[c].y - pts[a].y) * rx) / denom;
                    Pt x{pts[a].x + tt * rx, pts[a].y + tt * ry};
                    auto key = std::make_pair(x.x + 0.0, x.y + 0.0);
                    int xid;
                    auto it = canon.find(key);
                    if (it != canon.end()) xid = it->second;
                    else { pts.push_back(x); xid = (int)pts.size() - 1; canon[key] = xid; }
                    cuts[i].push_back({tt, xid});
                    cuts[j].push_back({uu, xid});
                    any = true;
                }
        if (!any) break;
        std::vector<std::pair<int, int>> next;
        seen.clear();
        auto add = [&](int p, int q) {
            if (p != q && seen.insert(ukey(p, q)).second) next.push_back({p, q});
        };
        for (size_t i = 0; i < S; ++i) {
            std::sort(cuts[i].begin(), cuts[i].end());
            int prev = segs[i].first;
            for (auto& [t, v] : cuts[i]) { add(prev, v); prev = v; }
            add(prev, segs[i].second);
        }
        segs.swap(next);
    }
    T.build(pts);
    if (!T.has_triangles_) {
        // All vertices on one line: there is nothing to triangulate, but the PSLG is still valid. Each
        // segment becomes the run of consecutive chain edges between its endpoints.
        std::map<int, size_t> pos;
        for (size_t k = 0; k < T.chain_.size(); ++k) pos[T.chain_[k]] = k;
        std::set<uint64_t> have;
        for (auto& [a, b] : segs) {
            size_t i = pos.at(T.dup_of_[a]), j = pos.at(T.dup_of_[b]);
            if (i > j) std::swap(i, j);
            for (size_t k = i; k < j; ++k) {
                int p = T.chain_[k], q = T.chain_[k + 1];
                if (have.insert(ukey(p, q)).second) T.segs_.push_back({p, q});
            }
        }
        return T;
    }
    // map canonical segment endpoints; duplicates in pts already point to canonical ids via cid
    std::set<uint64_t> done;
    std::vector<std::pair<int, int>> work(segs.rbegin(), segs.rend());
    T.segs_.clear();
    while (!work.empty()) {
        auto [a, b] = work.back();
        work.pop_back();
        a = T.dup_of_[a]; b = T.dup_of_[b];
        if (a == b) continue;
        int t, i;
        if (T.find_edge(a, b, t, i)) {
            T.mark_constraint(a, b);
            if (done.insert(ukey(a, b)).second) T.segs_.push_back({a, b});
            continue;
        }
        // locate the wedge at a that contains the direction to b
        int start = T.vtri_[a], cur = start;
        int wt = -1;
        int mid = -1;
        for (size_t step = 0; step < T.tris_.size() + 4; ++step) {
            const Tri& TT = T.tris_[cur];
            int k = idx_of(TT, a);
            int x = TT.v[nx(k)], y = TT.v[pv(k)];
            if (x >= 0 && y >= 0) {
                int o1 = orient2d(T.pts_[a], T.pts_[x], T.pts_[b]);
                int o2 = orient2d(T.pts_[a], T.pts_[y], T.pts_[b]);
                if (o1 == 0 && o2 <= 0) {
                    // b on ray a->x (x != b since the edge does not exist): x must lie before b
                    mid = x; break;
                }
                if (o2 == 0 && o1 >= 0) { mid = y; break; }
                if (o1 > 0 && o2 < 0) { wt = cur; break; }
            }
            cur = TT.n[nx(k)];
            if (cur == start) break;
        }
        if (mid >= 0) {
            work.push_back({mid, b});
            work.push_back({a, mid});
            continue;
        }
        if (wt < 0) throw GeometryError("internal: could not find the wedge for a constraint segment");
        // walk across the triangulation collecting the edges the segment crosses
        std::deque<std::pair<int, int>> crossing;
        {
            const Tri& W = T.tris_[wt];
            int k = idx_of(W, a);
            int R = W.v[nx(k)], L = W.v[pv(k)];  // R right of a->b, L left of a->b
            int curt = wt;
            for (size_t step = 0;; ++step) {
                if (step > T.tris_.size() + 4) throw GeometryError("internal: crossing walk did not terminate");
                if (T.is_constrained(L, R)) throw GeometryError("constraint segments cross (unresolved intersection)");
                crossing.push_back({L, R});
                int ti, ii;
                if (!T.find_edge(L, R, ti, ii)) throw GeometryError("internal: crossing edge missing");
                curt = ti;
                int z = T.tris_[curt].v[ii];
                if (z < 0) throw GeometryError("internal: constraint leaves the hull");
                if (z == b) break;
                int o = orient2d(T.pts_[a], T.pts_[b], T.pts_[z]);
                if (o == 0) {  // vertex exactly on the segment: split there
                    crossing.clear();
                    mid = z;
                    break;
                }
                if (o > 0) L = z; else R = z;
            }
        }
        if (mid >= 0) {
            work.push_back({mid, b});
            work.push_back({a, mid});
            continue;
        }
        // Sloan's edge-flipping insertion
        std::vector<std::pair<int, int>> fresh;
        size_t guard = 0, cap = 64 * (crossing.size() + 8) * (crossing.size() + 8);
        auto crosses = [&](int p, int q) {
            return orient2d(T.pts_[a], T.pts_[b], T.pts_[p]) * orient2d(T.pts_[a], T.pts_[b], T.pts_[q]) < 0;
        };
        while (!crossing.empty()) {
            if (++guard > cap) throw GeometryError("internal: constraint insertion did not converge");
            auto [p, q] = crossing.front();
            crossing.pop_front();
            int ft, fi;
            if (!T.find_edge(p, q, ft, fi) && !T.find_edge(q, p, ft, fi))
                throw GeometryError("internal: crossing edge vanished");
            int u = T.tris_[ft].n[fi];
            int j = 0;
            while (T.tris_[u].n[j] != ft) ++j;
            int ap = T.tris_[ft].v[fi], dp = T.tris_[u].v[j];
            if (ap < 0 || dp < 0) throw GeometryError("internal: constraint crosses the hull");
            int s1 = orient2d(T.pts_[ap], T.pts_[dp], T.pts_[p]);
            int s2 = orient2d(T.pts_[ap], T.pts_[dp], T.pts_[q]);
            if (s1 * s2 >= 0) { crossing.push_back({p, q}); continue; }  // quad not strictly convex yet
            T.flip(ft, fi);
            if (crosses(ap, dp)) crossing.push_back({ap, dp});
            else fresh.push_back({ap, dp});
        }
        T.mark_constraint(a, b);
        if (done.insert(ukey(a, b)).second) T.segs_.push_back({a, b});
        std::vector<std::pair<int, int>> st;
        for (auto& [p, q] : fresh) {
            int ft, fi;
            if (T.find_edge(p, q, ft, fi)) st.push_back({ft, fi});
        }
        T.legalize(st);
    }
    if (carve) T.carve_domain();
    return T;
}

void Triangulation::carve_domain() {
    const int INF = 1 << 29;
    std::vector<int> depth(tris_.size(), INF);
    std::deque<int> dq;
    for (size_t i = 0; i < tris_.size(); ++i)
        if (!tris_[i].dead && tris_[i].ghost()) { depth[i] = 0; dq.push_back((int)i); }
    while (!dq.empty()) {
        int t = dq.front();
        dq.pop_front();
        for (int i = 0; i < 3; ++i) {
            int nb = tris_[t].n[i];
            int w = (tris_[t].con >> i & 1) ? 1 : 0;
            if (depth[t] + w < depth[nb]) {
                depth[nb] = depth[t] + w;
                if (w) dq.push_back(nb); else dq.push_front(nb);
            }
        }
    }
    for (size_t i = 0; i < tris_.size(); ++i)
        if (!tris_[i].dead) tris_[i].inside = !tris_[i].ghost() && (depth[i] % 2 == 1);
    carved_ = true;
}

bool Triangulation::encroaches(const Pt& p, const Segment& s) const {
    const Pt& a = pts_[s.a];
    const Pt& b = pts_[s.b];
    return (a.x - p.x) * (b.x - p.x) + (a.y - p.y) * (b.y - p.y) < 0;
}

}  // namespace sextant
