#include "strx.h"
int vowels(const char *s) {
    int n = 0;
    for (; *s; s++)
        if (*s == 'a' || *s == 'e' || *s == 'i' || *s == 'o' || *s == 'u') n++;
    return n;
}
