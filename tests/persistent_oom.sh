#!/bin/sh
# tests/persistent_oom.sh: ビルド済みPHPソースのinline allocatorを単独で検証する。
set -eu
source_root=$(readlink -f "${1:?Usage: tests/persistent_oom.sh /configured/php/source}")
test -f "$source_root/main/php_config.h"
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
cc -O2 -I"$source_root" -I"$source_root/main" -I"$source_root/Zend" \
    -I"$source_root/TSRM" "$test_dir/persistent_oom.c" -o "$scratch/probe"
for mode in malloc realloc; do
    status=0
    "$scratch/probe" "$scratch/atexit" "$mode" > "$scratch/out" 2> "$scratch/err" || status=$?
    test "$status" -eq 1
    test ! -e "$scratch/atexit"
    grep -q 'Out of memory' "$scratch/err"
done
echo 'PASS: persistent malloc/realloc failure exits 1 without atexit'
