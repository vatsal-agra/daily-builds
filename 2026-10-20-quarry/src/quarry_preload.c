/* libquarry.so — LD_PRELOAD front end for the Quarry core.
 *
 * Environment:
 *   QUARRY_DEBUG=1        headers, redzones, poisoning, quarantine, leak report
 *   QUARRY_ABORT=0        keep running after a heap error (default: abort)
 *   QUARRY_QUARANTINE=N   freed blocks kept poisoned before reuse (default 1024)
 *   QUARRY_LEAKS=0|all    disable the exit-time leak report / also list libc-internal blocks
 *   QUARRY_TRACE=path     record every allocation event (%p in path = pid)
 *   QUARRY_STATS=1        print allocator statistics at exit
 *   QUARRY_LOG=path       append reports to a file instead of stderr
 */
#define _GNU_SOURCE
#include "quarry.h"
#include "trace.h"

#include <dlfcn.h>
#include <link.h>
#include <stdarg.h>
#include <errno.h>
#include <execinfo.h>
#include <fcntl.h>
#include <malloc.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define EXPORT __attribute__((visibility("default")))

enum { M_DEBUG = 1, M_TRACE = 2, M_STATS = 4 };
static volatile int g_mode;                 /* fast path: 0 means straight to the core */
static int g_abort = 1, g_leaks = 1, g_leaks_all;
static size_t g_quarantine_max = 1024;
static int g_ready;

/* ------------------------------------------------------------------ messages */

/* Reports normally go to stderr.  Some programs (coreutils' close_stdout) close fd 2 in an atexit
 * handler that runs before ours, so a private duplicate is kept; QUARRY_LOG=file redirects to a file. */
static int g_log_fd = -1, g_saved_err = -1;

static void emit(const char *s, size_t n) {
    int fd = g_log_fd >= 0 ? g_log_fd : (fcntl(2, F_GETFD) >= 0 ? 2 : g_saved_err);
    if (fd < 0) return;
    while (n) { ssize_t w = write(fd, s, n); if (w <= 0) return; s += w; n -= (size_t)w; }
}
static void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void say(const char *fmt, ...) {
    char buf[1024];
    va_list ap; va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof buf - 1) n = sizeof buf - 1;
    if (n > 0) emit(buf, (size_t)n);
}

/* --------------------------------------------------------------- debug blocks */

#define HDR 192
#define TAIL 16
#define MAGIC_LIVE  0x51554152524C4956ULL   /* "QUARRLIV" */
#define MAGIC_FREED 0x5155415252465245ULL   /* "QUARRFRE" */
#define GUARD_BYTE  0xFD
#define TAIL_BYTE   0xBD
#define FILL_NEW    0xCD
#define FILL_FREED  0xDD
#define NA 10
#define NF 6

typedef struct Hdr {
    uint64_t magic;
    uint64_t size;
    uint64_t seq;
    void    *base;                           /* pointer returned by the core */
    struct Hdr *prev, *next;                 /* live list */
    uint32_t tid;
    uint16_t na, nf;
    void    *abt[NA];                        /* allocation stack */
    void    *fbt[NF];                        /* free stack */
    uint8_t  guard[8];                       /* directly before the user pointer */
} Hdr;
_Static_assert(sizeof(Hdr) == HDR, "header size");

static pthread_mutex_t dbg_lock = PTHREAD_MUTEX_INITIALIZER;
static Hdr *live_head;
static uint64_t g_seq, g_live_bytes, g_live_blocks;
static Hdr **quar;                            /* ring buffer */
static size_t quar_head, quar_n;
static size_t quar_cap;
static __thread int in_dbg;                   /* recursion guard (backtrace, dladdr) */
#define RAW_MAX 8192
static void *raw_blocks[RAW_MAX];             /* headerless blocks: made before init or while recursing */
static int raw_n, raw_overflow;

static inline Hdr *hdr_of(void *p) { return (Hdr *)((char *)p - HDR); }
static inline uint8_t *tail_of(Hdr *h) { return (uint8_t *)(h + 1) + h->size; }

static uint32_t gettid32(void) { return (uint32_t)syscall(SYS_gettid); }

