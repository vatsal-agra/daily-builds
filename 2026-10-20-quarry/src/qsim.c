/* qsim — replay an allocation trace against several allocators and compare them.
 *
 *   qsim info    trace.qtr
 *   qsim compare trace.qtr [-a quarry,glibc,...] [--html report.html] [--no-verify]
 *   qsim list
 */
#define _GNU_SOURCE
#include "models.h"
#include "quarry.h"
#include "trace.h"

#include <errno.h>
#include <stdarg.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "qsim.h"

/* ------------------------------------------------------------------ utilities */

static uint64_t now_ns(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static void die(const char *fmt, ...) __attribute__((format(printf, 1, 2), noreturn));
static void die(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    fprintf(stderr, "qsim: "); vfprintf(stderr, fmt, ap); fprintf(stderr, "\n");
    va_end(ap);
    exit(1);
}

static void *xmalloc(size_t n) { void *p = malloc(n ? n : 1); if (!p) die("out of memory"); return p; }
static void *xcalloc(size_t a, size_t b) { void *p = calloc(a ? a : 1, b ? b : 1); if (!p) die("out of memory"); return p; }

static const char *human(double b, char *buf) {
    const char *u[] = { "B", "KiB", "MiB", "GiB", "TiB" };
    int i = 0;
    while (b >= 1024 && i < 4) { b /= 1024; i++; }
    if (i == 0) snprintf(buf, 32, "%.0f %s", b, u[i]); else snprintf(buf, 32, "%.1f %s", b, u[i]);
    return buf;
}

/* ------------------------------------------------------- pointer -> id table */

typedef struct { uint64_t *key; uint32_t *val; size_t cap, n; } PMap;   /* val = id + 1; key 0 = empty */

static void pm_init(PMap *m, size_t cap) {
    size_t c = 1024; while (c < cap * 2) c <<= 1;
    m->key = xcalloc(c, 8); m->val = xcalloc(c, 4); m->cap = c; m->n = 0;
}
static inline size_t pm_hash(uint64_t k, size_t cap) { k ^= k >> 33; k *= 0xff51afd7ed558ccdULL; k ^= k >> 33; return (size_t)k & (cap - 1); }
static uint32_t pm_get(PMap *m, uint64_t k) {
    for (size_t i = pm_hash(k, m->cap);; i = (i + 1) & (m->cap - 1)) {
        if (!m->key[i]) return 0;
        if (m->key[i] == k) return m->val[i];
    }
}
static void pm_put(PMap *m, uint64_t k, uint32_t v) {
    if ((m->n + 1) * 2 > m->cap) {
        PMap o = *m; pm_init(m, o.cap);
        for (size_t i = 0; i < o.cap; i++) if (o.key[i]) pm_put(m, o.key[i], o.val[i]);
        free(o.key); free(o.val);
    }
    for (size_t i = pm_hash(k, m->cap);; i = (i + 1) & (m->cap - 1)) {
        if (!m->key[i]) { m->key[i] = k; m->val[i] = v; m->n++; return; }
        if (m->key[i] == k) { m->val[i] = v; return; }
    }
}
static void pm_del(PMap *m, uint64_t k) {          /* linear probing with backward-shift deletion */
    size_t i = pm_hash(k, m->cap);
    while (m->key[i] && m->key[i] != k) i = (i + 1) & (m->cap - 1);
    if (!m->key[i]) return;
    size_t j = i;
    for (;;) {
        j = (j + 1) & (m->cap - 1);
        if (!m->key[j]) break;
        size_t h = pm_hash(m->key[j], m->cap);
        if ((j > i && (h <= i || h > j)) || (j < i && (h <= i && h > j))) {
            m->key[i] = m->key[j]; m->val[i] = m->val[j]; i = j;
        }
    }
    m->key[i] = 0; m->val[i] = 0; m->n--;
}

/* --------------------------------------------------------------- trace loading */

uint64_t g_max_size = 256ULL << 20, g_max_live = 8ULL << 30;

/* Turns raw records into events with dense block ids.  Anything that cannot be replayed faithfully
 * (frees of unknown pointers, failed allocations, absurd sizes) is counted, not guessed at. */
typedef struct {
    Trace *t;
    PMap pm;
    uint64_t *idsize, cur_live;
    uint32_t cap_ids;
} Loader;

static void ld_emit(Loader *l, int op, uint32_t id, uint64_t size, uint64_t align) {
    Ev e; memset(&e, 0, sizeof e);
    e.op = (uint8_t)op; e.id = id; e.size = size; e.align = align;
    l->t->ev[l->t->n++] = e;
}

static uint32_t ld_newid(Loader *l, uint64_t size) {
    Trace *t = l->t;
    if (t->ids + 2 >= l->cap_ids) { l->cap_ids *= 2; l->idsize = realloc(l->idsize, l->cap_ids * 8); if (!l->idsize) die("out of memory"); }
    uint32_t id = ++t->ids;
    l->idsize[id] = size; l->cur_live += size;
    return id;
}

/* A pointer that is still mapped when a new block claims its address was freed without a record. */
static void ld_reclaim(Loader *l, uint64_t ptr) {
    uint32_t v = pm_get(&l->pm, ptr);
    if (!v) return;
    uint32_t id = v - 1;
    ld_emit(l, EV_FREE, id, 0, 0);
    l->cur_live -= l->idsize[id];
    pm_del(&l->pm, ptr);
    l->t->implicit_frees++;
}

static int ld_too_big(Loader *l, uint64_t size, uint64_t freed) {
    return size > g_max_size || l->cur_live - freed + size > g_max_live;
}

Trace *trace_load(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) die("cannot open %s: %s", path, strerror(errno));
    struct stat st;
    if (fstat(fd, &st) < 0) die("cannot stat %s", path);
    if ((size_t)st.st_size < sizeof(qtr_header)) die("%s: too short to be a quarry trace", path);
    void *map = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (map == MAP_FAILED) die("cannot map %s", path);
    close(fd);
    const qtr_header *hd = map;
    if (memcmp(hd->magic, QTR_MAGIC, 8)) die("%s: not a quarry trace (bad magic)", path);
    if (hd->version != QTR_VERSION || hd->rec_size != sizeof(qtr_rec))
        die("%s: unsupported trace version %u / record size %u", path, hd->version, hd->rec_size);
    size_t body = (size_t)st.st_size - sizeof *hd, nrec = body / sizeof(qtr_rec);
    const qtr_rec *rec = (const qtr_rec *)(hd + 1);

    Trace *t = xcalloc(1, sizeof *t);
    t->truncated_bytes = body % sizeof(qtr_rec);
    t->ev = xmalloc((nrec * 2 + 1) * sizeof(Ev));     /* an event per record, plus implicit frees */
    Loader l; memset(&l, 0, sizeof l);
    l.t = t; l.cap_ids = 1024; l.idsize = xmalloc(l.cap_ids * 8);
    pm_init(&l.pm, nrec < 1000000 ? nrec : 1000000);
    uint32_t *tids = xmalloc(4); size_t ntid = 0, captid = 1;

    for (size_t i = 0; i < nrec; i++) {
        const qtr_rec *r = &rec[i];
        int seen = 0;
        for (size_t k = 0; k < ntid; k++) if (tids[k] == r->tid) { seen = 1; break; }
        if (!seen) {
            if (ntid == captid) { captid *= 2; tids = realloc(tids, captid * 4); if (!tids) die("out of memory"); }
            tids[ntid++] = r->tid;
        }
        switch (r->op) {
        case QTR_MALLOC: case QTR_CALLOC: case QTR_MEMALIGN: {
            if (!r->ptr) { t->failed_allocs++; break; }
            int bad_align = r->op == QTR_MEMALIGN && (r->aux == 0 || (r->aux & (r->aux - 1)) || r->aux > (1UL << 30));
            if (bad_align || ld_too_big(&l, r->size, 0)) { t->oversized++; break; }
            ld_reclaim(&l, r->ptr);
            uint32_t id = ld_newid(&l, r->size);
            ld_emit(&l, r->op == QTR_CALLOC ? EV_ZALLOC : r->op == QTR_MEMALIGN ? EV_ALIGNED : EV_ALLOC,
                    id, r->size, r->op == QTR_MEMALIGN ? r->aux : 0);
            pm_put(&l.pm, r->ptr, id + 1);
            break;
        }
        case QTR_FREE: {
            uint32_t v = pm_get(&l.pm, r->ptr);
            if (!v) { t->unknown_frees++; break; }
            ld_emit(&l, EV_FREE, v - 1, 0, 0);
            l.cur_live -= l.idsize[v - 1];
            pm_del(&l.pm, r->ptr);
            break;
        }
        case QTR_REALLOC: {
            if (!r->ptr) { t->failed_allocs++; break; }      /* a failed realloc leaves the block alone */
            uint32_t v = r->aux ? pm_get(&l.pm, r->aux) : 0;
            if (r->aux && !v) t->unknown_frees++;
            uint64_t old_size = v ? l.idsize[v - 1] : 0;
            if (ld_too_big(&l, r->size, old_size)) { t->oversized++; break; }
            if (!v) {                                         /* realloc(NULL, n), or a block we never saw */
                ld_reclaim(&l, r->ptr);
                uint32_t id = ld_newid(&l, r->size);
                ld_emit(&l, EV_ALLOC, id, r->size, 0);
                pm_put(&l.pm, r->ptr, id + 1);
            } else {
                uint32_t id = v - 1;
                pm_del(&l.pm, r->aux);
                if (r->ptr != r->aux) ld_reclaim(&l, r->ptr);
                l.cur_live = l.cur_live - old_size + r->size;
                l.idsize[id] = r->size;
                ld_emit(&l, EV_REALLOC, id, r->size, 0);
                pm_put(&l.pm, r->ptr, id + 1);
            }
            break;
        }
        default: t->bad_records++; break;
        }
    }
    t->records = nrec;
    t->threads = ntid;
    t->live_at_end = l.pm.n;
    free(l.idsize); free(tids); free(l.pm.key); free(l.pm.val);
    munmap(map, (size_t)st.st_size);
    return t;
}

