/* Heap-map sampling for qsim (and, later, the HTML report writer). */
#define _GNU_SOURCE
#include "qsim.h"
#include "quarry.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

static void sink_snap(FrameSink *fs, uint64_t ev, uint64_t live, uint64_t fp) {
    MapData *md = fs->md;
    if (md->nframes >= MAP_FRAMES) return;
    size_t top = q_top_pages();
    if (!top) return;
    q_page_info *pi = malloc(top * sizeof *pi);
    uint32_t *cnt = calloc((size_t)md->cells * 6, sizeof *cnt);   /* free, released, large, small, occsum, any */
    if (!pi || !cnt) { free(pi); free(cnt); return; }
    q_snapshot(pi, top);
    for (size_t pg = 0; pg < top; pg++) {
        size_t c = pg / (size_t)md->group;
        if (c >= (size_t)md->cells) c = (size_t)md->cells - 1;
        uint32_t *k = &cnt[c * 6];
        k[5]++;
        switch (pi[pg].state) {
        case Q_PG_FREE: k[0]++; break;
        case Q_PG_RELEASED: k[1]++; break;
        case Q_PG_LARGE: k[2]++; break;
        case Q_PG_SMALL: k[3]++; k[4] += pi[pg].occ; break;
        }
    }
    uint8_t *fr = md->frames + (size_t)md->nframes * (size_t)md->cells;
    for (int c = 0; c < md->cells; c++) {
        uint32_t *k = &cnt[(size_t)c * 6];
        uint8_t v = 0;
        if (k[5]) {
            if (k[2] >= k[0] && k[2] >= k[1] && k[2] >= k[3]) v = 3;
            else if (k[3] >= k[0] && k[3] >= k[1]) v = (uint8_t)(10 + (k[4] / k[3] + 5) / 10);
            else if (k[1] > k[0]) v = 2;
            else v = 1;
        }
        fr[c] = v;
    }
    md->pts[md->nframes].ev = ev; md->pts[md->nframes].live = live; md->pts[md->nframes].fp = fp;
    md->nframes++;
    free(pi); free(cnt);
}

void map_sink_init(FrameSink *fs, MapData *md, size_t nevents) {
    (void)nevents;
    uint64_t top = md->top_hint ? md->top_hint : 1024;
    int group = 1;
    while ((uint64_t)group * MAP_CELLS < top) group <<= 1;
    md->group = group;
    md->cells = (int)((top + (uint64_t)group - 1) / (uint64_t)group);
    if (md->cells < 1) md->cells = 1;
    md->nframes = 0;
    md->frames = calloc((size_t)MAP_FRAMES * (size_t)md->cells, 1);
    fs->snap = sink_snap; fs->md = md;
}

void map_sink_write(FrameSink *fs, FILE *f) {
    MapData *md = fs->md;
    fwrite(&md->group, sizeof md->group, 1, f);
    fwrite(&md->cells, sizeof md->cells, 1, f);
    fwrite(&md->nframes, sizeof md->nframes, 1, f);
    fwrite(md->pts, sizeof md->pts[0], (size_t)md->nframes, f);
    fwrite(md->frames, 1, (size_t)md->nframes * (size_t)md->cells, f);
}

void map_sink_read(MapData *md, FILE *f) {
    if (fread(&md->group, sizeof md->group, 1, f) != 1 || fread(&md->cells, sizeof md->cells, 1, f) != 1 ||
        fread(&md->nframes, sizeof md->nframes, 1, f) != 1) { md->nframes = 0; return; }
    if (md->nframes < 0 || md->nframes > MAP_FRAMES || md->cells < 1 || md->cells > MAP_CELLS) { md->nframes = 0; return; }
    if (fread(md->pts, sizeof md->pts[0], (size_t)md->nframes, f) != (size_t)md->nframes) { md->nframes = 0; return; }
    free(md->frames);
    md->frames = malloc((size_t)md->nframes * (size_t)md->cells + 1);
    if (fread(md->frames, 1, (size_t)md->nframes * (size_t)md->cells, f) != (size_t)md->nframes * (size_t)md->cells) md->nframes = 0;
}

int report_write(const char *out, const char *trace_path, const Trace *t, const TraceProfile *p,
                 const Row *rows, int nrows, const MapData *md) {
    (void)out; (void)trace_path; (void)t; (void)p; (void)rows; (void)nrows; (void)md;
    errno = ENOSYS;
    return -1;
}
