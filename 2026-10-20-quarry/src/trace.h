/* Binary trace format shared by libquarry.so (writer), qgen (writer) and qsim (reader). */
#ifndef QUARRY_TRACE_H
#define QUARRY_TRACE_H
#include <stdint.h>
#include <inttypes.h>

#define QTR_MAGIC "QTRACE\x01\x00"
#define QTR_VERSION 1

enum { QTR_MALLOC = 1, QTR_FREE = 2, QTR_CALLOC = 3, QTR_REALLOC = 4, QTR_MEMALIGN = 5 };

typedef struct {
    char     magic[8];
    uint32_t version;
    uint32_t rec_size;
    uint64_t reserved[6];
} qtr_header;                /* 64 bytes */

/* One event.  ptr is the pointer returned (or freed); for REALLOC aux is the old pointer,
 * for MEMALIGN aux is the alignment.  size is the requested size (calloc: nmemb*size). */
typedef struct {
    uint8_t  op;
    uint8_t  pad[3];
    uint32_t tid;
    uint64_t ts_ns;
    uint64_t ptr;
    uint64_t size;
    uint64_t aux;
} qtr_rec;                   /* 40 bytes */

#endif
