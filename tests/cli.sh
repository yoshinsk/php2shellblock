#!/bin/sh
# tests/cli.sh: 独立CLIで正常系、警告、fatal、OOM、shutdown省略を検証する。
set -eu
module=$(readlink -f "${1:?Usage: tests/cli.sh /absolute/path/php2shell_block.so}")
phpbin=${PHP_BIN:-php}
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
check() {
    expected=$1
    code=$2
    actual=0
    "$phpbin" -n -d "extension=$module" -d memory_limit=16M -r "$code" >"$scratch/out" 2>"$scratch/err" || actual=$?
    test "$actual" -eq "$expected" || { cat "$scratch/err"; echo "FAIL status $actual != $expected"; exit 1; }
}
check 0 'echo "normal";'
test "$(cat "$scratch/out")" = normal
check 0 'trigger_error("warning", E_USER_WARNING); echo "continued";'
grep -q continued "$scratch/out"
check 86 'register_shutdown_function(function(){echo "SHUTDOWN_RAN";}); undefined_function_for_test();'
! grep -q SHUTDOWN_RAN "$scratch/out"
grep -q 'fail-fast exit (86)' "$scratch/err"
check 86 '$x = str_repeat("a", 32 * 1024 * 1024);'
check 86 'trigger_error("fatal", E_USER_ERROR);'
check 86 'eval("invalid syntax !!!");'
echo 'PASS: normal, warning, fatal, OOM, user fatal, parse, shutdown skipped'
