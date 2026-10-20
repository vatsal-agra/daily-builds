/* Process-level behaviour under LD_PRELOAD: fork with live threads, exec, signals-free exit paths. */
#define _GNU_SOURCE
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static void *spin(void *a) {
    (void)a;
    for (int i = 0; i < 200000; i++) { void *p = malloc(32 + i % 300); memset(p, 7, 32); free(p); }
    return NULL;
}

int main(void) {
    pthread_t th[4];
    for (int i = 0; i < 4; i++) pthread_create(&th[i], NULL, spin, NULL);
    for (int round = 0; round < 40; round++) {              /* fork while other threads hammer malloc */
        pid_t pid = fork();
        if (pid == 0) {
            char *v[64];
            for (int i = 0; i < 64; i++) { v[i] = malloc(100 + i); memset(v[i], i, 100); }
            for (int i = 0; i < 64; i++) free(v[i]);
            _exit(0);
        }
        int st; waitpid(pid, &st, 0);
        if (!WIFEXITED(st) || WEXITSTATUS(st)) { puts("child failed"); return 1; }
    }
    for (int i = 0; i < 4; i++) pthread_join(th[i], NULL);
    char *buf = strdup("hello"); free(buf);
    char *s; if (asprintf(&s, "%d-%s", 42, "x") < 0) return 1; if (strcmp(s, "42-x")) return 1; free(s);
    void *z = calloc(1 << 20, 4); if (!z) return 1; free(z);
    printf("misc ok\n");
    return 0;
}
