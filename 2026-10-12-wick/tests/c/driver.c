#include <stdio.h>
#include "programs.c"
int main(void) {
  struct { const char *name; int args[4]; int nargs; int kind; } t[] = {
    {"primes_below", {10, 1000, 100000, 299999}, 4, 0},
    {"sort_checksum", {1, 100, 5000, 20000}, 4, 0},
    {"collatz_best", {10, 1000, 30000, 0}, 3, 0},
    {"nqueens", {4, 6, 8, 9}, 4, 0},
    {"matmul_trace", {1, 8, 17, 32}, 4, 2},
    {"mandel_iters", {8, 40, 100, 0}, 3, 0},
    {"mix64", {1, 100, 100000, 0}, 3, 1},
    {"powmod", {0, 1, 1000000, 2147483647}, 4, 1},
    {"word_count", {10, 500, 4000, 0}, 3, 0},
    {"float_mix", {1, 100, 10000, 0}, 3, 0},
    {"list_sum", {1, 50, 5000, 0}, 3, 0},
  };
  for (unsigned k = 0; k < sizeof t / sizeof t[0]; k++)
    for (int a = 0; a < t[k].nargs; a++) {
      int x = t[k].args[a];
      printf("%s %d => ", t[k].name, x);
#define CALL(n, fn) if (k == n) {
      switch (k) {
        case 0: printf("i32:%d\n", primes_below(x)); break;
        case 1: printf("i32:%d\n", sort_checksum(x)); break;
        case 2: printf("i32:%d\n", collatz_best(x)); break;
        case 3: printf("i32:%d\n", nqueens(x)); break;
        case 4: { double d = matmul_trace(x); unsigned long long b; __builtin_memcpy(&b, &d, 8); printf("f64:bits:0x%llx\n", b); break; }
        case 5: printf("i32:%d\n", mandel_iters(x)); break;
        case 6: printf("i64:%lld\n", mix64(x)); break;
        case 7: printf("i64:%lld\n", powmod(x)); break;
        case 8: printf("i32:%d\n", word_count(x)); break;
        case 9: printf("i32:%d\n", float_mix(x)); break;
        case 10: printf("i32:%d\n", list_sum(x)); break;
      }
    }
  return 0;
}
