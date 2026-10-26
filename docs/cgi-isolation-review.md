# PHP 5.4 CGI のリクエスト単位分離

## 設計評価

OOM 時に PHP の後処理を経ず `_exit()` するバックポートと、要求ごとに新しい PHP CGI プロセスを `exec` する配置を組み合わせる方式です。PHP の版番号は 5.4.45 のままです。以下はソースと公式情報に基づく設計評価であり、配置済みという意味ではありません。実機の試験結果は別途記録してください。

| 対象 | 対策の根拠 | 成立条件 |
| --- | --- | --- |
| CVE-2026-109618 | OOM の `longjmp()` と不完全な状態での PHP 後処理を、allocator 内の `_exit()` で止める | 実際に実行する CGI バイナリーにパッチが入り、対象の割当失敗がその経路を通る |
| CVE-2026-109619 | 公式説明の条件 4「同じワーカーが後続要求を処理する」を、要求ごとの新規 `exec` で除く | PHP を初期化したプロセスを再利用せず、未対策の別ハンドラーにも流さない |

これは公開された両 CVE の成立条件を組み合わせて除くという評価です。未知の脆弱性、第三者拡張の不具合、PHP 5.4 全体の安全性を保証するものではありません。プロセスを分けるだけでは CVE-2026-109618 の同一要求内の危険な後処理は残るため、allocator の修正も必要です。

[PHP の CVE-2026-109619 告知](https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp) は、問題の状態を生成した要求と、それを消費する要求が同一ワーカーで処理される条件を示しています。[CVE-2026-109618 告知](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w) は、OOM からの早期脱出で不完全な状態が後処理に渡る仕組みを説明しています。

## 新規プロセスの条件

PHP 5.4.45 の [cgi_main.c](https://github.com/php/php-src/blob/php-5.4.45/sapi/cgi/cgi_main.c) では、通常 CGI の要求処理は `if (!fastcgi)` の分岐で一度の処理後にループを抜けます。ただし、benchmark の反復実行オプションは例外です。起動する引数を固定し、要求由来の値をコマンドライン引数へ追加しない構成にします。

Apache の [mod_cgi](https://httpd.apache.org/docs/2.4/mod/mod_cgi.html) と [mod_actions](https://httpd.apache.org/docs/2.4/mod/mod_actions.html) を用い、固定 wrapper から固定パスの patched `php-cgi` を `exec` する方式を対象とします。PHP を初期化した常駐プロセスからの fork、FastCGI の再利用、FPM のワーカー再利用は、この設計でいう新規 `exec` とは異なります。

PHP 5.4 の FastCGI 判定は、単に環境変数名だけでは決まりません。[fastcgi.c](https://github.com/php/php-src/blob/php-5.4.45/sapi/cgi/fastcgi.c) は Linux では標準入力が接続待ちソケットかを調べます。通常 CGI の標準入力を用い、`-b` で待受ソケットを作らないことも確認します。

TCP 接続の Keep-Alive を利用しても、Apache が要求ごとに PHP を新しく `exec` するなら、PHP のプロセス分離は維持されます。PID の一覧だけでは PID 再利用を区別できないため、プロセス開始時刻と実行バイナリー、必要に応じて `execve` の観測を併用します。

## 配置時の確認

すべての公開ポート、VirtualHost、Alias、Directory、拡張子、PATH_INFO、内部リダイレクトを確認します。一部の `.php` が従来の mod_php や別の FastCGI ハンドラーに流れる場合、その経路は新規プロセスによる対策の対象外です。管理画面だけの切替でサーバー全体を対応済みとは扱いません。

CGI 本体や wrapper を任意ファイルの実行入口として直接利用できない配置にします。[PHP の cgi.force_redirect の説明](https://www.php.net/manual/en/security.cgi-bin.force-redirect.php) は、Apache の内部リダイレクトを通す用途を示しています。設定値だけで判断せず、wrapper への直接要求、存在しないファイル、PHP ファイルに続く PATH_INFO、認証済み領域外のファイルを実際に試験します。

wrapper とバイナリーは Web 実行ユーザーが書き換えられない所有権にします。INI の読込み先と共有拡張の探索先を固定し、既存の設定を無条件で失わないよう比較します。`PHPRC`、`PHP_INI_SCAN_DIR`、`LD_PRELOAD` などを要求の入力から指定できる構成にはしません。`QUERY_STRING` を shell の文字列へ展開して実行する wrapper は使いません。

## mod_php との互換性

| 項目 | 変更または検証事項 |
| --- | --- |
| PHP 言語・共有拡張 | 版番号が同じでも、ビルド設定、共有ライブラリー、拡張の読込みを比較する |
| Apache 固有関数 | CGI にない `apache_getenv()`、`apache_setenv()`、`apache_get_modules()` などの利用を調べる。5.4 CGI にある `apache_request_headers()` と `apache_response_headers()` まで一律に使えないとは扱わない |
| `.htaccess` の PHP 設定 | mod_php 用 `php_value` / `php_flag` の値が CGI に自動継承されるとは扱わない。必要な値を固定 INI へ移す |
| `.user.ini` | CGI では有効になる。既存ファイルを調べるか、不要なら `user_ini.filename` を空にして挙動を固定する |
| 認証 | Authorization の受渡し、PHP_AUTH_USER、PHP_AUTH_PW、既存ログインと権限を確認する |
| URL とファイルの対応 | SCRIPT_FILENAME、SCRIPT_NAME、PATH_INFO、PATH_TRANSLATED、REQUEST_URI、DOCUMENT_ROOT を比較し、別ファイルへの誤解決がないことを確認する |
| 作業ディレクトリーと権限 | 相対パス、ファイル所有者、umask、書込み先、セッション保存先を確認する |
| セッション | ファイルや DB に保存するセッションはプロセス外に残る。通常ログイン、保存処理とロックを試験する |
| 永続接続とキャッシュ | 要求間の DB 永続接続や PHP プロセス内キャッシュを共有しなくなる。起動・接続コストを測定する |
| 負荷とタイムアウト | 同時起動数、メモリー使用、遅延を測定する。OOM で CGI が終了したときの Apache 応答と後続要求を確認する |

[PHP の `.user.ini` 説明](https://www.php.net/manual/en/configuration.file.per-user.php) は、この設定が CGI/FastCGI SAPI で処理されることを示しています。Apache 固有関数の差異は、5.4.45 の [CGI 関数登録](https://github.com/php/php-src/blob/php-5.4.45/sapi/cgi/cgi_main.c) と [Apache 関数登録](https://github.com/php/php-src/blob/php-5.4.45/sapi/apache2handler/php_functions.c) を比較した結果です。

## 実機試験の合格条件

1. 通常 GET/POST、multipart、セッション付き要求を同じ接続で連続実行し、各要求が新しい CGI 実行インスタンスで処理される。
2. parse error、fatal error、timeout、shutdown 中の warning の後も、次の要求が新しい CGI 実行インスタンスで処理される。
3. 入力解析中とアプリケーション実行中の OOM で CGI が終了し、登録した PHP shutdown 関数やデストラクタが呼ばれない。Apache 自体と後続要求は正常に処理される。
4. 未対策 mod_php、FPM、FastCGI へ戻る公開経路がない。wrapper の直接実行や URL 解決の迂回が拒否される。
5. アプリのログイン、主要画面、設定保存、アップロード、連携、セッション維持に必要な機能が通る。

これらの条件を確認した範囲で、「PHP 5.4.45 を維持し、公開された両 CVE の成立経路を遮断した」と記録できます。実施していない経路や機能の検証まで完了したとは記載しません。
