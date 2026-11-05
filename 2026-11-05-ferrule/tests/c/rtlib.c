#include "rtlib.h"
size_t rt_strlen(const char *s) { size_t n = 0; while (s[n]) n++; return n; }
void rt_puts(const char *s) { sys_write(1, s, rt_strlen(s)); }
void rt_putu(unsigned long v) {
    char tmp[24]; int n = 0;
    if (!v) tmp[n++] = '0';
    while (v) { tmp[n++] = '0' + v % 10; v /= 10; }
    char out[24]; int k = 0;
    while (n) out[k++] = tmp[--n];
    sys_write(1, out, k);
}
void rt_putnl(void) { sys_write(1, "\n", 1); }
