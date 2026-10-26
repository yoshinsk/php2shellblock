dnl config.m4: PHP 5.4〜5.6用の実験的fail-fast拡張を構成する。
PHP_ARG_ENABLE(php2shell_block, whether to enable php2shell_block,
[  --enable-php2shell_block  Enable experimental fatal-error fail-fast mitigation])
if test "$PHP_PHP2SHELL_BLOCK" != "no"; then
  PHP_NEW_EXTENSION(php2shell_block, php2shell_block.c, $ext_shared)
fi
