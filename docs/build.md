# ビルドと配布物の生成

公開インストーラーにはビルド済みのPHPモジュールを同梱しています。通常の導入では[導入手順](install.md)を使用してください。この文書はソースと生成処理を確認する開発者向けです。

## Remiソースからのビルド

対象はRemi `php-5.4.45-19.remi.src.rpm`です。`v0.1.3`で追加した`5.4.45-18.el7.remi`構成でも、同じ修正版モジュールを使用します。`gcc`、`make`、`patch`、`bzip2`、`httpd-devel`、`apxs`、`ionice`など、PHPのビルド依存関係を満たす隔離環境を用意してください。

```sh
curl --fail --location --max-time 120 \
  https://remi.repo.nfrance.com/SRPMS/php-5.4.45-19.remi.src.rpm \
  -o php-5.4.45-19.remi.src.rpm
sh scripts/build-remi54.sh ./php-5.4.45-19.remi.src.rpm /opt/php2shell-remi-build
```

ビルド先には、新しい絶対パスを指定します。スクリプトはSRPMとRemi 2022鍵のSHA-256を照合し、システムとは別のRPMデータベースで署名を検証します。既存のRemiパッチを適用した後、本プロジェクトのパッチを追加します。

`nice -n 15`、`ionice -c3`、`make -j1`でビルドします。`make install`や既存RPMへの上書きは行いません。生成先は`/opt/php2shell-remi-build/rpmbuild/BUILD/php-5.4.45/`です。共有拡張の探索先は`/usr/lib64/php/modules`、INIの読込み先は`/etc`と`/etc/php.d`を前提としています。

このビルドは全サブパッケージのRPMを再作成するものではありません。CLIの`readline`は構成に含みません。ビルドしたCLIを既存の`/usr/bin/php`へ上書きしないでください。

## 機能試験

専用環境で、生成したバイナリーを指定します。

```sh
source_dir=/opt/php2shell-remi-build/rpmbuild/BUILD/php-5.4.45
sh tests/runtime_cli.sh "$source_dir/sapi/cli/php"
sh tests/persistent_oom.sh "$source_dir"
python tests/startup_oom.py "$source_dir/sapi/cgi/php-cgi"
python tests/apache_http.py "$source_dir/libs/libphp5.so" --runtime --installed-extensions
```

HTTP試験はrootで専用Apacheを起動し、子プロセスを`apache`ユーザーで実行します。127.0.0.1:18081が使用中なら停止します。試験用のログ・セッション・ファイルは一時ディレクトリへ分離します。

## 配布ファイルの生成

生成ツールにはPython 3.10以上が必要です。対象モジュールと変更後PHPソースのハッシュが、公開している定義と一致する場合だけ配布物を生成します。異なるビルドへ検証結果を流用することはできません。

```sh
python3 scripts/package-release.py \
  --version v0.1.3 \
  --module /絶対パス/libphp5.so \
  --php-source /絶対パス/php-5.4.45 \
  --output /新しい絶対パス/release-v0.1.3
```

出力先に既存のディレクトリを指定すると停止します。出力は導入用シェル、シェル用チェックサム、payloadアーカイブ、`SHA256SUMS`です。同じ入力から同じ内容を生成するため、アーカイブの並び順・時刻・所有者情報を固定しています。

PHPパッチと変更後ソースの定義は[`release/php54-source-manifest.json`](../release/php54-source-manifest.json)、ライセンスは[NOTICE.md](../NOTICE.md)を参照してください。

## 実験用コード

`scripts/build-php54.sh`はupstreamソースを対象とする別構成のビルド用です。Remiが追加した二つの文字列長検査を準備パッチで合わせてから、本体パッチを適用します。公開インストーラー用のRemi構成とは区別してください。

`php2shell_block.c`と`config.m4`は、致命的エラーを検知した際に終了する実験用拡張です。公開インストーラーはこの拡張を使用しません。PHPの入力解析や内部状態の問題を網羅して修正するものではないため、本体向けパッチの代替として導入しないでください。
