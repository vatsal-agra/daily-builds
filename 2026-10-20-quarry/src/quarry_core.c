/* Quarry allocator core.
 *
 *  - One big MAP_NORESERVE virtual reservation; "is this pointer ours" is an address-range check.
 *  - Page heap: 4 KiB pages grouped in spans, a flat pagemap (page -> span), best-fit free lists,
 *    split + immediate coalescing, lazy madvise(DONTNEED) scavenging, per-span "known zero" flag.
 *  - Small objects (<= 32 KiB): 40 size classes, slab spans carved lazily, central partial lists,
 *    per-thread caches with batch refill / flush.
 *  - Large objects: whole spans; realloc grows and shrinks in place.
 */
#define _GNU_SOURCE
#include "quarry.h"

#include <errno.h>
#include <pthread.h>
#include <string.h>
#include <sys/mman.h>
#include <sched.h>
#include <unistd.h>

#define PAGE      Q_PAGE_SIZE
#define PSHIFT    12
#define MAX_SMALL Q_MAX_SMALL
#define NCLS      Q_NCLASS
#define NLISTS    256            /* exact-size free lists for 1..255 pages; >= 256 on one list */
#define GROW_PAGES 256           /* the page heap grows in 1 MiB steps */
#define MIN_RELEASE_PAGES 16     /* never madvise runs shorter than 64 KiB */
#define SCAV_SLACK (2UL << 20)   /* always allow 2 MiB of resident free memory ... */

#define LIKELY(x)   __builtin_expect(!!(x), 1)
#define UNLIKELY(x) __builtin_expect(!!(x), 0)

enum { SP_NONE = 0, SP_FREE, SP_SMALL, SP_LARGE };

typedef struct Span {
    struct Span *prev, *next;
    size_t   page;               /* first page index relative to the region base */
    size_t   npages;
    uint8_t  state;
    uint8_t  released;           /* free span whose pages are not resident */
    uint8_t  zero;               /* every byte of the span is known to be 0 */
    uint8_t  cls;
    uint8_t  onlist;             /* slab is on its class's partial list */
    uint32_t inuse, nobj, bump;  /* slab accounting */
    void    *freelist;
} Span;

typedef struct { void *head[NCLS]; uint16_t count[NCLS]; uint8_t registered; } TCache;

static struct {
    int state;                          /* 0 = not started, 1 = starting, 2 = ready */
    pthread_mutex_t lock;
    char   *base;
    size_t  cap_pages, top_pages;
    Span  **map;
    Span   *lists[NLISTS];              /* index n: free spans of exactly n pages; [0] unused */
    Span   *large_free;                 /* free spans of >= NLISTS pages */
    uint64_t bitmap[NLISTS / 64];
    size_t  free_pages, released_pages, small_pages, large_pages;
    size_t  peak_fp, scav_floor, reserved;
    Span   *span_pool;
    char   *meta_cur, *meta_end;
    size_t  meta_bytes;
    Span   *partial[NCLS];
    size_t  cls_spans[NCLS], cls_objs[NCLS], cls_inuse[NCLS];
    uint32_t cls_size[NCLS], cls_pages[NCLS];
    uint8_t sc_small[65];               /* (size+15)/16 for size <= 1024 */
    uint8_t sc_large[(MAX_SMALL - 1024) / 128 + 1];
    pthread_key_t key;
    int key_ok;
} G = { .lock = PTHREAD_MUTEX_INITIALIZER };

static __thread TCache tc;

/* ------------------------------------------------------------------ helpers */

static void *os_map(size_t bytes, int noreserve) {
    void *p = mmap(NULL, bytes, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | (noreserve ? MAP_NORESERVE : 0), -1, 0);
    return p == MAP_FAILED ? NULL : p;
}

static inline void *page_addr(size_t page) { return G.base + (page << PSHIFT); }

/* top_pages only grows and is published with a relaxed store: lock-free readers (free fast path,
 * q_owns) need at most a value that covers every pointer they were legitimately handed. */
static inline size_t top_now(void) { return __atomic_load_n(&G.top_pages, __ATOMIC_RELAXED); }

static inline Span *span_of(const void *p) {
    size_t off = (size_t)((const char *)p - G.base);
    if ((const char *)p < G.base || (off >> PSHIFT) >= top_now()) return NULL;
    return __atomic_load_n(&G.map[off >> PSHIFT], __ATOMIC_RELAXED);
}