void trace_free(Trace *t) { if (t) { free(t->ev); free(t); } }

/* ------------------------------------------------------------------- stats */

static int ilog2(uint64_t v) { return v ? 63 - __builtin_clzll(v) : 0; }

static int cmp_u64(const void *a, const void *b) { uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b; return x < y ? -1 : x > y; }

TraceProfile trace_profile(const Trace *t) {
    TraceProfile p; memset(&p, 0, sizeof p);
    uint64_t *size = xcalloc(t->ids + 1, 8), *born = xcalloc(t->ids + 1, 8);
    uint8_t *live = xcalloc(t->ids + 1, 1);
    uint64_t *life = xmalloc((t->n + 1) * 8); size_t nl = 0;
    uint64_t cur = 0;
    for (size_t i = 0; i < t->n; i++) {
        const Ev *e = &t->ev[i];
        switch (e->op) {
        case EV_ALLOC: case EV_ZALLOC: case EV_ALIGNED:
            p.allocs++; if (e->op == EV_ZALLOC) p.callocs++; if (e->op == EV_ALIGNED) p.aligned++;
            size[e->id] = e->size; born[e->id] = i; live[e->id] = 1; cur += e->size;
            p.size_hist[ilog2(e->size | 1)]++; p.total_bytes += e->size;
            if (e->size > p.max_size) p.max_size = e->size;
            break;
        case EV_FREE:
            p.frees++;
            if (live[e->id]) { cur -= size[e->id]; live[e->id] = 0; life[nl++] = i - born[e->id]; }
            break;
        case EV_REALLOC:
            p.reallocs++;
            if (live[e->id]) { cur -= size[e->id]; cur += e->size; size[e->id] = e->size; }
            break;
        }
        if (cur > p.peak_live) { p.peak_live = cur; p.peak_at = i; }
    }
    p.live_end = cur;
    if (nl) {
        qsort(life, nl, 8, cmp_u64);
        p.life_p50 = life[nl / 2]; p.life_p90 = life[nl * 9 / 10]; p.life_p99 = life[nl * 99 / 100];
    }
    p.freed = nl;
    free(size); free(born); free(live); free(life);
    return p;
}

