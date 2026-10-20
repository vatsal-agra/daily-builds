/* Deliberately buggy programs for the debug-mode tests.  Usage: t_bugs <case>  */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <malloc.h>
#include <stdint.h>

extern int quarry_check_heap(void) __attribute__((weak));

static char *leaker(size_t n) { char *p = malloc(n); p[0] = 1; return p; }

int main(int argc, char **argv) {
    const char *c = argc > 1 ? argv[1] : "";
    volatile char *p;
    if (!strcmp(c, "clean")) {
        for (int i = 0; i < 1000; i++) { char *q = malloc(i + 1); memset(q, 1, i + 1); q = realloc(q, i * 3 + 5); free(q); }
        void *a = memalign(256, 100); if ((uintptr_t)a & 255) return 3; free(a);
        void *z = calloc(10, 10); for (int i = 0; i < 100; i++) if (((char *)z)[i]) return 4; free(z);
        puts("clean done");
    } else if (!strcmp(c, "overflow")) { p = malloc(100); p[100] = 'x'; free((void *)p);
    } else if (!strcmp(c, "overflow8")) { p = malloc(100); memset((void *)(p + 100), 'x', 8); free((void *)p);
    } else if (!strcmp(c, "underflow")) { p = malloc(100); p[-1] = 'x'; free((void *)p);
    } else if (!strcmp(c, "underflow3")) { p = malloc(100); p[-3] = 'x'; free((void *)p);
    } else if (!strcmp(c, "doublefree")) { p = malloc(50); free((void *)p); free((void *)p);
    } else if (!strcmp(c, "invalidfree")) { p = malloc(64); free((void *)(p + 8));
    } else if (!strcmp(c, "stackfree")) { char buf[64]; free(buf);
    } else if (!strcmp(c, "uaf")) { p = malloc(200); free((void *)p); p[10] = 'z'; for (int i = 0; i < 2000; i++) free(malloc(64)); 
        puts("after uaf");
    } else if (!strcmp(c, "uaf_read")) { p = malloc(8); strcpy((char *)p, "hello"); free((void *)p);
        printf("freed byte reads 0x%02x\n", (unsigned char)p[0]);
    } else if (!strcmp(c, "uninit")) { p = malloc(8); printf("fresh byte reads 0x%02x\n", (unsigned char)p[0]);
    } else if (!strcmp(c, "leak")) { for (int i = 0; i < 3; i++) leaker(100); leaker(5000); free(malloc(10));
    } else if (!strcmp(c, "noleak")) { free(leaker(10));
    } else if (!strcmp(c, "reallocoverflow")) { p = malloc(10); p = realloc((void *)p, 20); p[20] = 1; free((void *)p);
    } else if (!strcmp(c, "checkheap")) { p = malloc(30); p[30] = 1; int bad = quarry_check_heap ? quarry_check_heap() : -1; printf("bad=%d\n", bad);
    } else if (!strcmp(c, "align")) { p = memalign(4096, 10); p[10] = 1; free((void *)p);
    } else if (!strcmp(c, "usable")) { p = malloc(33); printf("usable=%zu\n", malloc_usable_size((void *)p)); free((void *)p);
    } else { fprintf(stderr, "unknown case\n"); return 2; }
    return 0;
}
