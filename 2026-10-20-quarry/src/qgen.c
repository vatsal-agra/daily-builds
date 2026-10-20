/* qgen — synthetic allocation-workload generator.  Writes a trace in the same format libquarry.so
 * records, so qsim can replay it.  Usage: qgen <workload> [-n events] [-s seed] -o file.qtr */
#define _GNU_SOURCE
#include "trace.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --------------------------------------------------------------------- state */

static uint64_t rng_s = 0x9E3779B97F4A7C15ULL;
static uint64_t rnd(void) { rng_s ^= rng_s << 13; rng_s ^= rng_s >> 7; rng_s ^= rng_s << 17; return rng_s; }
static double urand(void) { return (double)(rnd() >> 11) / 9007199254740992.0; }
static size_t below(size_t n) { return n ? (size_t)(rnd() % n) : 0; }
static double gauss(void) { return sqrt(-2 * log(urand() + 1e-300)) * cos(6.283185307179586 * urand()); }
static size_t lognorm(double median, double sigma, size_t lo, size_t hi) {
    double v = median * exp(sigma * gauss());
    return v < lo ? lo : v > hi ? hi : (size_t)v;
}

static FILE *out;
static uint64_t n_events, limit, next_addr = 0x100000, clock_ns;

static int full(void) { return n_events >= limit; }

static void emit(int op, uint64_t ptr, uint64_t size, uint64_t aux) {
    qtr_rec r; memset(&r, 0, sizeof r);
    r.op = (uint8_t)op; r.tid = 1; r.ts_ns = (clock_ns += 400 + rnd() % 600);
    r.ptr = ptr; r.size = size; r.aux = aux;
    if (fwrite(&r, sizeof r, 1, out) != 1) { perror("write"); exit(1); }
    n_events++;
}
static uint64_t fresh(size_t n) { uint64_t a = next_addr; next_addr += ((n + 63) & ~63UL) + 64; return a; }

static uint64_t g_malloc(size_t n)  { uint64_t p = fresh(n); emit(QTR_MALLOC, p, n, 0); return p; }
static uint64_t g_calloc(size_t n)  { uint64_t p = fresh(n); emit(QTR_CALLOC, p, n, 0); return p; }
static void     g_free(uint64_t p)  { emit(QTR_FREE, p, 0, 0); }
static uint64_t g_realloc(uint64_t old, size_t n) { uint64_t p = fresh(n); emit(QTR_REALLOC, p, n, old); return p; }
static uint64_t g_aligned(size_t al, size_t n) { uint64_t p = fresh(n + al); p = (p + al - 1) & ~(uint64_t)(al - 1); emit(QTR_MEMALIGN, p, n, al); return p; }

typedef struct { uint64_t *v; size_t n, cap; } Vec;
static void vpush(Vec *a, uint64_t x) { if (a->n == a->cap) { a->cap = a->cap ? a->cap * 2 : 64; a->v = realloc(a->v, a->cap * 8); } a->v[a->n++] = x; }
static uint64_t vtake(Vec *a, size_t i) { uint64_t x = a->v[i]; a->v[i] = a->v[--a->n]; return x; }
static void drain_random(Vec *a) { while (a->n) g_free(vtake(a, below(a->n))); }

/* ----------------------------------------------------------------- workloads */

/* A server: every request allocates a burst of short-lived objects with log-normal sizes plus a
 * transient I/O buffer; a few results are promoted into a bounded long-lived cache. */