static int cmd_info(const char *path) {
    Trace *t = trace_load(path);
    TraceProfile p = trace_profile(t);
    char b1[32], b2[32], b3[32];
    printf("trace %s\n", path);
    printf("  records        %zu (%zu threads%s)\n", t->records, t->threads, t->truncated_bytes ? ", last record truncated" : "");
    printf("  events         %zu: %llu allocs (%llu calloc, %llu aligned), %llu reallocs, %llu frees\n",
           t->n, (unsigned long long)p.allocs, (unsigned long long)p.callocs, (unsigned long long)p.aligned,
           (unsigned long long)p.reallocs, (unsigned long long)p.frees);
    if (t->unknown_frees || t->failed_allocs || t->implicit_frees || t->bad_records || t->oversized)
        printf("  anomalies      %zu frees of unknown pointers skipped, %zu failed allocations skipped, %zu address reuses,\n"
               "                 %zu unknown opcodes, %zu requests over the safety limits skipped (--max-size/--max-live)\n",
               t->unknown_frees, t->failed_allocs, t->implicit_frees, t->bad_records, t->oversized);
    printf("  requested      %s total, largest %s\n", human((double)p.total_bytes, b1), human((double)p.max_size, b2));
    printf("  peak live      %s (at event %zu), %s still live at the end (%zu blocks)\n",
           human((double)p.peak_live, b1), p.peak_at, human((double)p.live_end, b2), t->live_at_end);
    printf("  lifetime       median %llu events, p90 %llu, p99 %llu (%llu blocks freed)\n",
           (unsigned long long)p.life_p50, (unsigned long long)p.life_p90, (unsigned long long)p.life_p99, (unsigned long long)p.freed);
    printf("  request sizes  (power-of-two buckets)\n");
    uint64_t mx = 1;
    for (int i = 0; i < 64; i++) if (p.size_hist[i] > mx) mx = p.size_hist[i];
    for (int i = 0; i < 64; i++) {
        if (!p.size_hist[i]) continue;
        int bar = (int)(40.0 * (double)p.size_hist[i] / (double)mx);
        printf("    %8s %-8s %9llu %.*s\n", human((double)(1ULL << i), b1), i ? "" : "(0-1)", (unsigned long long)p.size_hist[i], bar, "########################################");
    }
    (void)b3;
    trace_free(t);
    return 0;
}

