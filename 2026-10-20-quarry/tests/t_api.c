/* API-level tests of the allocator core, linked directly (no interposition). */
#define _GNU_SOURCE
#include "../src/quarry.h"
#include "check.h"
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static uint64_t rng = 88172645463325252ULL;
static uint64_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; }

static size_t rss_bytes(void) {
    long a = 0, b = 0;
    FILE *f = fopen("/proc/self/statm", "r");
    if (!f) return 0;
    if (fscanf(f, "%ld %ld", &a, &b) != 2) b = 0;
    fclose(f);
    return (size_t)b * 4096;
}

static void fill(void *p, size_t n, uint8_t seed) { for (size_t i = 0; i < n; i++) ((uint8_t *)p)[i] = (uint8_t)(seed + i * 7); }
static int verify(const void *p, size_t n, uint8_t seed) {
    for (size_t i = 0; i < n; i++) if (((const uint8_t *)p)[i] != (uint8_t)(seed + i * 7)) return 0;
    return 1;
}

static void test_basic(void) {
    void *p = q_malloc(0);
    CHECK(p != NULL);
    CHECK(((uintptr_t)p & 15) == 0);
    q_free(p);
    q_free(NULL);
    for (size_t n = 1; n <= 40000; n += (n < 2000 ? 1 : 97)) {
        void *a = q_malloc(n);
        CHECK(a != NULL);
        CHECK(((uintptr_t)a & 15) == 0);
        CHECK(q_usable_size(a) >= n);
        CHECK(q_owns(a));
        if (n > 32768) CHECK(((uintptr_t)a & 4095) == 0);
        memset(a, 0xAB, n);                      /* whole requested range is writable */
        q_free(a);
    }
    int x;
    CHECK(!q_owns(&x));
    CHECK(q_usable_size(&x) == 0);
    CHECK(q_free_checked(&x) == Q_FREE_FOREIGN);
}

static void test_classes(void) {
    size_t prev = 0;
    for (int c = 0; c < Q_NCLASS; c++) {
        size_t s = q_class_size(c);
        CHECK(s > prev);
        CHECK(s % 16 == 0);
        prev = s;
        void *a = q_malloc(s);
        CHECK(q_usable_size(a) == s);            /* exact class size fits its own class */
        void *b = q_malloc(s - 15);               /* one granule below also lands in this class */
        CHECK(q_usable_size(b) == s || s <= 128);
        q_free(a); q_free(b);
    }
    CHECK(prev == Q_MAX_SMALL);
    void *a = q_malloc(17), *b = q_malloc(1000);
    CHECK(q_usable_size(a) == 32);
    CHECK(q_usable_size(b) == 1024);
    q_free(a); q_free(b);
}

static void test_calloc(void) {
    for (size_t n = 1; n < 200000; n = n * 3 + 1) {
        uint8_t *p = q_calloc(n, 1);
        int zero = 1;
        for (size_t i = 0; i < n; i++) if (p[i]) { zero = 0; break; }
        CHECK(zero);
        memset(p, 0xFF, n);
        q_free(p);
        p = q_calloc(1, n);                      /* recycled memory must be re-zeroed */
        zero = 1;
        for (size_t i = 0; i < n; i++) if (p[i]) { zero = 0; break; }
        CHECK(zero);
        q_free(p);
    }
    errno = 0;
    CHECK(q_calloc(SIZE_MAX / 2, 3) == NULL);
    CHECK(errno == ENOMEM);
    void *c0 = q_calloc(0, 5);
    CHECK(c0 != NULL);
    q_free(c0);
    errno = 0;
    CHECK(q_malloc(SIZE_MAX) == NULL && errno == ENOMEM);
    CHECK(q_malloc(SIZE_MAX - 5000) == NULL);
}

static void test_realloc(void) {
    void *r0 = q_realloc(NULL, 100);
    CHECK(r0 != NULL);
    q_free(r0);
    for (size_t from = 1; from < 100000; from = from * 2 + 3) {
        for (size_t to = 1; to < 100000; to = to * 2 + 5) {
            uint8_t *p = q_malloc(from);
            fill(p, from, 3);
            uint8_t *q = q_realloc(p, to);
            CHECK(q != NULL);
            size_t keep = from < to ? from : to;
            CHECK(verify(q, keep, 3));
            CHECK(q_usable_size(q) >= to);
            q_free(q);
        }
    }
    /* realloc(p, 0) behaves as a valid minimal allocation, never a use-after-free */
    void *p = q_malloc(10);
    void *q = q_realloc(p, 0);
    CHECK(q != NULL);
    q_free(q);
}