static void print_frame(void *pc) {
    Dl_info di;
    if (dladdr(pc, &di) && di.dli_fname) {
        const char *base = strrchr(di.dli_fname, '/');
        base = base ? base + 1 : di.dli_fname;
        if (di.dli_sname)
            say("      %p  %s(%s+0x%lx)\n", pc, base, di.dli_sname, (unsigned long)((char *)pc - (char *)di.dli_saddr));
        else
            say("      %p  %s+0x%lx\n", pc, di.dli_fname, (unsigned long)((char *)pc - (char *)di.dli_fbase));
    } else say("      %p\n", pc);
}

static void print_stack(const char *title, void *const *bt, int n) {
    if (n <= 0) return;
    say("    %s:\n", title);
    for (int i = 0; i < n; i++) print_frame(bt[i]);
}

static int capture(void **out, int max);

static void describe(Hdr *h) {
    say("    block: %" PRIu64 " bytes, allocation #%" PRIu64 ", thread %u\n", h->size, h->seq, h->tid);
    print_stack("allocated at", h->abt, h->na);
    if (h->nf) print_stack("freed at", h->fbt, h->nf);
}

static void heap_error(const char *what, void *ptr, Hdr *h) {
    say("\n==quarry== ERROR: %s (pointer %p, pid %d)\n", what, ptr, (int)getpid());
    if (h) describe(h);
    void *bt[12]; int n = capture(bt, 12);
    print_stack("detected at", bt, n);
    if (g_abort) { say("==quarry== aborting\n"); abort(); }
}

/* Address range of libquarry.so itself, so its own frames can be left out of reports. */
static uintptr_t self_lo, self_hi;

static int find_self(struct dl_phdr_info *info, size_t size, void *data) {
    (void)size; (void)data;
    uintptr_t me = (uintptr_t)&find_self;
    for (int i = 0; i < info->dlpi_phnum; i++) {
        const ElfW(Phdr) *ph = &info->dlpi_phdr[i];
        if (ph->p_type != PT_LOAD) continue;
        uintptr_t lo = info->dlpi_addr + ph->p_vaddr, hi = lo + ph->p_memsz;
        if (me >= lo && me < hi) { self_lo = (uintptr_t)info->dlpi_addr; self_hi = hi + 0x100000; return 1; }
    }
    return 0;
}

static inline int in_self(void *pc) { return (uintptr_t)pc >= self_lo && (uintptr_t)pc < self_hi; }

/* Record up to `max` return addresses, starting at the first caller outside libquarry.so. */
static int capture(void **out, int max) {
    void *tmp[NA + 12];
    int n = backtrace(tmp, NA + 12), i = 0, k = 0;
    while (i < n && in_self(tmp[i])) i++;
    while (i < n && k < max) out[k++] = tmp[i++];
    return k;
}

/* Lock-free on purpose: it can be reached while dbg_lock is held (dladdr, backtrace). */
static void note_raw(void *p) {
    int i = __atomic_fetch_add(&raw_n, 1, __ATOMIC_RELAXED);
    if (i < RAW_MAX) __atomic_store_n(&raw_blocks[i], p, __ATOMIC_RELEASE); else raw_overflow = 1;
}

/* Only consulted when a block has no valid header, so the linear scan stays off the hot path. */
static int is_raw(void *p) {
    int n = __atomic_load_n(&raw_n, __ATOMIC_RELAXED);
    for (int i = 0; i < n && i < RAW_MAX; i++) if (__atomic_load_n(&raw_blocks[i], __ATOMIC_ACQUIRE) == p) return 1;
    return 0;
}

static int has_header(void *p, uint64_t magic) {
    return q_owns((char *)p - HDR) && hdr_of(p)->magic == magic;
}

