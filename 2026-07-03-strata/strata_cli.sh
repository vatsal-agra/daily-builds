#!/usr/bin/env bash
# Convenience wrapper: run `strata` from anywhere by sourcing this dir onto PYTHONPATH.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="$DIR:$PYTHONPATH" python3 -m strata "$@"
