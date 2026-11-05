#include "rtlib.h"
/* sieve in .bss, qsort via function pointer table, switch jump table, struct tables with pointers */
static unsigned char sieve[10000];
static int counter = 100;               /* static: name clashes with other TU */
int shared_common;                      /* -fcommon tentative definition */
struct entry { const char *name; int (*fn)(int); int weight; };
static int sq(int x) { return x * x; }
static int neg(int x) { return -x; }
static int ident(int x) { return x; }
static const struct entry entries[] = {
    {"square", sq, 3}, {"negate", neg, 5}, {"ident", ident, 7},
};
extern int other_counter(void);
extern int classify(int);
__attribute__((weak)) int optional_hook(void);
static void isort(int *a, int n, int (*cmp)(int, int)) {
    for (int i = 1; i < n; i++) {
        int v = a[i], j = i - 1;
        while (j >= 0 && cmp(a[j], v) > 0) { a[j + 1] = a[j]; j--; }
        a[j + 1] = v;
    }
}
static int by_value(int a, int b) { return a - b; }
static int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
int main(void) {
    int primes = 0;
    for (int i = 2; i < 10000; i++) sieve[i] = 1;
    for (int i = 2; i * i < 10000; i++) if (sieve[i]) for (int j = i * i; j < 10000; j += i) sieve[j] = 0;
    for (int i = 2; i < 10000; i++) primes += sieve[i];
    rt_puts("primes<10000: "); rt_putu(primes); rt_putnl();
    int arr[] = {9, 3, 7, 1, 8, 2, 6, 4, 5, 0};
    isort(arr, 10, by_value);
    for (int i = 0; i < 10; i++) rt_putu(arr[i]);
    rt_putnl();
    long total = 0;
    for (unsigned i = 0; i < sizeof entries / sizeof entries[0]; i++) {
        rt_puts(entries[i].name); rt_puts("="); rt_putu((unsigned long)(entries[i].fn(6) + 100)); rt_puts(" ");
        total += entries[i].weight;
    }
    rt_putnl();
    for (int i = 0; i < 8; i++) rt_putu(classify(i));
    rt_putnl();
    counter += other_counter();
    shared_common = 5;
    rt_puts("counter="); rt_putu(counter); rt_puts(" fib20="); rt_putu(fib(20));
    rt_puts(" hook="); rt_putu(optional_hook ? optional_hook() : 999); rt_putnl();
    unsigned long big = 0xFFFFFFFFFFFFFFFFUL;
    rt_putu(big / 7); rt_putnl();
    return (int)(total + shared_common);       /* 15 + 5 */
}