static void test_large_inplace(void) {
    /* A large block that is the last one on the heap grows in place, and shrinks in place. */
    size_t sz = 1 << 20;
    q_free(q_malloc(64 << 20));                  /* leave one big free span to carve from */
    uint8_t *p = q_malloc(sz);
    fill(p, sz, 9);
    uint8_t *g = q_realloc(p, sz * 4);
    CHECK(g == p);
    CHECK(verify(g, sz, 9));
    CHECK(q_usable_size(g) >= sz * 4);
    fill(g, sz * 4, 9);
    uint8_t *s = q_realloc(g, sz / 2);
    CHECK(s == g);
    CHECK(q_usable_size(s) >= sz / 2 && q_usable_size(s) < sz);
    uint8_t *tail = q_malloc(sz);                /* the freed tail is reusable right away */
    CHECK(tail != NULL);
    memset(tail, 2, sz);
    CHECK(verify(s, sz / 2, 9));
    /* growing again re-absorbs the neighbouring free pages without moving */
    q_free(tail);
    uint8_t *again = q_realloc(s, sz);
    CHECK(again == s && verify(again, sz / 2, 9));
    q_free(again);
    /* large -> small shrink moves into a slab and keeps data */
    uint8_t *b = q_malloc(100000);
    fill(b, 100000, 4);
    uint8_t *sm = q_realloc(b, 300);
    CHECK(verify(sm, 300, 4));
    CHECK(q_usable_size(sm) < Q_PAGE_SIZE);
    q_free(sm);
}

static void test_memalign(void) {
    for (size_t a = 16; a <= (1 << 22); a <<= 1) {
        for (size_t n = 1; n < 70000; n = n * 5 + 3) {
            void *p = q_memalign(a, n);
            CHECK(p != NULL);
            CHECK(((uintptr_t)p & (a - 1)) == 0);
            CHECK(q_usable_size(p) >= n);
            memset(p, 0x5A, n);
            CHECK(q_free_checked(p) == Q_FREE_OK);
        }
    }
    void *p;
    CHECK(q_posix_memalign(&p, 3, 10) == EINVAL);
    CHECK(q_posix_memalign(&p, 64, 10) == 0 && ((uintptr_t)p & 63) == 0);
    q_free(p);
    CHECK(q_posix_memalign(&p, 4, 10) == EINVAL);  /* smaller than a pointer */
}

static void test_checked_free(void) {
    char *a = q_malloc(64);
    CHECK(q_free_checked(a + 8) == Q_FREE_BADPTR);
    CHECK(q_free_checked(a) == Q_FREE_OK);
    CHECK(q_free_checked(a) == Q_FREE_DOUBLE);   /* sits in the thread cache */
    q_thread_flush();
    void *big = q_malloc(1 << 20);
    CHECK(q_free_checked((char *)big + 4096) == Q_FREE_BADPTR);
    CHECK(q_free_checked(big) == Q_FREE_OK);
    CHECK(q_free_checked(big) == Q_FREE_DOUBLE);
}

typedef struct { uint8_t *p; size_t n; uint8_t seed; } Slot;

static int cmp_ptr(const void *a, const void *b) {
    const Slot *x = a, *y = b;
    return x->p < y->p ? -1 : x->p > y->p;
}

static void test_stress(void) {
    enum { N = 4000 };
    static Slot slots[N];
    for (long iter = 0; iter < 400000; iter++) {
        Slot *s = &slots[rnd() % N];
        if (s->p) {
            CHECK(verify(s->p, s->n < 64 ? s->n : 64, s->seed));
            CHECK(verify(s->p + s->n - (s->n < 64 ? s->n : 64), s->n < 64 ? s->n : 64, (uint8_t)(s->seed + (s->n - (s->n < 64 ? s->n : 64)) * 7)));
            if (rnd() % 3 == 0) {                 /* realloc */
                size_t nn = (rnd() % 8 == 0) ? rnd() % 200000 : rnd() % 3000;
                size_t keep = nn < s->n ? nn : s->n;
                uint8_t *q = q_realloc(s->p, nn);
                CHECK(q != NULL);
                CHECK(verify(q, keep < 64 ? keep : 64, s->seed));
                s->p = q; s->n = nn; s->seed = (uint8_t)rnd();
                fill(s->p, nn < 64 ? nn : 64, s->seed);
                if (nn >= 64) { size_t off = nn - 64; for (size_t i = 0; i < 64; i++) s->p[off + i] = (uint8_t)(s->seed + (off + i) * 7); }
                if (nn == 0) { q_free(s->p); s->p = NULL; }
            } else { q_free(s->p); s->p = NULL; }
        } else {
            size_t n = (rnd() % 20 == 0) ? (rnd() % 300000) : (rnd() % 4 == 0 ? rnd() % 20000 : rnd() % 300);
            if (n == 0) n = 1;
            s->p = (rnd() % 7 == 0) ? q_calloc(1, n) : q_malloc(n);
            CHECK(s->p != NULL);
            s->n = n; s->seed = (uint8_t)rnd();
            fill(s->p, n < 64 ? n : 64, s->seed);
            if (n >= 64) { size_t off = n - 64; for (size_t i = 0; i < 64; i++) s->p[off + i] = (uint8_t)(s->seed + (off + i) * 7); }
        }
        if (iter % 100000 == 99999) {              /* no two live blocks may overlap */
            static Slot copy[N]; int m = 0;
            for (int i = 0; i < N; i++) if (slots[i].p) copy[m++] = slots[i];
            qsort(copy, m, sizeof(Slot), cmp_ptr);
            int bad = 0;
            for (int i = 1; i < m; i++) if (copy[i - 1].p + copy[i - 1].n > copy[i].p) bad++;
            CHECK(bad == 0);
        }
    }
    for (int i = 0; i < N; i++) q_free(slots[i].p);
}