static void *dbg_alloc(size_t n, size_t align, int zero) {
    if (align < 16) align = 16;
    if (n > (size_t)-1 - HDR - TAIL - 2 * align) { errno = ENOMEM; return NULL; }
    if (in_dbg) {                              /* an allocation made by backtrace()/dladdr() itself */
        void *p = q_malloc(n ? n : 1);
        if (zero && p) memset(p, 0, n);
        if (p) note_raw(p);
        return p;
    }
    in_dbg = 1;
    size_t total = HDR + n + TAIL + (align > 16 ? align : 0);
    char *raw = q_malloc(total);
    if (!raw) { in_dbg = 0; errno = ENOMEM; return NULL; }
    char *user = raw + HDR;
    if (align > 16) user = (char *)(((uintptr_t)raw + HDR + align - 1) & ~(uintptr_t)(align - 1));
    Hdr *h = hdr_of(user);
    h->magic = MAGIC_LIVE; h->size = n; h->base = raw;
    h->tid = gettid32();
    h->na = (uint16_t)capture(h->abt, NA); h->nf = 0;
    memset(h->guard, GUARD_BYTE, sizeof h->guard);
    memset(tail_of(h), TAIL_BYTE, TAIL);
    memset(user, zero ? 0 : FILL_NEW, n);
    pthread_mutex_lock(&dbg_lock);
    h->seq = ++g_seq;
    h->prev = NULL; h->next = live_head;
    if (live_head) live_head->prev = h;
    live_head = h;
    g_live_bytes += n; g_live_blocks++;
    pthread_mutex_unlock(&dbg_lock);
    in_dbg = 0;
    return user;
}

/* A header is trustworthy only if it still describes a region inside the block the core gave us;
 * otherwise tail_of() would point anywhere. */
static int header_sane(Hdr *h) {
    char *user = (char *)(h + 1);
    if (!q_owns(h->base) || (char *)h->base > (char *)h) return 0;
    size_t usable = q_usable_size(h->base), before = (size_t)(user - (char *)h->base);
    return before <= usable && h->size <= usable - before && usable - before - h->size >= TAIL;
}

/* Verify the redzones of a live block; returns 0 and reports on corruption. */
static int check_block(Hdr *h, void *user, const char *when) {
    char msg[160];
    if (!header_sane(h)) {
        snprintf(msg, sizeof msg, "heap corruption: the block header was overwritten (%s)", when);
        heap_error(msg, user, NULL);
        return 0;
    }
    int bad_guard = 0;
    for (int i = 0; i < 8; i++) bad_guard += h->guard[i] != GUARD_BYTE;
    if (bad_guard) {
        if (bad_guard == 8)
            snprintf(msg, sizeof msg, "heap buffer underflow: at least 8 bytes before the block were overwritten (%s)", when);
        else
            snprintf(msg, sizeof msg, "heap buffer underflow: %d byte%s before the block %s overwritten (%s)",
                     bad_guard, bad_guard == 1 ? "" : "s", bad_guard == 1 ? "was" : "were", when);
        heap_error(msg, user, h);
        return 0;
    }
    uint8_t *t = tail_of(h);
    for (int i = 0; i < TAIL; i++)
        if (t[i] != TAIL_BYTE) {
            int last = TAIL - 1;
            while (last > i && t[last] == TAIL_BYTE) last--;
            snprintf(msg, sizeof msg, "heap buffer overflow: %d byte%s written past the end of the block (%s)",
                     last + 1, last ? "s" : "", when);
            heap_error(msg, user, h);
            return 0;
        }
    return 1;
}

static void quarantine_check(Hdr *h) {       /* poison must be intact when a block leaves quarantine */
    uint8_t *user = (uint8_t *)(h + 1);
    if (!header_sane(h)) { heap_error("use after free: the header of a freed block was overwritten", user, NULL); return; }
    for (size_t i = 0; i < h->size; i++)
        if (user[i] != FILL_FREED) {
            char msg[160];
            snprintf(msg, sizeof msg, "use after free: byte %zu of a freed block was modified", i);
            heap_error(msg, user, h);
            break;
        }
    uint8_t *t = tail_of(h);
    for (int i = 0; i < TAIL; i++)
        if (t[i] != TAIL_BYTE) { heap_error("heap buffer overflow into a freed block's redzone", user, h); break; }
}