static void w_web(uint64_t until) {
    Vec cache = {0}, req = {0};
    size_t cache_max = 3000;
    while (n_events < until && !full()) {
        size_t k = 20 + below(100);
        for (size_t i = 0; i < k; i++) {
            size_t n = lognorm(72, 1.1, 8, 20000);
            uint64_t p = (rnd() % 9 == 0) ? g_calloc(n) : g_malloc(n);
            if (rnd() % 50 == 0) {
                if (cache.n >= cache_max) g_free(vtake(&cache, below(cache.n)));
                vpush(&cache, p);
            } else vpush(&req, p);
        }
        if (rnd() % 4 == 0) vpush(&req, g_malloc(4096 + below(60000)));
        if (req.n > 4 && rnd() % 3 == 0) {                   /* a string builder that grows */
            size_t i = below(req.n), n = 32;
            uint64_t p = g_malloc(n);
            for (int j = 0; j < 6; j++) { n *= 2; p = g_realloc(p, n); }
            vpush(&req, p); (void)i;
        }
        drain_random(&req);
    }
    free(req.v);
    drain_random(&cache); free(cache.v);
}

/* Binary trees of 48-byte nodes built, torn down in different orders, with a few kept alive. */
static void tree_build(Vec *nodes, int depth) {
    size_t total = (1u << depth) - 1;
    for (size_t i = 0; i < total && !full(); i++) vpush(nodes, g_malloc(48));
}
static void w_tree(uint64_t until) {
    Vec keep[3] = {{0}}; int slot = 0;
    while (n_events < until && !full()) {
        Vec t = {0};
        int depth = 8 + (int)below(8);
        tree_build(&t, depth);
        if (rnd() & 1) { for (size_t i = 0; i < t.n; i++) g_free(t.v[i]); t.n = 0; }  /* sequential */
        else drain_random(&t);                                                      /* scattered */
        if (t.n) { drain_random(&keep[slot]); keep[slot] = t; slot = (slot + 1) % 3; } else free(t.v);
        if (rnd() % 8 == 0) { Vec b = {0}; for (int i = 0; i < 40; i++) vpush(&b, g_malloc(1000 + below(9000))); drain_random(&b); free(b.v); }
    }
    for (int i = 0; i < 3; i++) { drain_random(&keep[i]); free(keep[i].v); }
}

/* A FIFO whose window breathes: steady state, then a burst far larger than steady state, then drain. */
static void w_queue(uint64_t until) {
    Vec q = {0}; size_t head = 0;
    uint64_t start = n_events, span = until > start ? until - start : 1;
    while (n_events < until && !full()) {
        double phase = (double)(n_events - start) / (double)span;
        size_t target = 4000 + (size_t)(60000.0 * exp(-pow((phase - 0.5) / 0.12, 2)));
        size_t live = q.n - head;
        if (live < target) vpush(&q, g_malloc(lognorm(300, 0.9, 16, 30000)));
        else { g_free(q.v[head++]); }
        if (head > 100000 && head * 2 > q.n) { memmove(q.v, q.v + head, (q.n - head) * 8); q.n -= head; head = 0; }
    }
    while (head < q.n) g_free(q.v[head++]);
    free(q.v);
}

/* Fragmentation adversary: fill with small blocks, free every other one, then ask for blocks that
 * are slightly too big for the holes; repeat with growing sizes. */
static void w_frag(uint64_t until) {
    size_t sizes[] = { 96, 144, 224, 336, 520, 800, 1200, 1800, 2800, 4500 };
    Vec all = {0}, keep = {0};
    uint64_t per_round = (until > n_events ? until - n_events : 1) / 11;
    for (int r = 0; r < 10 && !full(); r++) {
        uint64_t stop = n_events + per_round;
        Vec cur = {0};
        while (n_events < stop && !full()) vpush(&cur, g_malloc(sizes[r] + below(16)));
        for (size_t i = 0; i < cur.n; i++) { if (i & 1) g_free(cur.v[i]); else vpush(&keep, cur.v[i]); }
        free(cur.v);
    }
    (void)all;
    drain_random(&keep);
    free(keep.v); free(all.v);
}

