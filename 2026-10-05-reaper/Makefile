CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter
SRC := $(filter-out src/main.cpp,$(wildcard src/*.cpp))
OBJ := $(SRC:src/%.cpp=build/%.o)

all: reaper

build/%.o: src/%.cpp $(wildcard src/*.hpp)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -c $< -o $@

reaper: $(OBJ) build/main.o
	$(CXX) $(CXXFLAGS) $^ -o $@

build/main.o: src/main.cpp $(wildcard src/*.hpp)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build/test: $(OBJ) tests/test.cpp
	$(CXX) $(CXXFLAGS) -Isrc $^ -o $@

test: build/test
	./build/test

clean:
	rm -rf build reaper

.PHONY: all test clean