/* ------------------------------------------------------------------ replaying */

/* Every block carries a fingerprint in its first 16 and last 16 bytes (disjoint for any size). */
static inline size_t head_len(size_t n) { return n < 16 ? n : 16; }
static inline size_t tail_len(size_t n) { return n > 16 ? (n - 16 < 16 ? n - 16 : 16) : 0; }
static inline uint8_t pat_head(uint32_t id, size_t i) { return (uint8_t)(id * 131u + i * 7u + 1u); }
static inline uint8_t pat_tail(uint32_t id, size_t i) { return (uint8_t)(id * 17u + i * 3u + 5u); }

static inline void stamp(uint8_t *p, size_t n, uint32_t id) {
    for (size_t i = 0, k = head_len(n); i < k; i++) p[i] = pat_head(id, i);
    for (size_t i = 0, k = tail_len(n); i < k; i++) p[n - 1 - i] = pat_tail(id, i);
}
static inline int check_stamp(const uint8_t *p, size_t n, uint32_t id) {
    for (size_t i = 0, k = head_len(n); i < k; i++) if (p[i] != pat_head(id, i)) return 0;
    for (size_t i = 0, k = tail_len(n); i < k; i++) if (p[n - 1 - i] != pat_tail(id, i)) return 0;
    return 1;
}
static inline int check_prefix(const uint8_t *p, size_t n, uint32_t id) {
    for (size_t i = 0, k = head_len(n); i < k; i++) if (p[i] != pat_head(id, i)) return 0;
    return 1;
}
static int all_zero_run(const uint8_t *p, size_t n);
static int all_zero(const uint8_t *p, size_t n) {          /* huge blocks: first and last 4 MiB only */
    const size_t edge = 4UL << 20;
    if (n <= 2 * edge) return all_zero_run(p, n);
    return all_zero_run(p, edge) && all_zero_run(p + n - edge, edge);
}
static int all_zero_run(const uint8_t *p, size_t n) {
    size_t i = 0;
    for (; i + 8 <= n; i += 8) if (*(const uint64_t *)(p + i)) return 0;
    for (; i < n; i++) if (p[i]) return 0;
    return 1;
}

