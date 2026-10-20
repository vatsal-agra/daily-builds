/* Quarry allocator core — public API.
 *
 * Everything is prefixed q_ so the core can be linked into test programs and the
 * replay simulator next to the system malloc.  libquarry.so (quarry_preload.c)
 * exports the same functionality under the standard malloc names. */
#ifndef QUARRY_H
#define QUARRY_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define Q_PAGE_SIZE 4096UL
#define Q_MAX_SMALL 32768UL
#define Q_NCLASS 40

void *q_malloc(size_t n);
void  q_free(void *p);
void *q_calloc(size_t nmemb, size_t size);
void *q_realloc(void *p, size_t n);
void *q_memalign(size_t align, size_t n);          /* rounds align up to a power of two */
int   q_posix_memalign(void **out, size_t align, size_t n);
size_t q_usable_size(const void *p);               /* 0 for pointers we do not own */

/* Does p point into memory managed by this allocator? */
int q_owns(const void *p);

typedef enum {
    Q_FREE_OK = 0,
    Q_FREE_FOREIGN,   /* not ours */
    Q_FREE_BADPTR,    /* ours, but not the start of a live object */
    Q_FREE_DOUBLE     /* ours, object (or large span) is already free */
} q_free_status;

/* Fully validated free; slower than q_free (walks the span free list). */
q_free_status q_free_checked(void *p);

/* Give this thread's cached objects back to the shared lists. */
void q_thread_flush(void);
/* Flush this thread's cache and return every free page run to the OS. */
void q_trim(void);

typedef struct {
    size_t reserved_bytes;      /* size of the virtual reservation */
    size_t top_pages;           /* pages ever handed to the page heap */
    size_t free_pages;          /* pages in free spans (resident or not) */
    size_t released_pages;      /* subset of free_pages given back via madvise / never touched */
    size_t small_pages;         /* pages in slab spans */
    size_t large_pages;         /* pages in large allocations */
    size_t footprint_bytes;     /* (top - released) pages + allocator metadata */
    size_t peak_footprint_bytes;
    size_t meta_bytes;
    struct {
        uint32_t size;          /* object size of the class */
        uint32_t span_pages;    /* pages per slab */
        size_t   spans;         /* slabs of this class */
        size_t   objects;       /* objects those slabs can hold */
        size_t   inuse;         /* objects handed out (incl. in thread caches) */
    } cls[Q_NCLASS];
} q_stats_t;

void   q_get_stats(q_stats_t *out);
size_t q_class_size(int cls);               /* 0 if cls out of range */
size_t q_footprint(void);                   /* O(1) footprint_bytes */

/* One entry per page of the page heap, for heap maps. */
enum { Q_PG_FREE = 1, Q_PG_RELEASED = 2, Q_PG_LARGE = 3, Q_PG_SMALL = 4 };
typedef struct { uint8_t state; uint8_t occ; uint8_t cls; } q_page_info; /* occ: 0..100 slab fill */
size_t q_snapshot(q_page_info *out, size_t max_pages);  /* returns page count (top_pages) */
size_t q_top_pages(void);

#ifdef __cplusplus
}
#endif
#endif