static inline int ready(void) { return __atomic_load_n(&G.state, __ATOMIC_ACQUIRE) == 2; }

static inline void lock(void)   { pthread_mutex_lock(&G.lock); }
static inline void unlock(void) { pthread_mutex_unlock(&G.lock); }

/* --------------------------------------------------------------- span structs */

static Span *new_span(void) {
    Span *s = G.span_pool;
    if (s) { G.span_pool = s->next; }
    else {
        if (G.meta_cur + sizeof(Span) > G.meta_end) {
            size_t chunk = 64 << 10;
            char *m = os_map(chunk, 0);
            if (!m) return NULL;
            G.meta_cur = m; G.meta_end = m + chunk; G.meta_bytes += chunk;
        }
        s = (Span *)G.meta_cur; G.meta_cur += sizeof(Span);
    }
    memset(s, 0, sizeof *s);
    return s;
}

static void del_span(Span *s) { s->state = SP_NONE; s->next = G.span_pool; G.span_pool = s; }

/* ------------------------------------------------------------------- pagemap */

static inline void map_put(size_t i, Span *s) { __atomic_store_n(&G.map[i], s, __ATOMIC_RELAXED); }
static inline void map_set_ends(Span *s)  { map_put(s->page, s); map_put(s->page + s->npages - 1, s); }
static inline void map_clear_ends(Span *s){ map_put(s->page, NULL); map_put(s->page + s->npages - 1, NULL); }
static inline void map_set_all(Span *s)   { for (size_t i = 0; i < s->npages; i++) map_put(s->page + i, s); }
static inline void map_clear_all(Span *s) { for (size_t i = 0; i < s->npages; i++) map_put(s->page + i, NULL); }

/* ----------------------------------------------------------- free-list upkeep */

static void fl_insert(Span *s) {
    Span **head = s->npages < NLISTS ? &G.lists[s->npages] : &G.large_free;
    s->prev = NULL; s->next = *head;
    if (*head) (*head)->prev = s;
    *head = s;
    if (s->npages < NLISTS) G.bitmap[s->npages >> 6] |= 1ULL << (s->npages & 63);
    G.free_pages += s->npages;
    if (s->released) G.released_pages += s->npages;
}

static void fl_remove(Span *s) {
    Span **head = s->npages < NLISTS ? &G.lists[s->npages] : &G.large_free;
    if (s->prev) s->prev->next = s->next; else *head = s->next;
    if (s->next) s->next->prev = s->prev;
    if (s->npages < NLISTS && !*head) G.bitmap[s->npages >> 6] &= ~(1ULL << (s->npages & 63));
    G.free_pages -= s->npages;
    if (s->released) G.released_pages -= s->npages;
    s->prev = s->next = NULL;
}

/* First non-empty exact-size list with index >= n (n < NLISTS), or 0. */
static size_t find_list(size_t n) {
    for (size_t w = n >> 6; w < NLISTS / 64; w++) {
        uint64_t bits = G.bitmap[w];
        if (w == (n >> 6)) bits &= ~0ULL << (n & 63);
        if (bits) return (w << 6) + (size_t)__builtin_ctzll(bits);
    }
    return 0;
}

/* ------------------------------------------------------------------ page heap */

static void maybe_scavenge(void);

static inline size_t footprint_pages(void) { return G.top_pages - G.released_pages; }
static inline size_t used_pages(void)      { return G.small_pages + G.large_pages; }

/* Return a run of pages to the heap, merging with free neighbours.  `s` must be
 * detached (not on any list).  Its pagemap entries may still point at it. */
static void ph_free(Span *s) {
    map_clear_all(s);
    s->state = SP_FREE; s->prev = s->next = NULL;
    if (s->page > 0) {
        Span *p = G.map[s->page - 1];
        if (p && p->state == SP_FREE) {
            fl_remove(p); map_clear_ends(p);
            p->npages += s->npages; p->zero &= s->zero; p->released &= s->released;
            del_span(s); s = p;
        }
    }
    size_t idx = s->page + s->npages;
    if (idx < G.top_pages) {
        Span *n = G.map[idx];
        if (n && n->state == SP_FREE) {
            fl_remove(n); map_clear_ends(n);
            s->npages += n->npages; s->zero &= n->zero; s->released &= n->released;
            del_span(n);
        }
    }
    map_set_ends(s);
    fl_insert(s);
}

