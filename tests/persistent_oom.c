/*
 * tests/persistent_oom.c
 * PHPヘッダー内の永続割当失敗がatexitを実行せず終了することを検証する。
 * SIZE_MAX相当の割当は成功しないため、ホストの実メモリを消費しない。
 */
#include "php.h"
#include <stdio.h>
#include <stdlib.h>

static const char *marker;

/* exit()へ退行した場合だけ、呼出元が検出できるマーカーを残す。 */
static void cleanup_marker(void)
{
    FILE *stream = fopen(marker, "w");
    if (stream) {
        fputs("unsafe atexit", stream);
        fclose(stream);
    }
}

int main(int argc, char **argv)
{
    volatile size_t impossible = (size_t) -1;
    if (argc != 3) {
        return 2;
    }
    marker = argv[1];
    atexit(cleanup_marker);
    if (argv[2][0] == 'm') {
        (void) __zend_malloc(impossible);
    } else {
        (void) __zend_realloc(NULL, impossible);
    }
    return 3;
}