static void dbg_free(void *p) {
    if (!p) return;
    if (!q_owns(p)) {
        heap_error("free() of a pointer that was not returned by malloc", p, NULL);
        return;
    }
    if (has_header(p, MAGIC_FREED)) { heap_error("double free", p, hdr_of(p)); return; }
    if (!has_header(p, MAGIC_LIVE)) {
        if (is_raw(p)) { q_free(p); return; }
        if (raw_overflow) { q_free(p); return; }   /* cannot tell; stay quiet rather than cry wolf */
        heap_error("invalid free(): pointer is not the start of an allocation (or its header is corrupted)", p, NULL);
        return;
    }
    Hdr *h = hdr_of(p);
    in_dbg = 1;
    if (!check_block(h, p, "found at free()")) { in_dbg = 0; return; }
    h->nf = (uint16_t)capture(h->fbt, NF);
    in_dbg = 0;
    memset(p, FILL_FREED, h->size);
    Hdr *evict = NULL;
    pthread_mutex_lock(&dbg_lock);
    if (h->prev) h->prev->next = h->next; else live_head = h->next;
    if (h->next) h->next->prev = h->prev;
    g_live_bytes -= h->size; g_live_blocks--;
    h->magic = MAGIC_FREED;
    if (quar_cap) {
        if (quar_n == quar_cap) { evict = quar[quar_head]; quar[quar_head] = h; quar_head = (quar_head + 1) % quar_cap; }
        else { quar[(quar_head + quar_n) % quar_cap] = h; quar_n++; }
    } else evict = h;
    pthread_mutex_unlock(&dbg_lock);
    if (evict) {
        quarantine_check(evict);
        evict->magic = 0;
        q_free(evict->base);
    }
}

static size_t dbg_usable(void *p) {
    if (!q_owns(p)) return 0;
    if (has_header(p, MAGIC_LIVE)) return (size_t)hdr_of(p)->size;
    return is_raw(p) || raw_overflow ? q_usable_size(p) : 0;
}

/* Walk every live block and verify its redzones (public: quarry_check_heap). */
EXPORT int quarry_check_heap(void) {
    if (!(g_mode & M_DEBUG)) return 0;
    int bad = 0;
    int saved = g_abort; g_abort = 0;
    pthread_mutex_lock(&dbg_lock);
    in_dbg = 1;
    for (Hdr *h = live_head; h; h = h->next) if (!check_block(h, (char *)(h + 1), "found by quarry_check_heap")) bad++;
    for (size_t i = 0; i < quar_n; i++) {
        Hdr *h = quar[(quar_head + i) % quar_cap];
        uint8_t *user = (uint8_t *)(h + 1);
        for (size_t j = 0; j < h->size; j++) if (user[j] != FILL_FREED) { bad++; heap_error("use after free (found by quarry_check_heap)", user, h); break; }
    }
    in_dbg = 0;
    pthread_mutex_unlock(&dbg_lock);
    g_abort = saved;
    return bad;
}

/* ---------------------------------------------------------------- leak report */

typedef struct { void *bt[NA]; int n; size_t count, bytes; } Group;

/* libc keeps stdio buffers, locale tables and atexit records until the process dies; they are
 * not leaks.  Hidden unless QUARRY_LEAKS=all. */
static int libc_internal(Hdr *h) {
    static const char *const pre[] = { "_IO_", "__libc_", "_dl_", "__new_exitfn", "_nl_", "__cxa_", "__GI_", "__fopen", NULL };
    if (!h->na) return 0;
    Dl_info di;
    if (!dladdr(h->abt[0], &di) || !di.dli_sname || !di.dli_fname) return 0;
    if (!strstr(di.dli_fname, "libc.so") && !strstr(di.dli_fname, "ld-linux")) return 0;
    for (int i = 0; pre[i]; i++) if (!strncmp(di.dli_sname, pre[i], strlen(pre[i]))) return 1;
    return 0;
}