/* Cut `s` (detached, ends cleared) down to n pages; the remainder goes back to the heap. */
static void ph_trim_tail(Span *s, size_t n) {
    if (s->npages <= n) return;
    Span *t = new_span();
    if (!t) return;                       /* out of metadata: keep the slack inside the span */
    t->page = s->page + n; t->npages = s->npages - n;
    t->zero = s->zero; t->released = s->released;
    s->npages = n;
    ph_free(t);
}

static int ph_grow(size_t n) {
    size_t want = n < GROW_PAGES ? GROW_PAGES : n;
    if (G.top_pages + want > G.cap_pages) {
        want = n;
        if (G.top_pages + want > G.cap_pages) return 0;
    }
    Span *s = new_span();
    if (!s) return 0;
    s->page = G.top_pages; s->npages = want; s->zero = 1; s->released = 1;   /* untouched == released */
    __atomic_store_n(&G.top_pages, G.top_pages + want, __ATOMIC_RELAXED);
    ph_free(s);
    return 1;
}

/* Detached span of exactly n pages (flags `zero`/`released` still describe its contents),
 * or NULL.  Pagemap entries of the result are cleared. */
static Span *ph_alloc(size_t n) {
    for (;;) {
        Span *s = NULL;
        if (n < NLISTS) {
            size_t i = find_list(n);
            if (i) s = G.lists[i];
        }
        if (!s) {
            for (Span *c = G.large_free; c; c = c->next)
                if (c->npages >= n && (!s || c->npages < s->npages ||
                                       (c->npages == s->npages && c->page < s->page))) {
                    s = c;
                    if (c->npages == n) break;
                }
        }
        if (s) {
            fl_remove(s); map_clear_ends(s);
            ph_trim_tail(s, n);
            return s;
        }
        if (!ph_grow(n)) return NULL;
    }
}

static void note_peak(void) {
    size_t fp = footprint_pages() * PAGE + G.meta_bytes;
    if (fp > G.peak_fp) G.peak_fp = fp;
}

/* Mark `s` as in use (it is about to be touched). */
static void ph_commit(Span *s, uint8_t state) {
    s->state = state; s->released = 0;
    map_set_all(s);
    if (state == SP_SMALL) G.small_pages += s->npages; else G.large_pages += s->npages;
    note_peak();
}

static void do_release(Span *s) {         /* s is on a free list */
    if (s->released || s->npages < MIN_RELEASE_PAGES) return;
    madvise(page_addr(s->page), s->npages << PSHIFT, MADV_DONTNEED);
    G.released_pages += s->npages;
    s->released = 1; s->zero = 1;
}

static void scavenge(size_t target_bytes) {
    size_t target = target_bytes >> PSHIFT;
    for (Span *s = G.large_free; s && G.free_pages - G.released_pages > target; s = s->next) do_release(s);
    for (size_t i = NLISTS - 1; i >= MIN_RELEASE_PAGES && G.free_pages - G.released_pages > target; i--)
        for (Span *s = G.lists[i]; s && G.free_pages - G.released_pages > target; s = s->next) do_release(s);
    G.scav_floor = G.free_pages - G.released_pages;
}

static void maybe_scavenge(void) {
    size_t unreleased = G.free_pages - G.released_pages;
    size_t limit = (SCAV_SLACK + (used_pages() << PSHIFT) / 4) >> PSHIFT;
    if (unreleased > limit && unreleased > G.scav_floor + 256) scavenge(limit * PAGE / 2);
}

/* -------------------------------------------------------------- size classes */

