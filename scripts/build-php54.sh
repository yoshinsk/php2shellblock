#!/bin/sh
# scripts/build-php54.sh: upstream PHP 5.4.45を別配置でビルドし、既存PHPには導入しない。
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
archive=$(readlink -f "${1:?Usage: scripts/build-php54.sh php-5.4.45.tar.bz2 /absolute/new/build-dir}")
work=${2:?Specify a new absolute build directory}
case "$work" in /*) ;; *) echo 'Use an absolute path' >&2; exit 1;; esac
test ! -e "$work" || { echo 'Build directory already exists; refusing overwrite' >&2; exit 1; }
echo "4e0d28b1554c95cfaea6fa2b64aac85433f158ce72bb571bcd5574f98f4c6582  $archive" | sha256sum -c -
mkdir -p "$work"
tar -xjf "$archive" -C "$work"
cd "$work/php-5.4.45"
# Remiソースで追加される二つの文字列長検査を先に合わせ、同じ修正パッチを適用する。
patch --fuzz=0 -p1 < "$repo/patches/php-5.4.45-remi-overflow-prep.patch"
patch --fuzz=0 -p1 < "$repo/patches/php-5.4.45-php2shell.patch"
# 検証用の最小構成。make installは呼ばず、Apache設定・RPMを変更しない。
nice -n 15 ionice -c3 ./configure --prefix="$work/prefix" --disable-all \
    --enable-cli --enable-cgi --enable-session --enable-json --enable-filter \
    --with-apxs2=/usr/bin/apxs > "$work/configure.log" 2>&1
nice -n 15 ionice -c3 make -j1 > "$work/build.log" 2>&1
echo "Build only: $work/php-5.4.45/sapi/cli/php"
echo "Apache module: $work/php-5.4.45/libs/libphp5.so"
