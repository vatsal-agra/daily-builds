CXX      ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -ffp-contract=off -Isrc
LIB_SRC  := src/predicates.cpp src/triangulation.cpp src/voronoi.cpp src/check.cpp src/io.cpp src/render.cpp
LIB_OBJ  := $(LIB_SRC:src/%.cpp=build/%.o)

all: build/sextant

build/%.o: src/%.cpp $(wildcard src/*.hpp)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build/sextant: $(LIB_OBJ) build/main.o
	$(CXX) $(CXXFLAGS) $^ -o $@

clean:
	rm -rf build
.PHONY: all clean
