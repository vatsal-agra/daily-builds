# Graft

A version control system built from scratch in pure Python — content-addressable
object store, staging area, commit DAG, Myers diff, three-way merge and a
custom packfile format.

**Status: Phase 5 (verification) complete.** All 4 required features plus
all 3 stretch features work end-to-end, backed by 71 automated tests (unit,
fuzz, and differential-against-real-git) and a green `demo.sh` walkthrough.
See [PLAN.md](PLAN.md) for architecture and [REVIEW.md](REVIEW.md) for the
adversarial review (6 real issues found and fixed, several via differential
fuzzing against real git).

## Quick start

```sh
cd your-project
python3 /path/to/graft/bin/graft init .
python3 /path/to/graft/bin/graft add somefile.txt
python3 /path/to/graft/bin/graft commit -m "message"
python3 /path/to/graft/bin/graft log
```

Blob/tree/commit objects are byte-identical to real Git (verified via
subprocess differential tests against `git hash-object`/`git write-tree`,
and real `git cat-file` can read Graft's raw object files directly).

## Commands

`init`, `hash-object`, `cat-file`, `add`, `rm [--cached]`, `status`,
`commit -m`, `log [rev]`, `branch [name] [start] [-d name]`,
`checkout <target> [-f]`, `diff [--cached]`, `merge <branch>`, `gc`,
`viz [-o out.html]`.

## Testing

```sh
python3 -m unittest discover -s tests -p "test_*.py"   # 71 tests
./demo.sh                                               # runnable walkthrough
```

The test suite includes: unit tests for the object model; a differential
suite that shells out to real `git` to verify byte-identical object
encoding and tree hashing; a 3,000-trial fuzz test of the Myers diff engine
against a brute-force DP oracle; a 1,000-trial fuzz test of the three-way
merge against real `git merge-file`; packfile delta round-trip tests; and
20 CLI end-to-end tests exercising every command as a subprocess.