static void classes_init(void) {
    uint32_t sizes[NCLS]; int n = 0;
    for (uint32_t s = 16; s <= 128; s += 16) sizes[n++] = s;
    for (uint32_t base = 128; base < MAX_SMALL; base *= 2)
        for (int k = 1; k <= 4; k++) sizes[n++] = base + k * (base / 4);
    for (int i = 0; i < n; i++) {
        G.cls_size[i] = sizes[i];
        uint32_t s = sizes[i], pages = 64;
        for (uint32_t p = 1; p <= 64; p++) {
            size_t bytes = (size_t)p << PSHIFT;
            if (bytes < s) continue;
            size_t obj = bytes / s, waste = bytes - obj * s;
            if (obj >= 4 && waste * 8 <= bytes) { pages = p; break; }
        }
        G.cls_pages[i] = pages;
    }
    int c = 0;
    for (size_t i = 0; i <= 64; i++) {
        while (G.cls_size[c] < i * 16) c++;
        G.sc_small[i] = (uint8_t)c;
    }
    c = 0;
    for (size_t i = 0; i < sizeof G.sc_large; i++) {
        size_t sz = 1024 + i * 128;
        while (c < NCLS - 1 && G.cls_size[c] < sz) c++;
        G.sc_large[i] = (uint8_t)c;
    }
}

static inline int size_to_class(size_t n) {
    if (n <= 1024) return G.sc_small[(n + 15) >> 4];
    return G.sc_large[(n - 1024 + 127) >> 7];
}

size_t q_class_size(int cls) { return (cls >= 0 && cls < NCLS && ready()) ? G.cls_size[cls] : 0; }

/* ------------------------------------------------------------------- central */

static Span *slab_new(int cls) {
    Span *s = ph_alloc(G.cls_pages[cls]);
    if (!s) return NULL;
    s->cls = (uint8_t)cls; s->zero = 0; s->freelist = NULL; s->inuse = 0; s->bump = 0;
    s->nobj = (uint32_t)((s->npages << PSHIFT) / G.cls_size[cls]);
    ph_commit(s, SP_SMALL);
    G.cls_spans[cls]++; G.cls_objs[cls] += s->nobj;
    s->prev = NULL; s->next = G.partial[cls];
    if (s->next) s->next->prev = s;
    G.partial[cls] = s; s->onlist = 1;
    return s;
}

static void partial_remove(Span *s) {
    if (s->prev) s->prev->next = s->next; else G.partial[s->cls] = s->next;
    if (s->next) s->next->prev = s->prev;
    s->prev = s->next = NULL; s->onlist = 0;
}

static void *central_pop(int cls) {           /* G.lock held */
    Span *s = G.partial[cls];
    if (!s && !(s = slab_new(cls))) return NULL;
    void *o;
    if (s->freelist) { o = s->freelist; s->freelist = *(void **)o; }
    else { o = (char *)page_addr(s->page) + (size_t)s->bump++ * G.cls_size[cls]; }
    s->inuse++; G.cls_inuse[cls]++;
    if (s->inuse == s->nobj) partial_remove(s);
    return o;
}

static void central_push(void *o) {           /* G.lock held; o is a valid small object */
    Span *s = span_of(o);
    s->inuse--; G.cls_inuse[s->cls]--;
    if (s->inuse == 0) {                      /* whole slab is free again: hand it back */
        if (s->onlist) partial_remove(s);
        G.cls_spans[s->cls]--; G.cls_objs[s->cls] -= s->nobj;
        G.small_pages -= s->npages;
        s->zero = 0; s->released = 0; s->freelist = NULL;
        ph_free(s);
        maybe_scavenge();
        return;
    }
    *(void **)o = s->freelist; s->freelist = o;
    if (!s->onlist) {
        s->prev = NULL; s->next = G.partial[s->cls];
        if (s->next) s->next->prev = s;
        G.partial[s->cls] = s; s->onlist = 1;
    }
}

/* ------------------------------------------------------------- thread caches */

static inline unsigned batch_for(int cls) {
    unsigned b = 16384 / G.cls_size[cls];
    return b < 2 ? 2 : b > 32 ? 32 : b;
}

static void tc_destructor(void *arg);

static void tc_register(void) {
    tc.registered = 1;                        /* set first: pthread_setspecific may call malloc */
    if (G.key_ok) pthread_setspecific(G.key, &tc);
}

static void tc_release(int cls, unsigned n) {
    void *objs[64]; unsigned k = 0;
    while (k < n && tc.head[cls]) {
        void *o = tc.head[cls];
        tc.head[cls] = *(void **)o; tc.count[cls]--;
        objs[k++] = o;
    }
    if (!k) return;
    lock();
    for (unsigned i = 0; i < k; i++) central_push(objs[i]);
    unlock();
}

static void tc_destructor(void *arg) {
    (void)arg;
    for (int c = 0; c < NCLS; c++) while (tc.head[c]) tc_release(c, 32);
    tc.registered = 0;
}