static void test_release(void) {
    q_trim();
    size_t base = rss_bytes();
    enum { K = 64 };
    uint8_t *b[K];
    for (int i = 0; i < K; i++) { b[i] = q_malloc(4 << 20); memset(b[i], 1, 4 << 20); }
    size_t peak = rss_bytes();
    CHECK(peak >= base + (size_t)K * (4 << 20) * 9 / 10);
    for (int i = 0; i < K; i++) q_free(b[i]);
    size_t after = rss_bytes();
    CHECK(after < peak / 4);                      /* freed spans were given back to the OS */
    q_stats_t st; q_get_stats(&st);
    CHECK(st.footprint_bytes < (size_t)K * (4 << 20) / 4);
    CHECK(st.peak_footprint_bytes >= (size_t)K * (4 << 20));
    /* released memory comes back zeroed and calloc knows it */
    uint8_t *z = q_calloc(1, 8 << 20);
    int zero = 1; for (size_t i = 0; i < (8u << 20); i += 4096) if (z[i]) zero = 0;
    CHECK(zero);
    q_free(z);
}

static double now_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (double)t.tv_sec + (double)t.tv_nsec * 1e-9; }

/* Regression: the best-fit search over large free spans used to be a linear walk of one list. */
static void test_large_scan(void) {
    enum { N = 20000 };
    static void *big[N], *guard[N];
    for (int i = 0; i < N; i++) { big[i] = q_malloc((1 << 20) + (i % 64) * 4096); guard[i] = q_malloc(70000); }
    for (int i = 0; i < N; i++) q_free(big[i]);       /* 20000 free holes of 256..319 pages */
    double t0 = now_s();
    for (int i = 0; i < N; i++) { big[i] = q_malloc((1 << 20) + 65 * 4096); CHECK(big[i] != NULL); }  /* none fits */
    CHECK(now_s() - t0 < 1.0);
    /* ... but a hole-sized request is satisfied from the right sub-bucket, not from a bigger span */
    for (int i = 0; i < N; i++) q_free(big[i]);
    for (int i = 0; i < N; i++) q_free(guard[i]);
}

/* calloc on fresh or released pages must not touch them (that is the point of tracking zero spans). */
static void test_calloc_untouched(void) {
    q_trim();
    size_t before = rss_bytes();
    uint8_t *p = q_calloc(1, 256 << 20);
    CHECK(p != NULL);
    size_t after = rss_bytes();
    CHECK(after < before + (32 << 20));
    CHECK(p[0] == 0 && p[(256 << 20) - 1] == 0 && p[100 << 20] == 0);
    memset(p, 1, 64 << 20);                         /* dirty part of it, free, and ask again */
    q_free(p);
    q_trim();
    uint8_t *z = q_calloc(1, 256 << 20);
    CHECK(z[0] == 0 && z[(64 << 20) - 1] == 0);
    CHECK(rss_bytes() < before + (64 << 20));
    q_free(z);
}

static void test_stats_snapshot(void) {
    q_trim();
    void *keep[300];
    for (int i = 0; i < 300; i++) keep[i] = q_malloc(100 + i * 10);
    void *big = q_malloc(200000);
    q_stats_t st; q_get_stats(&st);
    CHECK(st.small_pages > 0 && st.large_pages >= 49);
    size_t inuse = 0; for (int c = 0; c < Q_NCLASS; c++) inuse += st.cls[c].inuse;
    CHECK(inuse >= 300);
    size_t n = q_top_pages();
    q_page_info *pi = malloc(n * sizeof *pi);
    CHECK(q_snapshot(pi, n) == n);
    size_t small = 0, large = 0, freep = 0;
    for (size_t i = 0; i < n; i++) {
        if (pi[i].state == Q_PG_SMALL) { small++; CHECK(pi[i].occ <= 100); }
        else if (pi[i].state == Q_PG_LARGE) large++;
        else if (pi[i].state == Q_PG_FREE || pi[i].state == Q_PG_RELEASED) freep++;
        else CHECK(0);
    }
    CHECK(small == st.small_pages && large == st.large_pages && freep == st.free_pages);
    for (int i = 0; i < 300; i++) q_free(keep[i]);
    q_free(big); free(pi);
    q_trim();
    q_get_stats(&st);
    CHECK(st.small_pages == 0 && st.large_pages == 0);
    CHECK(st.free_pages == st.top_pages);          /* everything coalesced back */
}

int main(void) {
    test_basic();
    test_classes();
    test_calloc();
    test_realloc();
    test_large_inplace();
    test_memalign();
    test_checked_free();
    test_stress();
    test_release();
    test_large_scan();
    test_calloc_untouched();
    test_stats_snapshot();
    TEST_DONE("t_api");
}
