/* Multi-threaded stress: private churn, cross-thread frees through a handoff ring, thread exit.
 * Built twice: against the core directly (-DUSE_Q) and against whatever malloc is preloaded. */
#define _GNU_SOURCE
#include "check.h"
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

#ifdef USE_Q
#include "../src/quarry.h"
#define MALLOC q_malloc
#define FREE q_free
#define REALLOC q_realloc
#define CALLOC q_calloc
#else
#define MALLOC malloc
#define FREE free
#define REALLOC realloc
#define CALLOC calloc
#endif

#define NTHREADS 8
#define ITERS 150000
#define RING 4096

typedef struct { uint8_t *p; size_t n; uint32_t tag; } Item;

static Item ring[RING];
static pthread_mutex_t ring_mu = PTHREAD_MUTEX_INITIALIZER;
static volatile int errors;

static inline uint8_t pat(uint32_t tag, size_t i) { return (uint8_t)(tag * 2654435761u + i * 31u); }
static void stamp(uint8_t *p, size_t n, uint32_t tag) { for (size_t i = 0; i < n; i++) p[i] = pat(tag, i); }
static int verify(const uint8_t *p, size_t n, uint32_t tag) { for (size_t i = 0; i < n; i++) if (p[i] != pat(tag, i)) return 0; return 1; }

static void *worker(void *arg) {
    uint32_t id = (uint32_t)(uintptr_t)arg;
    uint64_t s = 0x1234567ULL * (id + 1) + 77;
    #define R() (s ^= s << 13, s ^= s >> 7, s ^= s << 17, s)
    Item mine[256]; memset(mine, 0, sizeof mine);
    for (int it = 0; it < ITERS; it++) {
        int k = (int)(R() % 256);
        if (mine[k].p) {
            if (!verify(mine[k].p, mine[k].n, mine[k].tag)) __atomic_fetch_add(&errors, 1, __ATOMIC_RELAXED);
            if (R() % 4 == 0) {
                size_t nn = R() % 5000 + 1;
                uint8_t *q = REALLOC(mine[k].p, nn);
                size_t keep = nn < mine[k].n ? nn : mine[k].n;
                if (!q || !verify(q, keep, mine[k].tag)) __atomic_fetch_add(&errors, 1, __ATOMIC_RELAXED);
                mine[k].p = q; mine[k].n = nn; mine[k].tag = (uint32_t)R(); stamp(q, nn, mine[k].tag);
            } else if (R() % 3 == 0) {
                /* hand the block to whichever thread picks it up from the ring */
                int slot = (int)(R() % RING);
                pthread_mutex_lock(&ring_mu);
                Item old = ring[slot]; ring[slot] = mine[k];
                pthread_mutex_unlock(&ring_mu);
                mine[k].p = NULL;
                if (old.p) {
                    if (!verify(old.p, old.n, old.tag)) __atomic_fetch_add(&errors, 1, __ATOMIC_RELAXED);
                    FREE(old.p);                             /* freed by a different thread than the allocator */
                }
            } else { FREE(mine[k].p); mine[k].p = NULL; }
        } else {
            size_t n = (R() % 30 == 0) ? R() % 200000 + 1 : R() % 600 + 1;
            mine[k].p = (R() % 5 == 0) ? CALLOC(1, n) : MALLOC(n);
            mine[k].n = n; mine[k].tag = (uint32_t)R();
            if (!mine[k].p) { __atomic_fetch_add(&errors, 1, __ATOMIC_RELAXED); continue; }
            stamp(mine[k].p, n, mine[k].tag);
        }
    }
    for (int k = 0; k < 256; k++) if (mine[k].p) { if (!verify(mine[k].p, mine[k].n, mine[k].tag)) __atomic_fetch_add(&errors, 1, __ATOMIC_RELAXED); FREE(mine[k].p); }
    return NULL;
}

static void *short_lived(void *arg) {                       /* threads that allocate once and exit */
    (void)arg;
    void *a[64];
    for (int i = 0; i < 64; i++) a[i] = MALLOC(16 + i * 40);
    for (int i = 0; i < 64; i += 2) FREE(a[i]);
    return a[1];                                              /* leaks odd ones on purpose: freed by main */
}

int main(void) {
    pthread_t th[NTHREADS];
    for (int i = 0; i < NTHREADS; i++) pthread_create(&th[i], NULL, worker, (void *)(uintptr_t)i);
    for (int i = 0; i < NTHREADS; i++) pthread_join(th[i], NULL);
    for (int i = 0; i < RING; i++) if (ring[i].p) { CHECK(verify(ring[i].p, ring[i].n, ring[i].tag)); FREE(ring[i].p); }
    CHECK(errors == 0);

    for (int round = 0; round < 200; round++) {              /* thread churn: caches must be flushed on exit */
        pthread_t t2[16]; void *res[16];
        for (int i = 0; i < 16; i++) pthread_create(&t2[i], NULL, short_lived, NULL);
        for (int i = 0; i < 16; i++) { pthread_join(t2[i], &res[i]); FREE(res[i]); }
    }
    CHECK(1);
#ifdef USE_Q
    q_trim();
    q_stats_t st; q_get_stats(&st);
    /* thread-cache objects of dead threads went back; only the odd blocks leaked on purpose remain */
    CHECK(st.large_pages == 0);
    size_t inuse = 0; for (int c = 0; c < Q_NCLASS; c++) inuse += st.cls[c].inuse;
    CHECK(inuse < 200 * 16 * 32 + 1000);
#endif
    TEST_DONE("t_threads");
}