void q_thread_flush(void) {
    if (!ready()) return;
    for (int c = 0; c < NCLS; c++) while (tc.head[c]) tc_release(c, 32);
}

/* ----------------------------------------------------------------------- init */

static void atfork_prepare(void) { lock(); }
static void atfork_parent(void)  { unlock(); }
static void atfork_child(void)   { pthread_mutex_init(&G.lock, NULL); }

static void init_slow(void) {
    int expected = 0;
    if (!__atomic_compare_exchange_n(&G.state, &expected, 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        while (__atomic_load_n(&G.state, __ATOMIC_ACQUIRE) != 2) sched_yield();
        return;
    }
    size_t cap = 1UL << 38;                   /* 256 GiB of address space, halved until the OS agrees */
    void *region = NULL, *map = NULL;
    for (; cap >= (1UL << 28); cap >>= 1) {
        region = os_map(cap, 1);
        if (!region) continue;
        map = os_map((cap >> PSHIFT) * sizeof(Span *), 1);
        if (map) break;
        munmap(region, cap); region = NULL;
    }
    if (!region || !map) { static const char m[] = "quarry: cannot reserve address space\n"; if (write(2, m, sizeof m - 1) < 0) {} _exit(70); }
    G.base = region; G.map = map; G.reserved = cap; G.cap_pages = cap >> PSHIFT;
    classes_init();
    G.key_ok = pthread_key_create(&G.key, tc_destructor) == 0;   /* does not allocate */
    __atomic_store_n(&G.state, 2, __ATOMIC_RELEASE);
    /* pthread_atfork may call malloc itself, so the allocator must already be usable. */
    pthread_atfork(atfork_prepare, atfork_parent, atfork_child);
}

static inline void ensure_init(void) { if (UNLIKELY(!ready())) init_slow(); }

/* ------------------------------------------------------------------ allocation */

static void *large_alloc(size_t n, size_t align, int *zero_out) {
    if (n > (size_t)-1 - 2 * PAGE - align) { errno = ENOMEM; return NULL; }
    size_t np = (n + PAGE - 1) >> PSHIFT;
    if (np == 0) np = 1;
    if (np > G.cap_pages) { errno = ENOMEM; return NULL; }
    lock();
    Span *s;
    if (align <= PAGE) s = ph_alloc(np);
    else {
        size_t extra = align / PAGE;
        s = ph_alloc(np + extra - 1);
        if (s) {
            uintptr_t a = ((uintptr_t)page_addr(s->page) + align - 1) & ~(uintptr_t)(align - 1);
            size_t off = (a - (uintptr_t)page_addr(s->page)) >> PSHIFT;
            if (off) {
                Span *h = new_span();
                if (h) {
                    h->page = s->page; h->npages = off; h->zero = s->zero; h->released = s->released;
                    s->page += off; s->npages -= off;
                    ph_free(h);
                } else { /* cannot split: realign by over-allocating again is not possible; give up */
                    s->state = SP_LARGE; ph_free(s); s = NULL;
                }
            }
            if (s) ph_trim_tail(s, np);
        }
    }
    if (!s) { unlock(); errno = ENOMEM; return NULL; }
    if (zero_out) *zero_out = s->zero;
    s->zero = 0;
    s->state = SP_LARGE;
    ph_commit(s, SP_LARGE);
    unlock();
    return page_addr(s->page);
}

void *q_malloc(size_t n) {
    ensure_init();
    if (LIKELY(n <= MAX_SMALL)) {
        int c = size_to_class(n);
        void *o = tc.head[c];
        if (LIKELY(o != NULL)) { tc.head[c] = *(void **)o; tc.count[c]--; return o; }
        if (UNLIKELY(!tc.registered)) tc_register();
        unsigned b = batch_for(c), got = 0;
        void *list = NULL;
        lock();
        while (got < b) {
            void *x = central_pop(c);
            if (!x) break;
            *(void **)x = list; list = x; got++;
        }
        unlock();
        if (!got) { errno = ENOMEM; return NULL; }
        o = list; list = *(void **)o;
        tc.head[c] = list; tc.count[c] = (uint16_t)(got - 1);
        return o;
    }
    return large_alloc(n, 0, NULL);
}

void *q_calloc(size_t nmemb, size_t size) {
    size_t n;
    if (__builtin_mul_overflow(nmemb, size, &n)) { errno = ENOMEM; return NULL; }
    if (n <= MAX_SMALL) {
        void *p = q_malloc(n);
        if (p) memset(p, 0, n);
        return p;
    }
    ensure_init();
    int was_zero = 0;
    void *p = large_alloc(n, 0, &was_zero);
    if (p && !was_zero) memset(p, 0, n);      /* fresh or released pages are already zero */
    return p;
}

static void free_small(Span *s, void *p) {
    int c = s->cls;
    if (UNLIKELY(!tc.registered)) tc_register();
    *(void **)p = tc.head[c]; tc.head[c] = p;
    unsigned b = batch_for(c);
    if (UNLIKELY(++tc.count[c] > 2 * b)) tc_release(c, b);
}

static void free_large(Span *s) {
    lock();
    G.large_pages -= s->npages;
    s->zero = 0; s->released = 0;
    ph_free(s);
    maybe_scavenge();
    unlock();
}

void q_free(void *p) {
    if (!p || !ready()) return;
    Span *s = span_of(p);
    if (UNLIKELY(!s)) return;
    if (LIKELY(s->state == SP_SMALL)) { free_small(s, p); return; }
    if (s->state == SP_LARGE && p == page_addr(s->page)) free_large(s);
}

q_free_status q_free_checked(void *p) {
    if (!p) return Q_FREE_OK;
    if (!ready() || !q_owns(p)) return Q_FREE_FOREIGN;
    lock();
    Span *s = span_of(p);
    q_free_status st = Q_FREE_OK;
    if (!s || s->state == SP_FREE) st = Q_FREE_DOUBLE;
    else if (s->state == SP_SMALL) {
        size_t off = (size_t)((char *)p - (char *)page_addr(s->page)), sz = G.cls_size[s->cls];
        if (off % sz || off / sz >= s->bump) st = Q_FREE_BADPTR;
        else {
            for (void *f = s->freelist; f; f = *(void **)f) if (f == p) { st = Q_FREE_DOUBLE; break; }
            if (st == Q_FREE_OK) {
                /* objects sitting in this thread's cache are free too */
                for (void *f = tc.head[s->cls]; f; f = *(void **)f) if (f == p) { st = Q_FREE_DOUBLE; break; }
            }
        }
    } else if (p != page_addr(s->page)) st = Q_FREE_BADPTR;
    unlock();
    if (st == Q_FREE_OK) q_free(p);
    return st;
}

int q_owns(const void *p) {
    return ready() && (const char *)p >= G.base && (const char *)p < G.base + (top_now() << PSHIFT);
}

size_t q_usable_size(const void *p) {
    if (!p || !ready()) return 0;
    Span *s = span_of(p);
    if (!s) return 0;
    if (s->state == SP_SMALL) return G.cls_size[s->cls];
    if (s->state == SP_LARGE) return s->npages << PSHIFT;
    return 0;
}

/* Try to resize a large span in place; returns 1 on success. */
static int large_resize_inplace(Span *s, size_t np) {
    int ok = 0;
    lock();
    if (np < s->npages) {
        G.large_pages -= s->npages - np;
        Span *t = new_span();
        if (t) {
            t->page = s->page + np; t->npages = s->npages - np; t->zero = 0; t->released = 0;
            map_clear_all(t);
            s->npages = np;
            ph_free(t);
            maybe_scavenge();
            ok = 1;
        } else G.large_pages += s->npages - np;
    } else {
        size_t need = np - s->npages;
        size_t end = s->page + s->npages;
        if (end == G.top_pages) ph_grow(need);
        Span *nx = end < G.top_pages ? G.map[end] : NULL;
        if (nx && nx->state == SP_FREE && nx->npages >= need) {
            fl_remove(nx); map_clear_ends(nx);
            if (nx->npages > need) {
                Span *rest = new_span();
                if (rest) {
                    rest->page = nx->page + need; rest->npages = nx->npages - need;
                    rest->zero = nx->zero; rest->released = nx->released;
                    nx->npages = need;
                    ph_free(rest);
                }
            }
            s->npages += nx->npages;
            G.large_pages += nx->npages;
            del_span(nx);
            map_set_all(s);
            note_peak();
            ok = 1;
        }
    }
    unlock();
    return ok;
}

void *q_realloc(void *p, size_t n) {
    if (!p) return q_malloc(n);
    ensure_init();
    Span *s = span_of(p);
    if (!s || (s->state != SP_SMALL && s->state != SP_LARGE)) { errno = EINVAL; return NULL; }
    size_t usable = s->state == SP_SMALL ? G.cls_size[s->cls] : s->npages << PSHIFT;
    if (s->state == SP_SMALL) {
        if (n <= usable && n >= usable - usable / 4) return p;
    } else if (n > MAX_SMALL) {
        if (n > (size_t)-1 - 2 * PAGE) { errno = ENOMEM; return NULL; }
        size_t np = (n + PAGE - 1) >> PSHIFT;
        if (np == s->npages) return p;
        if (p == page_addr(s->page) && large_resize_inplace(s, np)) return p;
    }
    void *q = q_malloc(n);
    if (!q) return NULL;
    memcpy(q, p, n < usable ? n : usable);
    q_free(p);
    return q;
}

void *q_memalign(size_t align, size_t n) {
    ensure_init();
    if (align <= 16) return q_malloc(n);
    if (align & (align - 1)) { size_t a = 16; while (a < align && a) a <<= 1; align = a; }
    if (align == 0 || align > (1UL << 30)) { errno = EINVAL; return NULL; }
    if (align <= PAGE && n <= MAX_SMALL) {
        int c = size_to_class(n);
        while (c < NCLS && G.cls_size[c] % align) c++;
        if (c < NCLS) return q_malloc(G.cls_size[c]);
    }
    return large_alloc(n ? n : 1, align, NULL);
}

int q_posix_memalign(void **out, size_t align, size_t n) {
    if (align < sizeof(void *) || (align & (align - 1))) return EINVAL;
    void *p = q_memalign(align, n);
    if (!p) return ENOMEM;
    *out = p;
    return 0;
}

/* ----------------------------------------------------------------- introspection */

size_t q_footprint(void) {
    if (!ready()) return 0;
    lock();
    size_t f = footprint_pages() * PAGE + G.meta_bytes;
    unlock();
    return f;
}

size_t q_top_pages(void) { return ready() ? G.top_pages : 0; }

void q_get_stats(q_stats_t *o) {
    memset(o, 0, sizeof *o);
    if (!ready()) return;
    lock();
    o->reserved_bytes = G.reserved; o->top_pages = G.top_pages;
    o->free_pages = G.free_pages; o->released_pages = G.released_pages;
    o->small_pages = G.small_pages; o->large_pages = G.large_pages;
    o->meta_bytes = G.meta_bytes;
    o->footprint_bytes = footprint_pages() * PAGE + G.meta_bytes;
    o->peak_footprint_bytes = G.peak_fp;
    for (int c = 0; c < NCLS; c++) {
        o->cls[c].size = G.cls_size[c]; o->cls[c].span_pages = G.cls_pages[c];
        o->cls[c].spans = G.cls_spans[c]; o->cls[c].objects = G.cls_objs[c]; o->cls[c].inuse = G.cls_inuse[c];
    }
    unlock();
}

size_t q_snapshot(q_page_info *out, size_t max_pages) {
    if (!ready()) return 0;
    lock();
    size_t top = G.top_pages;
    for (size_t pg = 0; pg < top;) {
        Span *s = G.map[pg];
        size_t n = s ? s->npages : 1;
        for (size_t i = 0; i < n && pg + i < top; i++) {
            if (pg + i >= max_pages) continue;
            q_page_info *e = &out[pg + i];
            memset(e, 0, sizeof *e);
            if (!s) continue;
            if (s->state == SP_FREE) e->state = s->released ? Q_PG_RELEASED : Q_PG_FREE;
            else if (s->state == SP_LARGE) e->state = Q_PG_LARGE;
            else { e->state = Q_PG_SMALL; e->cls = s->cls; e->occ = (uint8_t)(100ULL * s->inuse / s->nobj); }
        }
        pg += n;
    }
    unlock();
    return top;
}

void q_trim(void) {
    if (!ready()) return;
    q_thread_flush();
    lock();
    scavenge(0);
    for (Span *s = G.large_free; s; s = s->next) do_release(s);
    unlock();
}
