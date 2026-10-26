# php2shellblock

PHP 5.4.45向けの独自バックポートと、Apache mod_php用の導入ツールです。PHP 5.4.45を維持する環境で、次の脆弱性に関連する処理を修正します。

- CVE-2026-109618：メモリ不足時の中断と後処理によるメモリ破損。
- CVE-2026-109619：リクエスト終了後に残った内部状態が、後続リクエストで使われる問題。

PHPプロジェクトやRemiの公式修正版ではありません。**両CVEの確認済み経路を修正前後で比較検証しました。** 元版でOOM後のSegmentation faultを再現し、修正版ではワーカーの終了と次要求の正常応答を確認しています。[試験条件と結果](docs/security-validation.md)を参照してください。任意コード実行と全攻撃経路への有効性は未検証です。

## ダウンロード

[導入シェル](https://github.com/yoshinsk/php2shellblock/releases/download/v0.1.2/php2shellblock-install.sh) · [チェックサム](https://github.com/yoshinsk/php2shellblock/releases/download/v0.1.2/php2shellblock-install.sh.sha256) · [リリース一覧](https://github.com/yoshinsk/php2shellblock/releases)

導入シェルは検証対象のPHPモジュールを同梱した自己展開形式です。モジュールを追加取得したり、対象サーバーでビルドしたりする必要はありません。

```sh
release_url='https://github.com/yoshinsk/php2shellblock/releases/download/v0.1.2'
curl --fail --location --output php2shellblock-install.sh "$release_url/php2shellblock-install.sh"
curl --fail --location --output php2shellblock-install.sh.sha256 "$release_url/php2shellblock-install.sh.sha256"
sha256sum --check php2shellblock-install.sh.sha256
```

チェックサムの一致を確認してから実行してください。チェックサムは破損や取り違えを検出するためのもので、署名ではありません。

## 対応環境

|項目|条件|
|---|---|
|OS・CPU|CentOS Linux 7、x86_64|
|PHP RPM|`php`・`php-common`・`php-cli`が`5.4.45-19.el7.remi.x86_64`|
|Apache|2.4.6、prefork、NTS mod_php|
|モジュール設定|`/etc/httpd/conf.modules.d/10-php.conf`|
|SELinux|DisabledまたはPermissive|
|実行権限|rootまたはsudo|

元のPHPモジュールと主要ライブラリのSHA-256も照合します。版番号が同じでも、ビルドや依存関係が異なる環境には適用しません。PHP-FPM、CGI、ZTS、Apache worker/event、別OSは自動適用の対象外です。強制適用オプションはありません。

必要なコマンドや空き容量は[導入手順の対応環境](docs/install.md#対応環境)を参照してください。

Pythonは2.7または3.6以上を使用します。`python`、`python2.7`、`python3`の順に利用可能なものを選びます。Python 2.6のみの環境やCentOS 6は対応外です。[実行時のエラー](docs/install.md#実行時のエラー)も参照してください。

`v0.1.1`を適用済みの環境は、`v0.1.2`の導入シェルで更新できます。更新前の設定とモジュールを退避し、ロールバック時は`v0.1.1`へ戻します。

## 検査と適用

`/login.php`を、既存アプリの実在するPHP表示ページへ置き換えてください。保存・削除を行わず、認証なしで200を返し、連続して取得しても本文が変わらないページを指定します。

まず、稼働中の設定を変更しない検査を実行します。

```sh
sudo bash php2shellblock-install.sh --check \
  --health-url http://127.0.0.1/login.php
```

適用には`--apply`を使用します。このモードにも事前検査が含まれます。

```sh
sudo bash php2shellblock-install.sh --apply \
  --health-url http://127.0.0.1/login.php
```

対応環境とファイルのハッシュ、隔離ApacheでのPHP拡張・内部関数・INI設定・機能試験を確認します。検査成功後に退避を作成し、Apacheをgracefulで再読込みして画面応答を比較します。適用後の確認で不一致を検出した場合は、自動復旧を試みます。

HTTPとHTTPSを併せて確認する場合は`--health-url`を複数指定します。VirtualHostには`--host-header`を指定できます。指定方法と検査の制約は[導入手順](docs/install.md)に記載しています。

## 状態確認と復旧

```sh
sudo bash php2shellblock-install.sh --status
sudo bash php2shellblock-install.sh --rollback latest
```

退避先は`/var/lib/php2shellblock/`です。適用時に、ネット接続なしで使える`rollback.sh`の場所も表示します。

同じモジュールがすでに稼働していれば、再適用せず終了し、新しい退避は作成しません。その場合は、元の導入方法に対応する復旧手順を使用してください。[ロールバックの詳細](docs/install.md#ロールバック)を確認してください。

## 変更範囲と制約

対象はWeb用mod_phpです。別配置のモジュールへ参照を切り替え、既存の`include_path`を維持します。元のPHP RPM、元モジュール、`/usr/bin/php`は上書きしません。アプリのコードやDBデータ、Apache以外のサービス設定は変更しません。

自動試験の範囲はPHPのAPI・INI・合成機能試験・指定画面のGETまでです。実パスワード認証、業務データの保存、外部連携、負荷試験など、アプリ全体の互換性は運用者による確認が必要です。

OOM時にはワーカーを即時終了するため、shutdown関数、デストラクタ、セッション保存、正常なエラーページ送信が完了しない場合があります。セッションアップロード進捗機能も無効になります。これらの動作変更を含め、[対応範囲](docs/backport-coverage.md)と[検証項目](docs/validation.md)を確認してください。

## 技術資料

- [導入・状態確認・ロールバック](docs/install.md)
- [ビルドと配布物の生成](docs/build.md)
- [PHP本体向けパッチの対応範囲](docs/backport-coverage.md)
- [検証項目と未検証の範囲](docs/validation.md)
- [両CVEの修正前後比較](docs/security-validation.md)
- [インストーラーの検証方法](docs/installer-validation.md)

## 出典

- [PHP公式セキュリティ告知](https://www.php.net/archive/2026.php)
- [CVE-2026-109618の公式アドバイザリ](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w)
- [CVE-2026-109619の公式アドバイザリ](https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp)
- [PHP 7.4向け公式最小バックポート](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2)

## ライセンス

独自の導入・検証スクリプトと文書は[MIT License](LICENSE)です。PHP/Zend由来のパッチ、修正後PHPソースとPHPバイナリーには元のライセンス条件が適用されます。[NOTICE.md](NOTICE.md)を参照してください。
