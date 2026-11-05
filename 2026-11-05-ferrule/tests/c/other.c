static int counter = 7;                 /* same name as algo.c's static */
int shared_common;                      /* merges with algo.c's common */
int other_counter(void) { shared_common += 3; return counter * 2; }
int classify(int x) {
    switch (x) {
    case 0: return 10; case 1: return 11; case 2: return 25; case 3: return 31;
    case 4: return 47; case 5: return 52; case 6: return 68; default: return 99;
    }
}
