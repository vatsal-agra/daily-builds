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

/* ---------------------------------------------------------------- HTML report */

extern const char _binary_report_tpl_html_start[], _binary_report_tpl_html_end[];

static void json_str(FILE *f, const char *s) {
    fputc('"', f);
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') fprintf(f, "\\%c", c);
        else if (c < 0x20 || c == '<' || c == '>' || c == '&') fprintf(f, "\\u%04x", c);   /* keeps "</script>" out of the page */
        else fputc(c, f);
    }
    fputc('"', f);
}

static void b64(FILE *f, const uint8_t *p, size_t n) {
    static const char T[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t i = 0;
    for (; i + 3 <= n; i += 3) {
        uint32_t v = (uint32_t)p[i] << 16 | (uint32_t)p[i + 1] << 8 | p[i + 2];
        fputc(T[v >> 18], f); fputc(T[(v >> 12) & 63], f); fputc(T[(v >> 6) & 63], f); fputc(T[v & 63], f);
    }
    if (n - i == 1) { uint32_t v = (uint32_t)p[i] << 16; fputc(T[v >> 18], f); fputc(T[(v >> 12) & 63], f); fputs("==", f); }
    else if (n - i == 2) { uint32_t v = (uint32_t)p[i] << 16 | (uint32_t)p[i + 1] << 8; fputc(T[v >> 18], f); fputc(T[(v >> 12) & 63], f); fputc(T[(v >> 6) & 63], f); fputc('=', f); }
}

static void write_data(FILE *f, const char *trace_path, const Trace *t, const TraceProfile *p,
                       const Row *rows, int nrows, const MapData *md) {
    fprintf(f, "{\"trace\":{\"path\":"); json_str(f, trace_path);
    fprintf(f, ",\"events\":%zu,\"threads\":%zu,\"peak_live\":%llu,\"total_bytes\":%llu,\"max_size\":%llu,\"allocs\":%llu,\"frees\":%llu,"
               "\"reallocs\":%llu,\"callocs\":%llu,\"aligned\":%llu,\"live_end\":%llu,\"life\":[%llu,%llu,%llu],\"size_hist\":[",
            t->n, t->threads, (unsigned long long)p->peak_live, (unsigned long long)p->total_bytes, (unsigned long long)p->max_size,
            (unsigned long long)p->allocs, (unsigned long long)p->frees, (unsigned long long)p->reallocs, (unsigned long long)p->callocs,
            (unsigned long long)p->aligned, (unsigned long long)p->live_end,
            (unsigned long long)p->life_p50, (unsigned long long)p->life_p90, (unsigned long long)p->life_p99);
    int first = 1;
    for (int i = 0; i < 64; i++) {
        if (!p->size_hist[i]) continue;
        fprintf(f, "%s[%llu,%llu]", first ? "" : ",", i ? 1ULL << i : 0ULL, (unsigned long long)p->size_hist[i]);
        first = 0;
    }
    fprintf(f, "]},\"allocs\":[");
    for (int i = 0; i < nrows; i++) {
        const Row *r = &rows[i];
        fprintf(f, "%s{\"name\":", i ? "," : ""); json_str(f, r->m->name);
        fprintf(f, ",\"desc\":"); json_str(f, r->m->desc);
        if (r->crashed) {
            fprintf(f, ",\"ok\":false,\"error\":\"the replay process crashed or could not start\"}");
            continue;
        }
        const RunResult *m = &r->meas;
        uint64_t bad = m->corrupt + m->overlaps + m->misaligned + m->not_zeroed;
        fprintf(f, ",\"ok\":true,\"peak\":%llu,\"end\":%llu,\"after\":%llu,\"overhead\":%.4f,\"ns_event\":%.2f,"
                   "\"alloc_p50\":%llu,\"alloc_p99\":%llu,\"free_p99\":%llu,\"bad\":%llu,\"series\":[",
                (unsigned long long)m->peak_fp, (unsigned long long)m->footprint_end, (unsigned long long)m->footprint_after_free,
                p->peak_live ? (double)m->peak_fp / (double)p->peak_live : 0.0, (double)r->time.ns_total / (double)(t->n ? t->n : 1),
                (unsigned long long)m->lat_alloc_p50, (unsigned long long)m->lat_alloc_p99, (unsigned long long)m->lat_free_p99,
                (unsigned long long)bad);
        for (size_t k = 0; k < m->nseries; k++)
            fprintf(f, "%s[%llu,%llu,%llu]", k ? "," : "", (unsigned long long)m->series[k].ev,
                    (unsigned long long)m->series[k].live, (unsigned long long)m->series[k].fp);
        fprintf(f, "]}");
    }
    fprintf(f, "],\"map\":");
    if (md && md->nframes > 0 && md->frames) {
        fprintf(f, "{\"group\":%d,\"cells\":%d,\"frames\":[", md->group, md->cells);
        for (int k = 0; k < md->nframes; k++)
            fprintf(f, "%s{\"ev\":%llu,\"live\":%llu,\"fp\":%llu}", k ? "," : "", (unsigned long long)md->pts[k].ev,
                    (unsigned long long)md->pts[k].live, (unsigned long long)md->pts[k].fp);
        fprintf(f, "],\"data\":\"");
        b64(f, md->frames, (size_t)md->nframes * (size_t)md->cells);
        fprintf(f, "\"}");
    } else fprintf(f, "null");
    fprintf(f, "}");
}

int report_write(const char *out, const char *trace_path, const Trace *t, const TraceProfile *p,
                 const Row *rows, int nrows, const MapData *md) {
    const char *tpl = _binary_report_tpl_html_start;
    size_t len = (size_t)(_binary_report_tpl_html_end - _binary_report_tpl_html_start);
    static const char mark[] = "__QUARRY_DATA__";
    const char *at = NULL;
    for (size_t i = 0; i + sizeof mark - 1 <= len; i++) if (!memcmp(tpl + i, mark, sizeof mark - 1)) { at = tpl + i; break; }
    if (!at) { errno = EINVAL; return -1; }
    FILE *f = fopen(out, "w");
    if (!f) return -1;
    fwrite(tpl, 1, (size_t)(at - tpl), f);
    write_data(f, trace_path, t, p, rows, nrows, md);
    fwrite(at + sizeof mark - 1, 1, len - (size_t)(at - tpl) - (sizeof mark - 1), f);
    if (fclose(f) != 0) return -1;
    return 0;
}