/* Many dynamic arrays that grow by realloc (doubling and 1.5x) and are replaced when they die. */
static void w_vector(uint64_t until) {
    enum { NV = 1500 };
    static struct { uint64_t p; size_t len, cap, elem; double growth; } v[NV];
    while (n_events < until && !full()) {
        size_t i = below(NV);
        if (!v[i].p) {
            v[i].elem = 8 << below(4); v[i].cap = 4; v[i].len = 0; v[i].growth = (rnd() & 1) ? 2.0 : 1.5;
            v[i].p = g_malloc(v[i].cap * v[i].elem);
        }
        size_t push = 1 + below(40);
        v[i].len += push;
        while (v[i].len > v[i].cap) {
            size_t nc = (size_t)(v[i].cap * v[i].growth) + 1;
            v[i].cap = nc;
            v[i].p = g_realloc(v[i].p, v[i].cap * v[i].elem);
        }
        if (rnd() % 60 == 0) {                              /* dies, sometimes after shrinking */
            if (rnd() & 1) v[i].p = g_realloc(v[i].p, v[i].elem * (v[i].len / 2 + 1));
            g_free(v[i].p); v[i].p = 0;
        }
    }
    for (int i = 0; i < NV; i++) if (v[i].p) { g_free(v[i].p); v[i].p = 0; }
}

/* Phase changes: each phase is a different workload, and everything is released in between. */
static void w_mixed(uint64_t until) {
    uint64_t base = n_events, third = (until - base) / 5;
    w_web(base + third);
    w_tree(base + 2 * third);
    w_queue(base + 3 * third);
    w_vector(base + 4 * third);
    Vec a = {0};                                            /* a sprinkling of aligned allocations */
    for (int i = 0; i < 2000 && !full(); i++) vpush(&a, g_aligned((size_t)16 << below(9), 1 + below(5000)));
    drain_random(&a); free(a.v);
    w_web(until);
}

static const struct { const char *name, *desc; void (*fn)(uint64_t); } WORK[] = {
    { "web",    "request bursts, log-normal sizes, bounded cache, string-builder reallocs", w_web },
    { "tree",   "binary-tree node churn, sequential vs scattered teardown", w_tree },
    { "queue",  "FIFO whose window swells 15x mid-run and drains again", w_queue },
    { "frag",   "fragmentation adversary: free every other block, then ask for bigger ones", w_frag },
    { "vector", "1500 dynamic arrays growing by realloc, shrinking and dying", w_vector },
    { "mixed",  "all of the above in phases, plus aligned allocations", w_mixed },
    { NULL, NULL, NULL }
};

static void usage(void) {
    fprintf(stderr, "usage: qgen <workload> [-n events] [-s seed] -o out.qtr\nworkloads:\n");
    for (int i = 0; WORK[i].name; i++) fprintf(stderr, "  %-7s %s\n", WORK[i].name, WORK[i].desc);
    exit(2);
}

int main(int argc, char **argv) {
    if (argc < 2) usage();
    const char *name = argv[1], *path = NULL;
    uint64_t n = 300000, seed = 1;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "-n") && i + 1 < argc) n = strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "-s") && i + 1 < argc) seed = strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "-o") && i + 1 < argc) path = argv[++i];
        else usage();
    }
    int idx = -1;
    for (int i = 0; WORK[i].name; i++) if (!strcmp(WORK[i].name, name)) idx = i;
    if (idx < 0 || !path) usage();
    if (n < 100) { fprintf(stderr, "qgen: -n must be at least 100\n"); return 2; }
    rng_s ^= seed * 0xD1B54A32D192ED03ULL; for (int i = 0; i < 8; i++) rnd();
    out = fopen(path, "wb");
    if (!out) { perror(path); return 1; }
    qtr_header hd; memset(&hd, 0, sizeof hd);
    memcpy(hd.magic, QTR_MAGIC, 8); hd.version = QTR_VERSION; hd.rec_size = sizeof(qtr_rec);
    fwrite(&hd, sizeof hd, 1, out);
    limit = n + n / 4 + 100000;                       /* hard stop; workloads end themselves at n */
    WORK[idx].fn(n);
    if (fclose(out)) { perror("close"); return 1; }
    fprintf(stderr, "qgen: %s: %llu events -> %s\n", name, (unsigned long long)n_events, path);
    return 0;
}
