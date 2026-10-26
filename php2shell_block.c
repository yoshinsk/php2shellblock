/*
 * php2shell_block.c
 * PHP 5.4〜5.6 NTS専用。致命的エラーでワーカーを即時終了する実験的緩和。
 * PHP2Shellの公式パッチと同等ではない。既存のメモリ破損は修復しない。
 */
#ifdef HAVE_CONFIG_H
#include "config.h"
#endif
#include "php.h"
#include <unistd.h>

#if PHP_VERSION_ID < 50400 || PHP_VERSION_ID >= 50700
#error "Only PHP 5.4 through 5.6 are supported experimentally"
#endif
#ifdef ZTS
#error "Thread-safe PHP is unsupported: exiting would terminate other requests"
#endif

static void (*previous_error_cb)(int, const char *, const uint,
                                const char *, va_list);

/*
 * 整形処理やヒープ割当を避け、固定メッセージだけを標準エラーへ出す。
 * 元のエラー処理、shutdown関数、出力・セッション保存を実行せず終了する。
 * zend_error()がこのコールバックより先に行う状態参照は保護できない。
 */
static void block_error_cb(int type, const char *filename, const uint line,
                           const char *format, va_list args)
{
    if (type & (E_ERROR | E_PARSE | E_CORE_ERROR | E_COMPILE_ERROR | E_USER_ERROR)) {
        static const char message[] =
            "php2shell_block: fatal error; experimental fail-fast exit (86)\n";
        ssize_t ignored = write(STDERR_FILENO, message, sizeof(message) - 1);
        (void) ignored;
        _exit(86);
    }
    /* 非致命的エラーは従来のコールバックへ渡し、警告の挙動を維持する。 */
    previous_error_cb(type, filename, line, format, args);
}

/* 入力解析より遅いRINITではなく、プロセス起動時にフックを登録する。 */
PHP_MINIT_FUNCTION(php2shell_block)
{
    previous_error_cb = zend_error_cb;
    zend_error_cb = block_error_cb;
    return SUCCESS;
}

/* 後続の拡張がフックを差し替えた場合、そのフックを上書きしない。 */
PHP_MSHUTDOWN_FUNCTION(php2shell_block)
{
    if (zend_error_cb == block_error_cb) {
        zend_error_cb = previous_error_cb;
    }
    return SUCCESS;
}

zend_module_entry php2shell_block_module_entry = {
    STANDARD_MODULE_HEADER,
    "php2shell_block",
    NULL,
    PHP_MINIT(php2shell_block),
    PHP_MSHUTDOWN(php2shell_block),
    NULL, NULL, NULL,
    "0.1.0-experimental",
    STANDARD_MODULE_PROPERTIES
};

#ifdef COMPILE_DL_PHP2SHELL_BLOCK
ZEND_GET_MODULE(php2shell_block)
#endif
