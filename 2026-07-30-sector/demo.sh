#!/usr/bin/env bash
# End-to-end walkthrough of every Sector feature through the real CLI,
# cross-checked against real fsck.vfat/mkfs.vfat/mtools wherever they're
# installed. Exits non-zero (and prints which step failed) on any problem.
set -u
cd "$(dirname "$0")"

PASS=0
FAIL=0
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

check() {
    local desc="$1"; shift
    if "$@" >"$WORKDIR/last_stdout" 2>"$WORKDIR/last_stderr"; then
        echo "  [ok] $desc"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $desc"
        echo "         command: $*"
        sed 's/^/         stderr: /' "$WORKDIR/last_stderr"
        FAIL=$((FAIL + 1))
    fi
}

expect_fail() {
    local desc="$1"; shift
    if "$@" >"$WORKDIR/last_stdout" 2>"$WORKDIR/last_stderr"; then
        echo "  [FAIL] $desc (expected nonzero exit, got 0)"
        FAIL=$((FAIL + 1))
    else
        echo "  [ok] $desc"
        PASS=$((PASS + 1))
    fi
}

echo "== 1. Unit + integration test suite (unittest, incl. real fsck.vfat/mtools oracle checks) =="
check "full test suite (103 tests)" python3 -m unittest discover -s tests

echo
echo "== 2. mkfs produces a real, clean FAT16 image =="
IMG="$WORKDIR/demo.img"
check "sector mkfs" python3 -m sector.cli mkfs "$IMG" --size 4M --label DEMOVOL
if command -v fsck.vfat >/dev/null; then
    check "fsck.vfat accepts it" fsck.vfat -n "$IMG"
else
    echo "  [skip] fsck.vfat not installed"
fi

echo
echo "== 3. Directories, files, long file names =="
check "mkdir /docs" python3 -m sector.cli mkdir "$IMG" /docs
echo "hello from the sector demo" > "$WORKDIR/hello.txt"
check "cp-in a short-named file" python3 -m sector.cli cp-in "$IMG" "$WORKDIR/hello.txt" /docs/hello.txt
check "cp-in a long-named file (forces VFAT LFN entries)" \
    python3 -m sector.cli cp-in "$IMG" "$WORKDIR/hello.txt" "/docs/a genuinely long descriptive file name.txt"
head -c 3000000 /dev/urandom > "$WORKDIR/big.bin"
check "cp-in a multi-cluster file" python3 -m sector.cli cp-in "$IMG" "$WORKDIR/big.bin" /big.bin

echo
echo "== 4. Reading it all back =="
check "tree" python3 -m sector.cli tree "$IMG"
cat "$WORKDIR/last_stdout"
check "cat round-trips the short file" python3 -m sector.cli cat "$IMG" /docs/hello.txt
diff <(cat "$WORKDIR/last_stdout") "$WORKDIR/hello.txt" >/dev/null \
    && echo "  [ok] content byte-identical" && PASS=$((PASS+1)) \
    || { echo "  [FAIL] content mismatch"; FAIL=$((FAIL+1)); }
check "cp-out the big file" python3 -m sector.cli cp-out "$IMG" /big.bin "$WORKDIR/big_out.bin"
cmp "$WORKDIR/big.bin" "$WORKDIR/big_out.bin" \
    && echo "  [ok] multi-cluster file byte-identical" && PASS=$((PASS+1)) \
    || { echo "  [FAIL] multi-cluster file mismatch"; FAIL=$((FAIL+1)); }

echo
echo "== 5. Cross-tool verification (real mtools reading our image) =="
if command -v mdir >/dev/null; then
    check "mdir lists our directory" mdir -i "$IMG" ::docs
    check "mtype reads our short file" mtype -i "$IMG" ::docs/hello.txt
    check "mcopy extracts our big file" mcopy -i "$IMG" ::big.bin "$WORKDIR/big_via_mtools.bin"
    cmp "$WORKDIR/big.bin" "$WORKDIR/big_via_mtools.bin" \
        && echo "  [ok] mtools sees byte-identical content" && PASS=$((PASS+1)) \
        || { echo "  [FAIL] mtools content mismatch"; FAIL=$((FAIL+1)); }
else
    echo "  [skip] mtools not installed"
fi

echo
echo "== 6. Delete + free-space reclamation =="
check "info shows free space before delete" python3 -m sector.cli info "$IMG"
check "rm the big file" python3 -m sector.cli rm "$IMG" /big.bin
if command -v fsck.vfat >/dev/null; then
    check "fsck.vfat still clean after delete (no orphaned clusters)" fsck.vfat -n "$IMG"
fi
check "cat on the deleted file now fails" bash -c "! python3 -m sector.cli cat '$IMG' /big.bin"

echo
echo "== 7. HTML disk inspector =="
check "sector inspect" python3 -m sector.cli inspect "$IMG" --out "$WORKDIR/inspect.html"
if [ -s "$WORKDIR/inspect.html" ] && grep -q "Cluster allocation map" "$WORKDIR/inspect.html"; then
    echo "  [ok] report contains the expected sections"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] report missing expected content"
    FAIL=$((FAIL + 1))
fi

echo
echo "== 8. Clean error handling (no raw tracebacks) =="
expect_fail "mkfs with a too-small size" python3 -m sector.cli mkfs "$WORKDIR/toosmall.img" --size 1K
expect_fail "cat a missing image" python3 -m sector.cli cat "$WORKDIR/nope.img" /x
expect_fail "cat a missing file" python3 -m sector.cli cat "$IMG" /nosuchfile.txt
expect_fail "rm a non-empty directory" python3 -m sector.cli rm "$IMG" /docs
if grep -q "Traceback" "$WORKDIR/last_stderr"; then
    echo "  [FAIL] a raw Python traceback leaked to the user"
    FAIL=$((FAIL + 1))
else
    echo "  [ok] no raw traceback"
    PASS=$((PASS + 1))
fi

echo
echo "=================================================="
echo "demo.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