typedef struct { uint64_t p, n; } Blk;
static int cmp_blk(const void *a, const void *b) { const Blk *x = a, *y = b; return x->p < y->p ? -1 : x->p > y->p; }

static int overlap_check(const uint64_t *ptr, const uint64_t *sz, const uint8_t *live, uint32_t ids) {
    size_t m = 0;
    Blk *b = xmalloc((ids + 1) * sizeof *b);
    for (uint32_t i = 1; i <= ids; i++) if (live[i]) { b[m].p = ptr[i]; b[m].n = sz[i]; m++; }
    qsort(b, m, sizeof *b, cmp_blk);
    int bad = 0;
    for (size_t i = 1; i < m; i++) if (b[i - 1].p + b[i - 1].n > b[i].p) bad++;
    free(b);
    return bad;
}

static inline int lat_bucket(uint64_t ns) {           /* 4 buckets per octave */
    if (ns < 4) return (int)ns;
    int l = ilog2(ns);
    return (l << 2) | (int)((ns >> (l - 2)) & 3);
}
static uint64_t lat_value(int b) {
    if (b < 4) return (uint64_t)b;
    int l = b >> 2; uint64_t base = 1ULL << l;
    return base + (base >> 2) * (uint64_t)(b & 3);
}
static uint64_t lat_quantile(const uint64_t *h, double q) {
    uint64_t tot = 0; for (int i = 0; i < LAT_BUCKETS; i++) tot += h[i];
    if (!tot) return 0;
    uint64_t want = (uint64_t)ceil(q * (double)tot), acc = 0;
    for (int i = 0; i < LAT_BUCKETS; i++) { acc += h[i]; if (acc >= want) return lat_value(i); }
    return lat_value(LAT_BUCKETS - 1);
}

