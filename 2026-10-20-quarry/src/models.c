/* Comparison allocators for the replay simulator.
 *
 *  bump     — never frees: the floor for speed and the ceiling for waste.
 *  firstfit — textbook boundary-tag allocator: 8-byte headers, explicit LIFO free list,
 *             immediate coalescing both ways, first fit, heap only ever grows.
 *  buddy    — binary buddy system: power-of-two blocks, split and merge by address xor.
 *  glibc    — the system malloc (ptmalloc2), measured through mallinfo2().
 *  quarry   — the allocator in this repository.
 */
#define _GNU_SOURCE
#include "models.h"
#include "quarry.h"

#include <errno.h>
#include <malloc.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

/* ------------------------------------------------------------------- arenas */

typedef struct { char *base; size_t cap; } Arena;

static int arena_open(Arena *a, size_t want) {
    for (size_t cap = want; cap >= (1UL << 26); cap >>= 1) {
        void *p = mmap(NULL, cap, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
        if (p != MAP_FAILED) { a->base = p; a->cap = cap; return 0; }
    }
    return -1;
}
static void arena_close(Arena *a) { if (a->base) munmap(a->base, a->cap); a->base = NULL; }

#define ALIGN16(x) (((x) + 15) & ~(size_t)15)

/* --------------------------------------------------------------------- bump */

static Arena bump_a; static size_t bump_top;
static int bump_init(void) { bump_top = 0; return arena_open(&bump_a, 1UL << 36); }
static void bump_fini(void) { arena_close(&bump_a); }
static void *bump_alloc(size_t n, int zero) {
    (void)zero;                               /* fresh anonymous memory is zero */
    size_t sz = ALIGN16(n ? n : 1);
    if (sz < n || bump_top + sz > bump_a.cap) return NULL;
    void *p = bump_a.base + bump_top; bump_top += sz;
    return p;
}
static void *bump_aligned(size_t al, size_t n) {
    size_t at = (bump_top + al - 1) & ~(al - 1);
    if (at + n > bump_a.cap) return NULL;
    bump_top = at + (n ? n : 1); bump_top = ALIGN16(bump_top);
    return bump_a.base + at;
}
static void bump_free(void *p) { (void)p; }
static void *bump_resize(void *p, size_t old_n, size_t n) {
    void *q = bump_alloc(n, 0);
    if (q && p) memcpy(q, p, old_n < n ? old_n : n);
    return q;
}
static size_t bump_fp(void) { return bump_top; }

/* ----------------------------------------------------------------- first-fit */

#define FF_ALLOC 1UL
#define FF_PREV  2UL
#define FF_MIN   32
#define FF_GROW  (64 << 10)
#define FF_MAGIC 0x51464641524C4947UL

typedef struct FFree { struct FFree *prev, *next; } FFree;
static Arena ff_a; static size_t ff_top;       /* ff_top: end of the last block */
static char *ff_last;                           /* start of the last block, or NULL */
static FFree *ff_head;

static inline uint64_t *hdr(char *b) { return (uint64_t *)b; }
static inline size_t bsize(char *b) { return *hdr(b) & ~15UL; }
static inline int balloc(char *b) { return *hdr(b) & FF_ALLOC; }
static inline int bprev_alloc(char *b) { return *hdr(b) & FF_PREV; }
static inline uint64_t *ffoot(char *b) { return (uint64_t *)(b + bsize(b) - 8); }
static inline FFree *flnk(char *b) { return (FFree *)(b + 8); }

static void ff_unlink(char *b) {
    FFree *f = flnk(b);
    if (f->prev) f->prev->next = f->next; else ff_head = f->next;
    if (f->next) f->next->prev = f->prev;
}
static void ff_link(char *b) {
    FFree *f = flnk(b);
    f->prev = NULL; f->next = ff_head;
    if (ff_head) ff_head->prev = f;
    ff_head = f;
}
static void ff_mark_next_prev(char *b, int alloc) {     /* tell the successor whether b is allocated */
    char *nx = b + bsize(b);
    if ((size_t)(nx - ff_a.base) >= ff_top) return;
    if (alloc) *hdr(nx) |= FF_PREV; else *hdr(nx) &= ~FF_PREV;
}
static void ff_set_free(char *b, size_t size, int prev_alloc) {
    *hdr(b) = size | (prev_alloc ? FF_PREV : 0);
    *ffoot(b) = *hdr(b);
    ff_mark_next_prev(b, 0);
    ff_link(b);
}

static int ff_init(void) {
    ff_top = 8; ff_last = NULL; ff_head = NULL;
    return arena_open(&ff_a, 1UL << 36);
}
static void ff_fini(void) { arena_close(&ff_a); }

static int ff_extend(size_t need) {
    size_t grow = need < FF_GROW ? FF_GROW : ALIGN16(need);
    if (ff_top + grow > ff_a.cap) return -1;
    char *b = ff_a.base + ff_top;
    int prev_alloc = 1;
    if (ff_last && !balloc(ff_last)) {          /* merge with a free tail */
        ff_unlink(ff_last);
        b = ff_last; grow += bsize(ff_last); prev_alloc = bprev_alloc(ff_last);
    } else if (ff_last) prev_alloc = 1;
    ff_top = (size_t)(b - ff_a.base) + grow;
    *hdr(b) = grow | (prev_alloc ? FF_PREV : 0);
    *ffoot(b) = *hdr(b);
    ff_last = b;
    ff_link(b);
    return 0;
}

static void *ff_alloc_raw(size_t n) {
    size_t need = ALIGN16(n + 8);
    if (need < FF_MIN || need < n) need = need < n ? (size_t)-1 : FF_MIN;
    if (need == (size_t)-1) return NULL;
    for (;;) {
        for (FFree *f = ff_head; f; f = f->next) {
            char *b = (char *)f - 8;
            size_t bs = bsize(b);
            if (bs < need) continue;
            ff_unlink(b);
            if (bs - need >= FF_MIN) {
                *hdr(b) = need | FF_ALLOC | (bprev_alloc(b) ? FF_PREV : 0);
                char *r = b + need;
                *hdr(r) = (bs - need) | FF_PREV;
                *ffoot(r) = *hdr(r);
                if (ff_last == b) ff_last = r;
                ff_link(r);
                ff_mark_next_prev(r, 0);
            } else {
                *hdr(b) |= FF_ALLOC;
                ff_mark_next_prev(b, 1);
            }
            return b + 8;
        }
        if (ff_extend(need) < 0) return NULL;
    }
}

static void *ff_alloc(size_t n, int zero) {
    void *p = ff_alloc_raw(n);
    if (p && zero) memset(p, 0, n);
    return p;
}

static void ff_free(void *p) {
    char *b = (char *)p - 8;
    uint64_t *mag = (uint64_t *)p - 2;           /* aligned allocations carry a back pointer */
    if ((char *)mag >= ff_a.base + 8 && mag[0] == FF_MAGIC && (char *)mag[1] < (char *)p && (char *)mag[1] >= ff_a.base) {
        void *orig = (void *)mag[1];
        if (((uintptr_t)orig & 15) == 0 && p > orig && (char *)p < (char *)orig + bsize((char *)orig - 8)) {
            mag[0] = 0;
            b = (char *)orig - 8;
        }
    }
    size_t size = bsize(b);
    int prev_alloc = bprev_alloc(b);
    char *nx = b + size;
    if ((size_t)(nx - ff_a.base) < ff_top && !balloc(nx)) {          /* merge forward */
        ff_unlink(nx);
        if (ff_last == nx) ff_last = b;
        size += bsize(nx);
    }
    if (!prev_alloc) {                                                /* merge backward */
        size_t psz = *(uint64_t *)(b - 8) & ~15UL;
        char *pv = b - psz;
        ff_unlink(pv);
        if (ff_last == b) ff_last = pv;
        prev_alloc = bprev_alloc(pv);
        b = pv; size += psz;
    }
    ff_set_free(b, size, prev_alloc);
}

static void *ff_aligned(size_t al, size_t n) {
    if (al <= 16) return ff_alloc_raw(n);
    void *raw = ff_alloc_raw(n + al + 32);
    if (!raw) return NULL;
    uintptr_t q = ((uintptr_t)raw + 16 + al - 1) & ~(uintptr_t)(al - 1);
    uint64_t *mag = (uint64_t *)q - 2;
    mag[0] = FF_MAGIC; mag[1] = (uint64_t)raw;
    return (void *)q;
}

static void *ff_resize(void *p, size_t old_n, size_t n) {
    char *b = (char *)p - 8;
    if (!(*(uint64_t *)((uint64_t *)p - 2) == FF_MAGIC) && ALIGN16(n + 8) <= bsize(b) && n + 8 >= bsize(b) / 2) return p;
    void *q = ff_alloc_raw(n);
    if (q) { memcpy(q, p, old_n < n ? old_n : n); ff_free(p); }
    return q;
}
static size_t ff_fp(void) { return ff_top; }

/* --------------------------------------------------------------------- buddy */

#define BD_MIN 5                               /* 32-byte blocks, 16 of them header */
#define BD_HDR 16
typedef struct BNode { uint32_t magic; uint8_t order, free; uint16_t pad; struct BNode *prev, *next; } BNode;
#define BD_FREE_MAGIC 0xB0DD1E5Fu
#define BD_USED_MAGIC 0xB0DD0CCDu
static Arena bd_a; static int bd_maxorder; static BNode *bd_free[64]; static size_t bd_extent;

static void bd_push(BNode *b, int order) {
    b->magic = BD_FREE_MAGIC; b->order = (uint8_t)order; b->free = 1;
    b->prev = NULL; b->next = bd_free[order];
    if (b->next) b->next->prev = b;
    bd_free[order] = b;
}
static void bd_pop(BNode *b) {
    if (b->prev) b->prev->next = b->next; else bd_free[b->order] = b->next;
    if (b->next) b->next->prev = b->prev;
    b->free = 0; b->magic = BD_USED_MAGIC;
}
static int bd_init(void) {
    memset(bd_free, 0, sizeof bd_free); bd_extent = 0;
    if (arena_open(&bd_a, 1UL << 36) < 0) return -1;
    bd_maxorder = 0; while ((1UL << (bd_maxorder + 1)) <= bd_a.cap) bd_maxorder++;
    bd_push((BNode *)bd_a.base, bd_maxorder);
    return 0;
}
static void bd_fini(void) { arena_close(&bd_a); }

static void *bd_alloc_raw(size_t n) {
    if (n > ((size_t)1 << bd_maxorder) - BD_HDR) return NULL;
    int order = BD_MIN;
    while (((size_t)1 << order) - BD_HDR < n) order++;
    int o = order;
    while (o <= bd_maxorder && !bd_free[o]) o++;
    if (o > bd_maxorder) return NULL;
    BNode *b = bd_free[o];
    bd_pop(b);
    while (o > order) {                          /* split, keeping the low half */
        o--;
        bd_push((BNode *)((char *)b + ((size_t)1 << o)), o);
    }
    b->order = (uint8_t)order;
    size_t end = (size_t)((char *)b - bd_a.base) + ((size_t)1 << order);
    if (end > bd_extent) bd_extent = end;
    return (char *)b + BD_HDR;
}
static void *bd_alloc(size_t n, int zero) {
    void *p = bd_alloc_raw(n);
    if (p && zero) memset(p, 0, n);
    return p;
}
static void bd_release(void *p) {
    BNode *b = (BNode *)((char *)p - BD_HDR);
    uint64_t *mag = (uint64_t *)p - 2;
    (void)mag;
    int order = b->order;
    while (order < bd_maxorder) {
        size_t off = (size_t)((char *)b - bd_a.base);
        BNode *bud = (BNode *)(bd_a.base + (off ^ ((size_t)1 << order)));
        if (bud->magic != BD_FREE_MAGIC || !bud->free || bud->order != order) break;
        bd_pop(bud);
        bud->magic = 0;
        if (bud < b) { b->magic = 0; b = bud; } else bud->magic = 0;
        order++;
    }
    bd_push(b, order);
}
static void *bd_aligned(size_t al, size_t n) {
    if (al <= 16) return bd_alloc_raw(n);
    /* a block of order k is aligned to 2^k, and its payload sits 16 bytes in: ask for a block
     * big enough that payload alignment al is met by returning an interior pointer with a
     * back pointer, exactly like the first-fit model. */
    size_t need = n + al + 32;
    char *raw = bd_alloc_raw(need);
    if (!raw) return NULL;
    uintptr_t q = ((uintptr_t)raw + 16 + al - 1) & ~(uintptr_t)(al - 1);
    uint64_t *mag = (uint64_t *)q - 2;
    mag[0] = FF_MAGIC; mag[1] = (uint64_t)(uintptr_t)raw;
    return (void *)q;
}
static void bd_free_any(void *p) {
    uint64_t *mag = (uint64_t *)p - 2;
    BNode *b = (BNode *)((char *)p - BD_HDR);
    if (b->magic != BD_USED_MAGIC && mag[0] == FF_MAGIC) { void *orig = (void *)mag[1]; mag[0] = 0; p = orig; }
    bd_release(p);
}
static void *bd_resize(void *p, size_t old_n, size_t n) {
    BNode *b = (BNode *)((char *)p - BD_HDR);
    if (b->magic == BD_USED_MAGIC && n + BD_HDR <= ((size_t)1 << b->order) && n + BD_HDR > ((size_t)1 << b->order) / 2) return p;
    void *q = bd_alloc_raw(n);
    if (q) { memcpy(q, p, old_n < n ? old_n : n); bd_free_any(p); }
    return q;
}
static size_t bd_fp(void) { return bd_extent; }

/* --------------------------------------------------------------------- glibc */

static int gl_init(void) { return 0; }
static void gl_fini(void) {}
static void *gl_alloc(size_t n, int zero) { return zero ? calloc(1, n) : malloc(n); }
static void *gl_aligned(size_t al, size_t n) { return memalign(al, n); }
static void gl_free(void *p) { free(p); }
static void *gl_resize(void *p, size_t old_n, size_t n) { (void)old_n; return realloc(p, n); }
static size_t gl_fp(void) { struct mallinfo2 m = mallinfo2(); return m.arena + m.hblkhd; }
static void gl_trim(void) { malloc_trim(0); }

/* -------------------------------------------------------------------- quarry */

static int qy_init(void) { return 0; }
static void qy_fini(void) {}
static void *qy_alloc(size_t n, int zero) { return zero ? q_calloc(1, n) : q_malloc(n); }
static void *qy_aligned(size_t al, size_t n) { return q_memalign(al, n); }
static void qy_free(void *p) { q_free(p); }
static void *qy_resize(void *p, size_t old_n, size_t n) { (void)old_n; return q_realloc(p, n); }
static size_t qy_fp(void) { return q_footprint(); }
static size_t qy_peak(void) { q_stats_t s; q_get_stats(&s); return s.peak_footprint_bytes; }
static void qy_trim(void) { q_trim(); }

static const Model m_quarry   = { "quarry",   "this repository: page heap + slab size classes + thread caches", qy_init, qy_fini, qy_alloc, qy_aligned, qy_free, qy_resize, qy_fp, qy_peak, qy_trim };
static const Model m_glibc    = { "glibc",    "system malloc (ptmalloc2), via mallinfo2", gl_init, gl_fini, gl_alloc, gl_aligned, gl_free, gl_resize, gl_fp, NULL, gl_trim };
static const Model m_firstfit = { "firstfit", "boundary tags, LIFO free list, first fit, immediate coalescing", ff_init, ff_fini, ff_alloc, ff_aligned, ff_free, ff_resize, ff_fp, NULL, NULL };
static const Model m_buddy    = { "buddy",    "binary buddy system (power-of-two blocks)", bd_init, bd_fini, bd_alloc, bd_aligned, bd_free_any, bd_resize, bd_fp, NULL, NULL };
static const Model m_bump     = { "bump",     "never frees (lower bound on time, upper bound on waste)", bump_init, bump_fini, bump_alloc, bump_aligned, bump_free, bump_resize, bump_fp, NULL, NULL };

const Model *const MODELS[] = { &m_quarry, &m_glibc, &m_firstfit, &m_buddy, &m_bump, NULL };

const Model *model_by_name(const char *name) {
    for (int i = 0; MODELS[i]; i++) if (!strcmp(MODELS[i]->name, name)) return MODELS[i];
    return NULL;
}
