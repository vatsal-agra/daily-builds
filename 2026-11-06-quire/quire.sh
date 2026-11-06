#!/bin/sh
# convenience launcher:  ./quire.sh info file.pdf
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$DIR" exec python3 -m quire "$@"