/* Replays the trace against one model inside the current process and fills r. */
static void replay(const Model *m, const Trace *t, int mode, RunResult *r, FrameSink *fs) {
    memset(r, 0, sizeof *r);
    uint32_t ids = t->ids;
    uint64_t *ptr = xcalloc(ids + 1, 8), *sz = xcalloc(ids + 1, 8);
    uint8_t *live = xcalloc(ids + 1, 1);
    int verify = mode == MODE_MEASURE;
    uint64_t live_bytes = 0, peak_live = 0, peak_fp = 0;
    size_t stride = t->n / 20000 + 1;
    size_t nsamp = SERIES_POINTS, next_sample = 0;
    uint64_t t_total = 0;
    uint64_t *lat_a = verify ? xcalloc(LAT_BUCKETS, 8) : NULL, *lat_f = verify ? xcalloc(LAT_BUCKETS, 8) : NULL;
    size_t overlap_every = t->n / 12 + 1;

    if (m->init() < 0) { r->status = RUN_INIT_FAILED; return; }
    uint64_t t0 = now_ns();
    for (size_t i = 0; i < t->n; i++) {
        const Ev *e = &t->ev[i];
        uint64_t c0 = 0;
        switch (e->op) {
        case EV_ALLOC: case EV_ZALLOC: case EV_ALIGNED: {
            if (verify) c0 = now_ns();
            void *p = e->op == EV_ALIGNED ? m->aligned(e->align, e->size) : m->alloc(e->size, e->op == EV_ZALLOC);
            if (verify) lat_a[lat_bucket(now_ns() - c0)]++;
            if (!p) { r->failed++; break; }
            ptr[e->id] = (uint64_t)(uintptr_t)p; sz[e->id] = e->size; live[e->id] = 1;
            live_bytes += e->size;
            if (verify) {
                if (e->op == EV_ALIGNED && ((uintptr_t)p & (e->align - 1))) r->misaligned++;
                if (e->op != EV_ALIGNED && ((uintptr_t)p & 7)) r->misaligned++;
                if (e->op == EV_ZALLOC && !all_zero(p, e->size)) r->not_zeroed++;
                if (e->size) stamp(p, e->size, e->id);
            }
            break;
        }
        case EV_FREE: {
            if (!live[e->id]) break;
            void *p = (void *)(uintptr_t)ptr[e->id];
            if (verify) {
                if (sz[e->id] && !check_stamp(p, sz[e->id], e->id)) r->corrupt++;
                c0 = now_ns();
            }
            m->release(p);
            if (verify) lat_f[lat_bucket(now_ns() - c0)]++;
            live_bytes -= sz[e->id]; live[e->id] = 0;
            break;
        }
        case EV_REALLOC: {
            void *old = (void *)(uintptr_t)ptr[e->id];
            if (!live[e->id]) break;
            size_t osz = sz[e->id];
            if (verify && osz && !check_stamp(old, osz, e->id)) r->corrupt++;
            if (verify) c0 = now_ns();
            void *p = m->resize(old, osz, e->size);
            if (verify) lat_a[lat_bucket(now_ns() - c0)]++;
            if (!p) { r->failed++; break; }
            if (verify) {
                size_t keep = osz < e->size ? osz : e->size;
                if (keep && !check_prefix(p, keep < 16 ? keep : 16, e->id)) r->corrupt++;
                if (((uintptr_t)p & 7)) r->misaligned++;
                if (e->size) stamp(p, e->size, e->id);
            }
            live_bytes = live_bytes - osz + e->size;
            ptr[e->id] = (uint64_t)(uintptr_t)p; sz[e->id] = e->size; r->reallocs_moved += p != old;
            break;
        }
        }
        if (live_bytes > peak_live) peak_live = live_bytes;
        if (verify) {
            if (i % stride == 0) { uint64_t fp = m->footprint(); if (fp > peak_fp) peak_fp = fp; }
            if (i >= next_sample && r->nseries < nsamp) {
                uint64_t fp = m->footprint(); if (fp > peak_fp) peak_fp = fp;
                r->series[r->nseries].ev = i; r->series[r->nseries].live = live_bytes; r->series[r->nseries].fp = fp;
                r->nseries++;
                next_sample = (uint64_t)(r->nseries) * t->n / nsamp;
                if (fs && fs->snap) fs->snap(fs, i, live_bytes, fp);
            }
            if (i % overlap_every == overlap_every - 1) r->overlaps += (uint64_t)overlap_check(ptr, sz, live, ids);
        }
    }
    t_total = now_ns() - t0;
    r->ns_total = t_total;
    r->peak_live = peak_live;
    r->footprint_end = m->footprint();
    if (r->footprint_end > peak_fp) peak_fp = r->footprint_end;
    if (m->peak) { uint64_t pk = m->peak(); if (pk > peak_fp) peak_fp = pk; }
    r->peak_fp = peak_fp;
    if (verify) {
        r->overlaps += (uint64_t)overlap_check(ptr, sz, live, ids);
        r->lat_alloc_p50 = lat_quantile(lat_a, 0.50); r->lat_alloc_p99 = lat_quantile(lat_a, 0.99); r->lat_alloc_max = lat_quantile(lat_a, 1.0);
        r->lat_free_p50 = lat_quantile(lat_f, 0.50); r->lat_free_p99 = lat_quantile(lat_f, 0.99); r->lat_free_max = lat_quantile(lat_f, 1.0);
    }
    /* release whatever is still live, then see how much memory the allocator keeps */
    for (uint32_t i = 1; i <= ids; i++) if (live[i]) {
        void *p = (void *)(uintptr_t)ptr[i];
        if (verify && sz[i] && !check_stamp(p, sz[i], i)) r->corrupt++;
        m->release(p);
    }
    if (m->trim) m->trim();
    r->footprint_after_free = m->footprint();
    if (!strcmp(m->name, "quarry")) r->top_pages = q_top_pages();
    r->status = RUN_OK;
    r->events = t->n;
    free(ptr); free(sz); free(live); free(lat_a); free(lat_f);
    m->fini();
}

/* Runs one pass in a forked child so every pass starts from a pristine allocator and a crash is
 * contained.  The result (and any heap-map frames) comes back through a pipe. */
