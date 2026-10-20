#ifndef QSIM_H
#define QSIM_H
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>
#include "models.h"

enum { EV_ALLOC = 1, EV_ZALLOC, EV_ALIGNED, EV_FREE, EV_REALLOC };
typedef struct { uint8_t op; uint32_t id; uint64_t size, align; } Ev;

typedef struct {
    Ev *ev; size_t n;
    uint32_t ids;
    size_t records, threads, truncated_bytes, unknown_frees, failed_allocs, implicit_frees, bad_records, live_at_end, oversized;
} Trace;

typedef struct {
    uint64_t allocs, callocs, aligned, reallocs, frees, freed;
    uint64_t total_bytes, max_size, peak_live, live_end;
    size_t peak_at;
    uint64_t size_hist[64];
    uint64_t life_p50, life_p90, life_p99;
} TraceProfile;

#define SERIES_POINTS 240
#define LAT_BUCKETS 256
enum { MODE_TIME = 0, MODE_MEASURE = 1 };
enum { RUN_OK = 1, RUN_INIT_FAILED, RUN_CRASHED };

typedef struct { uint64_t ev, live, fp; } SeriesPt;

typedef struct {
    int status, signal;
    uint64_t events, ns_total, peak_live, peak_fp, footprint_end, footprint_after_free, top_pages;
    uint64_t failed, corrupt, overlaps, misaligned, not_zeroed, reallocs_moved;
    uint64_t lat_alloc_p50, lat_alloc_p99, lat_alloc_max, lat_free_p50, lat_free_p99, lat_free_max;
    size_t nseries;
    SeriesPt series[SERIES_POINTS];
} RunResult;

/* Heap-map frames: one byte per cell. */
#define MAP_CELLS 4096
#define MAP_FRAMES 96
typedef struct {
    uint64_t top_hint;
    int group, cells, nframes;
    uint8_t *frames;                    /* nframes * cells */
    SeriesPt pts[MAP_FRAMES];
} MapData;

typedef struct FrameSink {
    void (*snap)(struct FrameSink *, uint64_t ev, uint64_t live, uint64_t fp);
    uint64_t (*top_pages)(void);
    MapData *md;
    int cap_frames;
} FrameSink;

typedef struct { const Model *m; RunResult time, meas; int crashed; } Row;

extern uint64_t g_max_size, g_max_live;   /* safety rails against hostile or corrupt traces */
Trace *trace_load(const char *path);
void trace_free(Trace *t);
TraceProfile trace_profile(const Trace *t);

void map_sink_init(FrameSink *fs, MapData *md, size_t nevents);
void map_sink_write(FrameSink *fs, FILE *f);
void map_sink_read(MapData *md, FILE *f);
int report_write(const char *out, const char *trace_path, const Trace *t, const TraceProfile *p,
                 const Row *rows, int nrows, const MapData *md);
#endif
