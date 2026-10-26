#!/bin/sh
# tests/runtime_cli.sh: 修正候補PHPの版番号、OOM即時終了、通常セッションを検証する。
set -eu
phpbin=$(readlink -f "${1:?Usage: tests/runtime_cli.sh /absolute/path/patched/php}")
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
test "$("$phpbin" -n -r 'echo PHP_VERSION;')" = 5.4.45
"$phpbin" -n -r 'echo "normal";' > "$scratch/out"
test "$(cat "$scratch/out")" = normal
status=0
# shutdownとデストラクタが、OOM後に呼ばれないことを外部ファイルで検出する。
"$phpbin" -n -d memory_limit=16M -r '
$path = $argv[1];
register_shutdown_function(function() use ($path) {file_put_contents($path, "shutdown");});
class TestDestructor {
    public $path;
    function __destruct() {file_put_contents($this->path, "destructor");}
}
$object = new TestDestructor();
$object->path = $path;
$x = str_repeat("a", 32 * 1024 * 1024);
' "$scratch/unsafe-cleanup" > "$scratch/out" 2> "$scratch/err" || status=$?
test "$status" -eq 1
test ! -e "$scratch/unsafe-cleanup"
grep -q 'Allowed memory size' "$scratch/err"
# システム全体のメモリを消費せず、単独プロセス内の設定上限で検証する。
echo 'PASS: PHP 5.4.45, normal execution, OOM exit 1, shutdown/destructor skipped'
