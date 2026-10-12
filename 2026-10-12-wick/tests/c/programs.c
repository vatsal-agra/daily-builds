/* Real-compiler workloads for Wick. Compiled twice: to wasm32 by clang (run on Wick and V8) and
 * natively by the host C compiler (reference answers). No libc: everything is self-contained. */
#ifdef __wasm__
#define EXPORT(n) __attribute__((export_name(n)))
#else
#define EXPORT(n)
#endif
typedef unsigned char u8; typedef unsigned int u32; typedef long long i64; typedef unsigned long long u64;

/* ---- prime sieve ---- */
static u8 sieve_buf[300000];
EXPORT("primes_below") int primes_below(int n) {
  if (n > 300000) n = 300000;
  for (int i = 0; i < n; i++) sieve_buf[i] = 1;
  int count = 0;
  for (int i = 2; i < n; i++) {
    if (sieve_buf[i]) { count++; for (i64 j = (i64)i * i; j < n; j += i) sieve_buf[j] = 0; }
  }
  return count;
}

/* ---- quicksort checksum over an LCG-generated array ---- */
static int qs_arr[20000];
static void qsort_i(int *a, int lo, int hi) {
  while (lo < hi) {
    int p = a[(lo + hi) / 2], i = lo, j = hi;
    while (i <= j) {
      while (a[i] < p) i++;
      while (a[j] > p) j--;
      if (i <= j) { int t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; }
    }
    if (j - lo < hi - i) { qsort_i(a, lo, j); lo = i; } else { qsort_i(a, i, hi); hi = j; }
  }
}
EXPORT("sort_checksum") int sort_checksum(int n) {
  if (n > 20000) n = 20000;
  u32 s = 12345;
  for (int i = 0; i < n; i++) { s = s * 1103515245u + 12345u; qs_arr[i] = (int)(s >> 8) % 100000 - 50000; }
  qsort_i(qs_arr, 0, n - 1);
  int ok = 1; u32 h = 2166136261u;
  for (int i = 0; i < n; i++) { if (i && qs_arr[i - 1] > qs_arr[i]) ok = 0; h = (h ^ (u32)qs_arr[i]) * 16777619u; }
  return ok ? (int)h : -1;
}

/* ---- collatz: longest chain start below n (64-bit arithmetic) ---- */
EXPORT("collatz_best") int collatz_best(int n) {
  int best = 1, best_len = 1;
  for (int s = 1; s < n; s++) {
    u64 x = (u64)s; int len = 1;
    while (x != 1) { x = (x & 1) ? 3 * x + 1 : x >> 1; len++; }
    if (len > best_len) { best_len = len; best = s; }
  }
  return best * 1000 + best_len % 1000;
}

/* ---- n-queens (recursion + bit tricks) ---- */
static int queens(int n, int row, u32 cols, u32 d1, u32 d2) {
  if (row == n) return 1;
  int cnt = 0;
  u32 avail = ~(cols | d1 | d2) & ((1u << n) - 1);
  while (avail) {
    u32 bit = avail & (0u - avail);
    avail ^= bit;
    cnt += queens(n, row + 1, cols | bit, (d1 | bit) << 1, (d2 | bit) >> 1);
  }
  return cnt;
}
EXPORT("nqueens") int nqueens(int n) { return queens(n, 0, 0, 0, 0); }

/* ---- double-precision matrix multiply + checksum ---- */
static double ma[32][32], mb[32][32], mc[32][32];
EXPORT("matmul_trace") double matmul_trace(int n) {
  if (n > 32) n = 32;
  for (int i = 0; i < n; i++) for (int j = 0; j < n; j++) { ma[i][j] = (i + 1) * 0.5 + j * 0.25; mb[i][j] = (i - j) * 0.125 + 1.0; }
  for (int i = 0; i < n; i++) for (int j = 0; j < n; j++) { double s = 0; for (int k = 0; k < n; k++) s += ma[i][k] * mb[k][j]; mc[i][j] = s; }
  double t = 0; for (int i = 0; i < n; i++) t += mc[i][i];
  return t;
}

/* ---- mandelbrot: total iterations over a grid ---- */
EXPORT("mandel_iters") int mandel_iters(int size) {
  int total = 0;
  for (int py = 0; py < size; py++) for (int px = 0; px < size; px++) {
    double cr = -2.0 + 3.0 * px / size, ci = -1.5 + 3.0 * py / size, zr = 0, zi = 0;
    int it = 0;
    while (it < 200 && zr * zr + zi * zi <= 4.0) { double t = zr * zr - zi * zi + cr; zi = 2 * zr * zi + ci; zr = t; it++; }
    total += it;
  }
  return total;
}

/* ---- 64-bit hashing / mixing ---- */
EXPORT("mix64") i64 mix64(int rounds) {
  u64 x = 88172645463325252ull, acc = 0;
  for (int i = 0; i < rounds; i++) {
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    acc += (x * 0x9E3779B97F4A7C15ull) >> 29;
    acc = (acc << 5) | (acc >> 59);
  }
  return (i64)acc;
}

/* ---- gcd / modular exponentiation ---- */
static u64 mulmod(u64 a, u64 b, u64 m) { u64 r = 0; a %= m; while (b) { if (b & 1) { r += a; if (r >= m) r -= m; } a <<= 1; if (a >= m) a -= m; b >>= 1; } return r; }
EXPORT("powmod") i64 powmod(int e) {
  u64 m = 1000000007ull, b = 3, r = 1; u64 ex = (u64)e;
  while (ex) { if (ex & 1) r = mulmod(r, b, m); b = mulmod(b, b, m); ex >>= 1; }
  return (i64)r;
}

/* ---- text processing: count words in a generated buffer, with signed/unsigned char tricks ---- */
static char text[4096];
EXPORT("word_count") int word_count(int n) {
  if (n > 4000) n = 4000;
  u32 s = 7;
  for (int i = 0; i < n; i++) { s = s * 1664525u + 1013904223u; text[i] = (char)((s >> 24) % 5 == 0 ? ' ' : 'a' + (s >> 16) % 26); }
  text[n] = 0;
  int words = 0, in = 0;
  for (int i = 0; i < n; i++) { if (text[i] == ' ') in = 0; else if (!in) { in = 1; words++; } }
  return words * 100 + (int)(text[n / 2] - 'a');
}

/* ---- float -> int conversions and rounding ---- */
EXPORT("float_mix") int float_mix(int n) {
  double acc = 0; float f = 0.1f;
  for (int i = 1; i <= n; i++) { acc += (double)(i % 7) / (double)i; f = f * 1.0001f + (float)i * 0.001f; }
  return (int)(acc * 1000) + (int)f + (int)(__builtin_sqrt(acc) * 100);
}

/* ---- struct copies / pointer-heavy linked list in static memory ---- */
typedef struct { int next; int val; } node;
static node nodes[5000];
EXPORT("list_sum") int list_sum(int n) {
  if (n > 5000) n = 5000;
  for (int i = 0; i < n; i++) { nodes[i].next = (i * 7 + 3) % n; nodes[i].val = i * 31 % 101; }
  int cur = 0, sum = 0;
  for (int steps = 0; steps < n * 3; steps++) { sum += nodes[cur].val; cur = nodes[cur].next; }
  return sum;
}