static void leak_report(void) {
    pthread_mutex_lock(&dbg_lock);
    size_t blocks = 0, bytes = 0, ngroups = 0, cap = 64;
    Group *groups = q_calloc(cap, sizeof(Group));
    in_dbg = 1;
    size_t hidden = 0;
    for (Hdr *h = live_head; h; h = h->next) {
        if (!g_leaks_all && libc_internal(h)) { hidden++; continue; }
        blocks++; bytes += h->size;
        size_t i;
        for (i = 0; i < ngroups; i++)
            if (groups[i].n == h->na && memcmp(groups[i].bt, h->abt, h->na * sizeof(void *)) == 0) break;
        if (i == ngroups) {
            if (ngroups == cap) {
                Group *g2 = q_realloc(groups, cap * 2 * sizeof(Group));
                if (!g2) break;
                groups = g2; cap *= 2;
                memset(groups + ngroups, 0, (cap - ngroups) * sizeof(Group));
            }
            groups[ngroups].n = h->na; memcpy(groups[ngroups].bt, h->abt, h->na * sizeof(void *));
            ngroups++;
        }
        groups[i].count++; groups[i].bytes += h->size;
    }
    if (blocks) {
        for (size_t i = 1; i < ngroups; i++) {          /* insertion sort, largest first */
            Group t = groups[i]; size_t j = i;
            while (j > 0 && groups[j - 1].bytes < t.bytes) { groups[j] = groups[j - 1]; j--; }
            groups[j] = t;
        }
        say("\n==quarry== LEAK SUMMARY: %zu block%s, %zu byte%s still allocated at exit (%zu distinct stack%s)\n",
            blocks, blocks == 1 ? "" : "s", bytes, bytes == 1 ? "" : "s", ngroups, ngroups == 1 ? "" : "s");
        for (size_t i = 0; i < ngroups && i < 20; i++) {
            say("  %zu byte%s in %zu block%s allocated at:\n", groups[i].bytes, groups[i].bytes == 1 ? "" : "s",
                groups[i].count, groups[i].count == 1 ? "" : "s");
            for (int k = 0; k < groups[i].n; k++) print_frame(groups[i].bt[k]);
        }
        if (ngroups > 20) say("  ... and %zu more stack%s\n", ngroups - 20, ngroups - 20 == 1 ? "" : "s");
    } else say("==quarry== no leaks: every allocation was freed\n");
    if (hidden) say("==quarry== (%zu libc-internal block%s not shown; QUARRY_LEAKS=all lists them)\n", hidden, hidden == 1 ? "" : "s");
    in_dbg = 0;
    q_free(groups);
    pthread_mutex_unlock(&dbg_lock);
}

/* --------------------------------------------------------------------- trace */

static pthread_mutex_t tr_lock = PTHREAD_MUTEX_INITIALIZER;
static int tr_fd = -1;
static qtr_rec tr_buf[2048];
static size_t tr_n;
static uint64_t tr_t0;

