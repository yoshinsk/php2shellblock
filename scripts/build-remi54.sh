#!/bin/sh
# scripts/build-remi54.sh: 署名を確認したRemi SRPMの既存修正を維持して検証用PHPをビルドする。
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
srpm=$(readlink -f "${1:?Usage: scripts/build-remi54.sh source.rpm /new/absolute/work [remi2022-key]}")
work=${2:?Specify a new absolute work directory}
key=$(readlink -f "${3:-/etc/pki/rpm-gpg/RPM-GPG-KEY-remi2022}")
case "$work" in /*) ;; *) echo 'Use an absolute path' >&2; exit 1;; esac
test ! -e "$work" || { echo 'Work directory exists; refusing overwrite' >&2; exit 1; }
echo "daba229f3ee2f17157d8bffcd74b8281f2da2eb08b537b1e6070743459ab0280  $srpm" | sha256sum -c -
echo "e60cece0fe4cc0dda016c2c9800818105da794d19acd1dd39a531d09758f5593  $key" | sha256sum -c -
mkdir -p "$work/rpmdb" "$work/rpmbuild"
# システムのRPM鍵データベースを変更しない。
rpm --dbpath "$work/rpmdb" --initdb
rpm --dbpath "$work/rpmdb" --import "$key"
rpm --dbpath "$work/rpmdb" --checksig "$srpm"
rpm -i --define "_topdir $work/rpmbuild" "$srpm" > "$work/extract.log" 2>&1
# --nodepsはソース準備だけに使用し、OSパッケージの導入は実行しない。
nice -n 15 ionice -c3 rpmbuild -bp --nodeps --define "_topdir $work/rpmbuild" \
    "$work/rpmbuild/SPECS/php54.spec" > "$work/prep.log" 2>&1
cd "$work/rpmbuild/BUILD/php-5.4.45"
# Remiの末尾空白の差を許容するが、コンテキスト行の省略は許容しない。
patch --dry-run -l --fuzz=0 -p1 < "$repo/patches/php-5.4.45-php2shell.patch"
patch -l --fuzz=0 -p1 < "$repo/patches/php-5.4.45-php2shell.patch"
# Remiがconfig.m4を変更しているため、configureの再生成を省略しない。
nice -n 15 ionice -c3 ./buildconf --force > "$work/buildconf.log" 2>&1
# Remi specと同じRPM最適化・保護フラグを使い、旧PHPに必要なaliasing設定も維持する。
CFLAGS="$(rpm --eval '%{optflags}') -fno-strict-aliasing -Wno-pointer-sign"
export CFLAGS
EXTENSION_DIR=/usr/lib64/php/modules nice -n 15 ionice -c3 ./configure \
    --prefix="$work/prefix" --disable-all --enable-cli --enable-cgi \
    --enable-session --enable-filter --enable-calendar --enable-ctype --enable-exif \
    --enable-ftp --enable-pcntl --enable-shmop --enable-sockets --enable-tokenizer \
    --enable-simplexml --enable-xml --with-bz2 --with-gettext --with-iconv \
    --with-openssl --with-pcre-regex=/usr --with-zlib --with-libxml-dir=/usr \
    --enable-libxml --with-mhash --with-system-tzdata --with-libdir=lib64 \
    --with-apxs2=/usr/bin/apxs --with-config-file-path=/etc \
    --with-config-file-scan-dir=/etc/php.d > "$work/configure.log" 2>&1
nice -n 15 ionice -c3 make -j1 > "$work/build.log" 2>&1
echo "Build only: $work/rpmbuild/BUILD/php-5.4.45"
echo 'Existing PHP extensions/configuration are referenced; no make install or binary RPM install is performed.'