static int run_isolated(const Model *m, const Trace *t, int mode, RunResult *r, MapData *md) {
    int fds[2];
    if (pipe(fds) < 0) die("pipe: %s", strerror(errno));
    fflush(NULL);
    pid_t pid = fork();
    if (pid < 0) die("fork: %s", strerror(errno));
    if (pid == 0) {
        close(fds[0]);
        RunResult res;
        FrameSink fs; memset(&fs, 0, sizeof fs);
        int want_map = md && mode == MODE_MEASURE && !strcmp(m->name, "quarry");
        if (want_map) map_sink_init(&fs, md, t->n);
        replay(m, t, mode, &res, want_map ? &fs : NULL);
        FILE *f = fdopen(fds[1], "wb");
        fwrite(&res, sizeof res, 1, f);
        if (want_map) map_sink_write(&fs, f);
        fclose(f);
        _exit(0);
    }
    close(fds[1]);
    FILE *f = fdopen(fds[0], "rb");
    memset(r, 0, sizeof *r);
    size_t got = fread(r, 1, sizeof *r, f);
    if (got == sizeof *r && r->status == RUN_OK && md && mode == MODE_MEASURE && !strcmp(m->name, "quarry")) map_sink_read(md, f);
    fclose(f);
    int st = 0;
    waitpid(pid, &st, 0);
    if (got != sizeof *r) {
        r->status = RUN_CRASHED;
        if (WIFSIGNALED(st)) r->signal = WTERMSIG(st);
        return -1;
    }
    return 0;
}

/* --------------------------------------------------------------------- compare */

static int cmd_compare(const char *path, const char *which, const char *html, int verify, int reps) {
    Trace *t = trace_load(path);
    if (t->n == 0) die("%s: the trace contains no usable events", path);
    TraceProfile prof = trace_profile(t);

    const Model *sel[16]; int ns = 0;
    char *list = strdup(which ? which : "quarry,glibc,firstfit,buddy,bump");
    for (char *tok = strtok(list, ","); tok; tok = strtok(NULL, ",")) {
        const Model *m = model_by_name(tok);
        if (!m) die("unknown allocator '%s' (try: qsim list)", tok);
        if (ns < 16) sel[ns++] = m;
    }
    free(list);
    if (!ns) die("no allocators selected");

    char b1[32], b2[32];
    printf("replaying %s: %zu events, peak live %s, %zu threads recorded\n\n",
           path, t->n, human((double)prof.peak_live, b1), t->threads);
    Row *rows = xcalloc((size_t)ns, sizeof *rows);
    MapData md; memset(&md, 0, sizeof md);
    for (int i = 0; i < ns; i++) {
        rows[i].m = sel[i];
        uint64_t best = (uint64_t)-1;
        for (int k = 0; k < reps; k++) {                       /* best of N for the timing pass */
            RunResult r;
            if (run_isolated(sel[i], t, MODE_TIME, &r, NULL) < 0 || r.status != RUN_OK) { rows[i].time = r; rows[i].crashed = 1; break; }
            if (r.ns_total < best) { best = r.ns_total; rows[i].time = r; }
        }
        if (!rows[i].crashed) {
            md.top_hint = rows[i].time.top_pages;
            if (verify) {
                if (run_isolated(sel[i], t, MODE_MEASURE, &rows[i].meas, &md) < 0 || rows[i].meas.status != RUN_OK) rows[i].crashed = 1;
            } else rows[i].meas = rows[i].time;
        }
    }

    printf("%-9s %11s %11s %9s %11s %9s %8s %8s %8s  %s\n", "allocator", "peak mem", "end mem", "overhead", "after free", "ns/event",
           "alloc p50", "alloc p99", "free p99", verify ? "integrity" : "");
    for (int i = 0; i < ns; i++) {
        Row *r = &rows[i];
        if (r->crashed) {
            const RunResult *bad = r->time.status != RUN_OK ? &r->time : &r->meas;
            if (bad->status == RUN_INIT_FAILED) printf("%-9s FAILED: could not initialise\n", r->m->name);
            else if (bad->signal) printf("%-9s FAILED: crashed with signal %d (%s)\n", r->m->name, bad->signal, strsignal(bad->signal));
            else printf("%-9s FAILED: the replay process died\n", r->m->name);
            continue;
        }
        const RunResult *m = &r->meas;
        double ov = prof.peak_live ? (double)m->peak_fp / (double)prof.peak_live : 0;
        char ok[96] = "";
        if (verify) {
            uint64_t bad = m->corrupt + m->overlaps + m->misaligned + m->not_zeroed;
            if (bad) snprintf(ok, sizeof ok, "BROKEN: %llu corrupt, %llu overlaps, %llu misaligned, %llu not zeroed",
                              (unsigned long long)m->corrupt, (unsigned long long)m->overlaps, (unsigned long long)m->misaligned, (unsigned long long)m->not_zeroed);
            else snprintf(ok, sizeof ok, "ok%s", m->failed ? " (some allocations failed)" : "");
        }
        char b3[32];
        printf("%-9s %11s %11s %8.2fx %11s %9.1f %7lluns %7lluns %7lluns  %s\n", r->m->name,
               human((double)m->peak_fp, b1), human((double)m->footprint_end, b2), ov,
               human((double)m->footprint_after_free, b3),
               (double)r->time.ns_total / (double)t->n,
               (unsigned long long)m->lat_alloc_p50, (unsigned long long)m->lat_alloc_p99, (unsigned long long)m->lat_free_p99, ok);
    }
    printf("\n  overhead = peak memory held from the OS / peak live bytes requested (1.00x is perfect)\n");
    printf("  after free = memory still held after every block is freed and the allocator is asked to trim\n");
    printf("  ns/event comes from an unverified run (best of %d); percentiles from a verified run that times each call\n", reps);

    int rc = 0;
    for (int i = 0; i < ns; i++) {
        if (rows[i].crashed) rc = 1;
        else if (verify && rows[i].meas.corrupt + rows[i].meas.overlaps + rows[i].meas.misaligned + rows[i].meas.not_zeroed) rc = 1;
    }
    if (html) {
        if (!verify) die("--html needs the verified pass; drop --no-verify");
        if (report_write(html, path, t, &prof, rows, ns, &md) < 0) die("cannot write %s: %s", html, strerror(errno));
        printf("\nreport written to %s\n", html);
    }
    free(rows); free(md.frames); trace_free(t);
    return rc;
}