static uint64_t now_ns(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static void tr_flush_locked(void) {
    const char *p = (const char *)tr_buf; size_t n = tr_n * sizeof(qtr_rec);
    while (n && tr_fd >= 0) { ssize_t w = write(tr_fd, p, n); if (w <= 0) break; p += w; n -= (size_t)w; }
    tr_n = 0;
}

static void tr_emit_locked(int op, void *ptr, size_t size, uint64_t aux) {
    if (tr_fd < 0) return;
    qtr_rec *r = &tr_buf[tr_n++];
    r->op = (uint8_t)op; r->pad[0] = r->pad[1] = r->pad[2] = 0;
    r->tid = gettid32(); r->ts_ns = now_ns() - tr_t0;
    r->ptr = (uint64_t)(uintptr_t)ptr; r->size = size; r->aux = aux;
    if (tr_n == sizeof tr_buf / sizeof tr_buf[0]) tr_flush_locked();
}

/* The first process that sees QUARRY_TRACE owns the path; every descendant (shell pipelines, make,
 * compilers...) inherits QUARRY_TRACE_OWNER and writes "<path>.<pid>" instead of truncating it. */
static void tr_open(const char *path) {
    char name[512];
    const char *pp = strstr(path, "%p");
    if (pp) snprintf(name, sizeof name, "%.*s%d%s", (int)(pp - path), path, (int)getpid(), pp + 2);
    else if (getenv("QUARRY_TRACE_OWNER")) snprintf(name, sizeof name, "%s.%d", path, (int)getpid());
    else { snprintf(name, sizeof name, "%s", path); char own[24]; snprintf(own, sizeof own, "%d", (int)getpid()); setenv("QUARRY_TRACE_OWNER", own, 1); }
    tr_fd = open(name, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (tr_fd < 0) { say("quarry: cannot open trace file %s: %s\n", name, strerror(errno)); return; }
    qtr_header hd; memset(&hd, 0, sizeof hd);
    memcpy(hd.magic, QTR_MAGIC, 8); hd.version = QTR_VERSION; hd.rec_size = sizeof(qtr_rec);
    if (write(tr_fd, &hd, sizeof hd) != (ssize_t)sizeof hd) { close(tr_fd); tr_fd = -1; return; }
    tr_t0 = now_ns();
}

static void tr_close(void) {
    pthread_mutex_lock(&tr_lock);
    tr_flush_locked();
    if (tr_fd >= 0) close(tr_fd);
    tr_fd = -1;
    pthread_mutex_unlock(&tr_lock);
}

/* ------------------------------------------------------------- stats at exit */

static uint64_t c_malloc, c_free, c_calloc, c_realloc, c_memalign;

static void print_stats(void) {
    q_stats_t st; q_get_stats(&st);
    say("\n==quarry== STATISTICS (pid %d)\n", (int)getpid());
    if (g_mode & M_STATS)
        say("  calls: malloc %lu  free %lu  calloc %lu  realloc %lu  memalign %lu\n",
            (unsigned long)c_malloc, (unsigned long)c_free, (unsigned long)c_calloc,
            (unsigned long)c_realloc, (unsigned long)c_memalign);
    say("  address space reserved %zu MiB; heap grew to %zu KiB (%zu pages)\n",
        st.reserved_bytes >> 20, (st.top_pages * Q_PAGE_SIZE) >> 10, st.top_pages);
    say("  footprint now %zu KiB, peak %zu KiB (metadata %zu KiB)\n",
        st.footprint_bytes >> 10, st.peak_footprint_bytes >> 10, st.meta_bytes >> 10);
    say("  pages: %zu small, %zu large, %zu free (%zu of those not resident)\n",
        st.small_pages, st.large_pages, st.free_pages, st.released_pages);
    say("  class   size  slab(pg)   spans   in-use / capacity   fill\n");
    for (int c = 0; c < Q_NCLASS; c++) {
        if (!st.cls[c].spans) continue;
        say("  %5d %6u %9u %7zu %9zu / %-9zu %4zu%%\n", c, st.cls[c].size, st.cls[c].span_pages,
            st.cls[c].spans, st.cls[c].inuse, st.cls[c].objects,
            st.cls[c].objects ? 100 * st.cls[c].inuse / st.cls[c].objects : 0);
    }
}

static void at_exit_report(void) {
    if (g_mode & M_DEBUG) {
        if (g_leaks) leak_report();
        int bad = quarry_check_heap();
        if (bad) say("==quarry== %d corrupted block%s found at exit\n", bad, bad == 1 ? "" : "s");
    }
    if (g_mode & M_STATS) print_stats();
    if (tr_fd >= 0) tr_close();
}

static void fork_child(void) {
    /* The child gets a private copy of the heap, so its events would be meaningless in the
     * parent's trace; stop tracing there.  Reset locks that other (now absent) threads held. */
    pthread_mutex_init(&tr_lock, NULL);
    pthread_mutex_init(&dbg_lock, NULL);
    tr_n = 0; tr_fd = -1;
    g_mode &= ~M_TRACE;
}
static void fork_prepare(void) { pthread_mutex_lock(&tr_lock); tr_flush_locked(); pthread_mutex_unlock(&tr_lock); }

__attribute__((constructor(101))) static void quarry_init(void) {
    if (g_ready) return;
    g_ready = 1;
    const char *e;
    int mode = 0;
    q_free(q_malloc(1));                      /* bring the core up before anything can recurse */
    dl_iterate_phdr(find_self, NULL);
    g_saved_err = fcntl(2, F_DUPFD_CLOEXEC, 64);
    if ((e = getenv("QUARRY_LOG")) && *e) g_log_fd = open(e, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    if ((e = getenv("QUARRY_ABORT")) && *e == '0') g_abort = 0;
    if ((e = getenv("QUARRY_LEAKS"))) { if (*e == '0') g_leaks = 0; else if (!strcmp(e, "all")) g_leaks_all = 1; }
    if ((e = getenv("QUARRY_QUARANTINE"))) g_quarantine_max = (size_t)strtoul(e, NULL, 10);
    if ((e = getenv("QUARRY_DEBUG")) && *e && *e != '0') {
        void *warm[4];
        in_dbg = 1; backtrace(warm, 4); Dl_info di; dladdr((void *)quarry_init, &di); in_dbg = 0;
        quar_cap = g_quarantine_max;
        if (quar_cap) quar = q_calloc(quar_cap, sizeof(Hdr *));
        if (!quar) quar_cap = 0;
        mode |= M_DEBUG;
    }
    if ((e = getenv("QUARRY_STATS")) && *e && *e != '0') mode |= M_STATS;
    if ((e = getenv("QUARRY_TRACE")) && *e) { tr_open(e); if (tr_fd >= 0) mode |= M_TRACE; }
    if (mode) {
        pthread_atfork(fork_prepare, NULL, fork_child);
        atexit(at_exit_report);
    }
    g_mode = mode;
}

/* ------------------------------------------------------------- slow-path ops */

#define TR_BEGIN() int tr = g_mode & M_TRACE; if (tr) pthread_mutex_lock(&tr_lock)
#define TR_END(op, ptr, size, aux) do { if (tr) { if (g_mode & M_TRACE) tr_emit_locked(op, ptr, size, aux); pthread_mutex_unlock(&tr_lock); } } while (0)

static void *slow_malloc(size_t n) {
    if (in_dbg) return dbg_alloc(n, 16, 0);
    TR_BEGIN();
    void *p = (g_mode & M_DEBUG) ? dbg_alloc(n, 16, 0) : q_malloc(n);
    TR_END(QTR_MALLOC, p, n, 0);
    if (g_mode & M_STATS) __atomic_fetch_add(&c_malloc, 1, __ATOMIC_RELAXED);
    return p;
}

static void slow_free(void *p) {
    if (!p) return;
    if (in_dbg) { dbg_free(p); return; }
    TR_BEGIN();
    if (tr && g_mode & M_TRACE) tr_emit_locked(QTR_FREE, p, 0, 0);
    if (g_mode & M_DEBUG) dbg_free(p); else q_free(p);
    if (tr) pthread_mutex_unlock(&tr_lock);
    if (g_mode & M_STATS) __atomic_fetch_add(&c_free, 1, __ATOMIC_RELAXED);
}

static void *slow_calloc(size_t a, size_t b) {
    size_t n;
    if (__builtin_mul_overflow(a, b, &n)) { errno = ENOMEM; return NULL; }
    if (in_dbg) return dbg_alloc(n, 16, 1);
    TR_BEGIN();
    void *p = (g_mode & M_DEBUG) ? dbg_alloc(n, 16, 1) : q_calloc(a, b);
    TR_END(QTR_CALLOC, p, n, 0);
    if (g_mode & M_STATS) __atomic_fetch_add(&c_calloc, 1, __ATOMIC_RELAXED);
    return p;
}

static void *dbg_realloc(void *old, size_t n) {
    if (!old) return dbg_alloc(n, 16, 0);
    size_t osz = dbg_usable(old);
    if (osz == 0 && q_usable_size(old) == 0) { dbg_free(old); return NULL; }   /* diagnose, then fail */
    if (osz == 0) osz = q_usable_size(old);
    void *p = dbg_alloc(n, 16, 0);
    if (p) { memcpy(p, old, osz < n ? osz : n); dbg_free(old); }
    return p;
}

static void *slow_realloc(void *old, size_t n) {
    if (in_dbg) return dbg_realloc(old, n);
    TR_BEGIN();
    void *p = (g_mode & M_DEBUG) ? dbg_realloc(old, n) : q_realloc(old, n);
    TR_END(QTR_REALLOC, p, n, (uint64_t)(uintptr_t)old);
    if (g_mode & M_STATS) __atomic_fetch_add(&c_realloc, 1, __ATOMIC_RELAXED);
    return p;
}

static void *slow_memalign(size_t align, size_t n) {
    if (in_dbg) return dbg_alloc(n, align < 16 ? 16 : align, 0);
    TR_BEGIN();
    void *p;
    if (g_mode & M_DEBUG) {
        if (align & (align - 1)) { size_t a = 16; while (a < align && a) a <<= 1; align = a; }
        p = dbg_alloc(n, align, 0);
    } else p = q_memalign(align, n);
    TR_END(QTR_MEMALIGN, p, n, align);
    if (g_mode & M_STATS) __atomic_fetch_add(&c_memalign, 1, __ATOMIC_RELAXED);
    return p;
}

/* ---------------------------------------------------------- exported symbols */

/* Blocks handed out before the constructor ran have no debug header; remember them. */
static inline void *early(void *p) {
    if (__builtin_expect(!g_ready && p, 0)) note_raw(p);
    return p;
}

EXPORT void *malloc(size_t n) {
    if (__builtin_expect(g_mode == 0, 1)) return early(q_malloc(n));
    return slow_malloc(n);
}
EXPORT void free(void *p) {
    if (__builtin_expect(g_mode == 0, 1)) { q_free(p); return; }
    slow_free(p);
}
EXPORT void *calloc(size_t a, size_t b) {
    if (__builtin_expect(g_mode == 0, 1)) return early(q_calloc(a, b));
    return slow_calloc(a, b);
}
EXPORT void *realloc(void *p, size_t n) {
    if (__builtin_expect(g_mode == 0, 1)) return early(q_realloc(p, n));
    return slow_realloc(p, n);
}
EXPORT void *memalign(size_t align, size_t n) {
    if (__builtin_expect(g_mode == 0, 1)) return early(q_memalign(align, n));
    return slow_memalign(align, n);
}
EXPORT int posix_memalign(void **out, size_t align, size_t n) {
    if (align < sizeof(void *) || (align & (align - 1))) return EINVAL;
    void *p = memalign(align, n);
    if (!p) return ENOMEM;
    *out = p;
    return 0;
}
EXPORT void *aligned_alloc(size_t align, size_t n) {
    if (align == 0 || (align & (align - 1))) { errno = EINVAL; return NULL; }
    return memalign(align, n);
}
EXPORT void *valloc(size_t n) { return memalign(Q_PAGE_SIZE, n); }
EXPORT void *pvalloc(size_t n) { return memalign(Q_PAGE_SIZE, (n + Q_PAGE_SIZE - 1) & ~(Q_PAGE_SIZE - 1)); }
EXPORT size_t malloc_usable_size(void *p) {
    if (!p) return 0;
    if (g_mode & M_DEBUG) return dbg_usable(p);
    return q_usable_size(p);
}
EXPORT void cfree(void *p) { free(p); }
EXPORT int mallopt(int param, int value) { (void)param; (void)value; return 1; }
EXPORT int malloc_trim(size_t pad) { (void)pad; q_trim(); return 1; }
EXPORT void malloc_stats(void) { print_stats(); }
EXPORT struct mallinfo2 mallinfo2(void) {
    struct mallinfo2 m; memset(&m, 0, sizeof m);
    q_stats_t st; q_get_stats(&st);
    m.arena = st.footprint_bytes;
    m.uordblks = (st.small_pages + st.large_pages) * Q_PAGE_SIZE;
    m.fordblks = (st.free_pages - st.released_pages) * Q_PAGE_SIZE;
    return m;
}
EXPORT struct mallinfo mallinfo(void) {
    struct mallinfo m; memset(&m, 0, sizeof m);
    struct mallinfo2 m2 = mallinfo2();
    m.arena = (int)m2.arena; m.uordblks = (int)m2.uordblks; m.fordblks = (int)m2.fordblks;
    return m;
}
EXPORT void quarry_stats(void) { print_stats(); }
