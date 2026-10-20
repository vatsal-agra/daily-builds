#ifndef CHECK_H
#define CHECK_H
#include <stdio.h>
#include <stdlib.h>
static int g_checks, g_fails;
#define CHECK(cond) do { g_checks++; if (!(cond)) { g_fails++; \
    fprintf(stderr, "  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define TEST_DONE(name) do { printf("%s: %d checks, %d failures\n", name, g_checks, g_fails); \
    return g_fails ? 1 : 0; } while (0)
#endif
