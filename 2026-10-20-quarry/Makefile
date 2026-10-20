CC      ?= gcc
CFLAGS  ?= -O2 -g -Wall -Wextra -fno-strict-aliasing
LIBFLAGS = -fPIC -ftls-model=initial-exec -fvisibility=hidden
CORE     = src/quarry_core.c
HDRS     = src/quarry.h src/trace.h src/qsim.h src/models.h

BINS = build/libquarry.so build/qsim build/qgen build/t_api build/t_threads build/t_threads_pre \
       build/t_bugs build/t_misc

all: $(BINS)

build:
	mkdir -p build

build/libquarry.so: $(CORE) src/quarry_preload.c $(HDRS) | build
	$(CC) $(CFLAGS) $(LIBFLAGS) -shared -o $@ $(CORE) src/quarry_preload.c -pthread -ldl

build/qsim: src/qsim.c src/report.c src/models.c $(CORE) $(HDRS) | build
	$(CC) $(CFLAGS) -o $@ src/qsim.c src/report.c src/models.c $(CORE) -pthread -lm

build/qgen: src/qgen.c src/trace.h | build
	$(CC) $(CFLAGS) -o $@ src/qgen.c -lm

build/t_api: tests/t_api.c $(CORE) src/quarry.h tests/check.h | build
	$(CC) $(CFLAGS) -o $@ tests/t_api.c $(CORE) -pthread

build/t_threads: tests/t_threads.c $(CORE) src/quarry.h tests/check.h | build
	$(CC) $(CFLAGS) -DUSE_Q -o $@ tests/t_threads.c $(CORE) -pthread

build/t_threads_pre: tests/t_threads.c tests/check.h | build
	$(CC) $(CFLAGS) -o $@ tests/t_threads.c -pthread

build/t_bugs: tests/t_bugs.c | build
	$(CC) -O0 -g -rdynamic -w -o $@ tests/t_bugs.c

build/t_misc: tests/t_misc.c | build
	$(CC) -O1 -g -o $@ tests/t_misc.c -pthread

test: all
	bash tests/run_tests.sh

clean:
	rm -rf build

.PHONY: all test clean
