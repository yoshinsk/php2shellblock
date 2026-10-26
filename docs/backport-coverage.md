# PHP 5.4.45 バックポート候補の対応範囲

## 検証状況

`patches/php-5.4.45-php2shell.patch` は PHP 5.4.45 用の独自バックポート候補です。PHP 公式の PHP 7.4 向け最小バックポートを参考に、Zend Engine 2 の構造に合わせて変更しています。PHP 公式の PHP 5.4 向けパッチではありません。

公式タグ `php-5.4.45` のソースに対する `git apply --check` は成功しています。コンパイルと隔離HTTP試験の結果は[検証記録](validation.md)に記載しています。Remi `5.4.45-19` のベンダーパッチ適用後のソースにも、空白差を許容する`patch -l --fuzz=0`で適用できました。両CVEの完全対応を確認したという意味ではありません。

## 根拠

- [PHP 公式セキュリティ告知](https://www.php.net/) は、2026 年 10 月 21 日に両 CVE の修正版を公開しています。
- [CVE-2026-109618](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w) は、OOM 時の `longjmp()` が未初期化のリクエスト状態を後処理に渡す問題です。
- [CVE-2026-109619](https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp) は、解放されたリクエストメモリーへの参照がワーカーに残り、次のリクエストで使用される問題です。
- [PHP 7.4 向け公式最小バックポート](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2) は、OOM 時のワーカー終了、状態の初期化、セッションアップロード進捗の無効化、multipart 制限を含みます。
- 移植元の PHP 5.4 ソースは [公式タグ php-5.4.45](https://github.com/php/php-src/tree/php-5.4.45) です。

## 公式パッチとの対応

| 公式 7.4 の変更 | PHP 5.4 での変更 | 判定と差異 |
| --- | --- | --- |
| `Zend/zend_alloc.c` の OOM を `_exit(1)` に変更 | 同ファイルの `zend_mm_safe_error()` から新設の終了関数を呼び出す | メモリー制限超過と基盤割当失敗で PHP のエラー処理・後処理を実行しない。元の heap reserve 解放も省く |
| 永続割当の失敗を即時終了 | `zend_alloc.h`の`__zend_malloc()`と`__zend_realloc()`を`_exit(1)`に変更 | malloc/realloc失敗時にatexitが実行されないことを単独Cプローブで確認 |
| 割当サイズの整数オーバーフローを同じ終了経路に変更 | `safe_address()` の全アーキテクチャ分岐を変更 | PHP 5.4 には `zend_multiply.h` の対応処理がなく、`zend_alloc.c` 内にある |
| `zend_strtod.c` の割当失敗を終了経路に変更 | `Balloc()` の割当失敗と範囲外を変更 | PHP 5.4 の処理位置に合わせた移植 |
| VM の文字列結合時の割当オーバーフローを終了経路に変更 | `zend_operators.c` の `concat_function()` の両エラー経路を変更 | PHP 5.4 の同処理はこの関数にある。生成済み VM ヘッダーの変更は不要 |
| `zend_execute_API.c` のエラーハンドラー・例外・オブジェクト状態を初期化 | `shutdown_executor()` の `zend_try` 外でポインターとスタックを初期化 | PHP 5.4 は `zval *` であり、7.4 の `ZVAL_UNDEF` は使えない。実行位置の参照も初期化 |
| `zend_llist_destroy()` の head/tail を NULL に変更 | 同変更 | 解放した要素への参照を残さない |
| `SAPI.c` で解放した認証情報などを NULL に変更 | 認証情報、content type、current user、post/raw post、callback を NULL に変更 | PHP 5.4 固有の post/raw post 所有状態も対象 |
| HTTP globals 解放後の未定義化、modules_activated の初期化 | `zval_ptr_dtor()` 後に NULL を設定。通常終了と hook 終了の両方の HTTP globals を変更 | PHP 5.4 のポインター表現に対応 |
| セッションアップロード進捗 callback を無条件に迂回 | 同 callback の既存 callback 連鎖後に進捗処理を無効化 | 通常の `session_start()` は残る。進捗機能は設定値にかかわらず使えなくなる |
| multipart の不要ヘッダー・重複ヘッダーを保存しない | Content-Disposition と Content-Type の最初の値だけ保存 | 従来の重複ヘッダーの扱いが変わる |
| multipart part 数制限の追加 | `max_multipart_body_parts` を追加 | 負数の場合は max_input_vars と max_file_uploads の合計。空ファイルを含む各 part を数える |
| `substring_conf()` の長さを size_t に変更 | 同変更 | PHP 5.4 の長さ型を変更 |
| singleton array と HashTable 内部処理の変更 | 移植していない | Zend Engine 2 と 3 で配列構造が異なる。割当増幅を減らす変更であり、独自に最小配列サイズを変えず OOM の終了経路で扱う |

`main/main.c` では、後段の拡張や SAPI の終了処理がエラー情報を再設定する場合に備え、通常のリクエストヒープ解放前にもエラーハンドラー、例外、最後のエラー情報を初期化します。独自拡張の非公開グローバル状態は、この変更だけでは監査できません。

## バイナリーと運用への影響

PHP の版番号を更新せず、元のRemi SRPMが適用している修正を維持し、用途に必要なビルド条件で再ビルドする必要があります。upstream のみから別条件でビルドした `libphp5.so` を既存環境へ置くと、共有拡張や外部ライブラリーとの互換性を失う可能性があります。対象は CentOS 7、NTS、mod_php、PHP 5.4.45 です。他の環境への適合は未検証です。

OOM になったワーカーは即時終了します。PHP の shutdown 関数、デストラクタ、セッション保存、出力フラッシュは実行しません。Apache prefork がワーカーを補充すること、同時処理中の別サービスに影響しないことを実測してください。これは PHP 7.4 の公式最小バックポートにもある動作変更です。

セッションアップロード進捗を利用するアプリケーションでは機能が失われます。通常のアップロード、ログイン、アプリの管理操作、セッション更新が維持されるかは別途確認が必要です。

## 必要な検証

1. Remi `5.4.45-19` の SRPM を取得し、元のパッチ適用後のソースにこの候補を適用する。差分の競合を確認し、元のパッケージの設定と依存ライブラリーで再ビルドする。
2. CLI と Apache の双方で版番号、SAPI、NTS、モジュール一覧、設定値を比較する。既存の共有拡張を読み込み、未解決シンボルや起動時エラーがないことを確認する。
3. 隔離した Apache prefork で通常リクエスト、GET/POST、通常アップロード、空ファイル、入力配列、セッションの書込みと読出しを確認する。
4. 小さい memory_limit で入力解析時とアプリケーション実行時の OOM を起こす。元のワーカー PID が終了し、PHP shutdown とデストラクタが実行されず、次の正常リクエストを別 PID が処理することを確認する。
5. セッションアップロード進捗を設定で有効にしても、実際のアップロード進捗がセッションに書かれないことを確認する。
6. part 数上限の直前、上限、上限超過、空ファイル多数、不要・重複ヘッダー、Content-Length が使えない入力を確認する。Web サーバー側の要求サイズ制限も別途確認する。
7. 同一ワーカーを使用する条件で fatal error、parse error、timeout、shutdown 中の warning と次の正常要求を繰り返す。ASan または Valgrind と、ヒープ解放直前の内部状態検査を併用する。
8. アプリのログイン、主要設定の保存、ファイル入出力、セッション維持、既存連携を確認する。Web プロセス切替前後の関連サービス状態も記録する。

ビルド成功と正常ページの表示だけでは、両 CVE の完全対応を立証できません。上記の異常系試験とベンダー差分の確認を満たし、残る未検証事項を記録したうえで採用を判断してください。