static int cmd_list(void) {
    for (int i = 0; MODELS[i]; i++) printf("  %-9s %s\n", MODELS[i]->name, MODELS[i]->desc);
    return 0;
}

static void usage(void) {
    fprintf(stderr, "usage: qsim info <trace>\n"
                    "       qsim compare <trace> [-a name,name,...] [--html report.html] [--no-verify] [--reps N]\n"
                    "                            [--max-size MiB] [--max-live MiB]   (skip absurd requests; default 256 / 8192)\n"
                    "       qsim list\n");
    exit(2);
}

int main(int argc, char **argv) {
    if (argc < 2) usage();
    if (!strcmp(argv[1], "list")) return cmd_list();
    if (!strcmp(argv[1], "info") && argc == 3) return cmd_info(argv[2]);
    if (!strcmp(argv[1], "compare") && argc >= 3) {
        const char *which = NULL, *html = NULL; int verify = 1, reps = 3;
        for (int i = 3; i < argc; i++) {
            if (!strcmp(argv[i], "-a") && i + 1 < argc) which = argv[++i];
            else if (!strcmp(argv[i], "--html") && i + 1 < argc) html = argv[++i];
            else if (!strcmp(argv[i], "--no-verify")) verify = 0;
            else if (!strcmp(argv[i], "--max-size") && i + 1 < argc) g_max_size = strtoull(argv[++i], NULL, 10) << 20;
            else if (!strcmp(argv[i], "--max-live") && i + 1 < argc) g_max_live = strtoull(argv[++i], NULL, 10) << 20;
            else if (!strcmp(argv[i], "--reps") && i + 1 < argc) { reps = atoi(argv[++i]); if (reps < 1) reps = 1; if (reps > 20) reps = 20; }
            else usage();
        }
        return cmd_compare(argv[2], which, html, verify, reps);
    }
    usage();
}
