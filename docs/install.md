# 導入とロールバック

この手順は、PHP 5.4.45を更新できない環境向けの独自バックポートを導入するものです。PHPプロジェクトやRemiの公式修正版ではありません。実攻撃の再現と、両CVEに対する完全な有効性は未検証です。

## 対応環境

`v0.1.1`の対応範囲は、次の構成に限定しています。

|項目|条件|
|---|---|
|OS・CPU|CentOS Linux 7、x86_64|
|PHP RPM|`php`・`php-common`・`php-cli`が`5.4.45-19.el7.remi.x86_64`|
|Web実行方式|Apache 2.4.6、prefork、NTS mod_php|
|モジュール設定|`/etc/httpd/conf.modules.d/10-php.conf`にNTSの`LoadModule`が1件|
|元モジュール|既知のRPMモジュールのSHA-256と一致|
|主要ライブラリ|glibc・OpenSSL・libxml2・PCREが同梱manifestのハッシュと一致|
|SELinux|DisabledまたはPermissive|
|実行権限|rootまたはsudo|
|必要なコマンド|bash、Python 2.7または3.6以上、uname、base64、sha256sum、awk、mktemp、nice、httpd、rpm、systemctl、ldd、getenforce|
|空き容量|`/opt`・`/var`・`/usr/local`に各100MiB以上|

EL8/EL9、AlmaLinux、Rocky Linux、Ubuntu、PHP-FPM、CGI、ZTS、Apache worker/event、別リリースのPHP RPMは自動適用の対象外です。同じ版番号でもベンダーやビルド条件が異なる場合は停止します。対象外へ強制適用するオプションはありません。

## ダウンロード

[リリース一覧](https://github.com/yoshinsk/php2shellblock/releases)から取得できます。初版の固定URLを使う場合は、対象サーバーで次を実行してください。

```sh
release_url='https://github.com/yoshinsk/php2shellblock/releases/download/v0.1.1'
curl --fail --location --output php2shellblock-install.sh "$release_url/php2shellblock-install.sh"
curl --fail --location --output php2shellblock-install.sh.sha256 "$release_url/php2shellblock-install.sh.sha256"
sha256sum --check php2shellblock-install.sh.sha256
```

最後の結果が`OK`であることを確認します。チェックサムが違う場合は実行しないでください。チェックサムは配布物の破損や取り違えを検出するためのもので、署名ではありません。

`php2shellblock-install.sh`は自己展開形式です。検証済みモジュール、インストーラー本体、機能テスト、PHPパッチ、変更後PHPソース10ファイルの全文、ライセンスを同梱しています。実行中の追加ダウンロード、ビルド、yumによるパッケージ導入はありません。取得後の検査・適用・復旧はネット接続なしで実行できます。

## 確認URLの選択

既存アプリのPHP表示ページを、`--health-url`で指定します。保存・削除・ログアウトなどを行わないページを選んでください。認証不要のログインフォームなど、連続して取得しても本文が変わらないページが適しています。

URLの接続先は`127.0.0.1`だけを許可しています。200を返す2MiB以下のページが必要で、リダイレクトは追跡しません。時刻や乱数を本文に含む画面、ログイン後に移動する302応答の画面、メンテナンス中の503応答では検査が停止します。公開用の診断ページは自動作成しません。

同じサーバーのLAN側IPであっても、URLの接続先には指定しません。VirtualHostの選択が必要な場合は、接続先を`127.0.0.1`とし、`--host-header`を併用してください。

以下の`/login.php`は例です。実在するPHP表示ページのパスに置き換えてください。

## 事前検査

```sh
sudo bash php2shellblock-install.sh --check \
  --health-url http://127.0.0.1/login.php
```

対応環境とファイルのハッシュを確認し、専用のループバックApacheで修正前後を比較します。PHP拡張、内部関数、既存INI値、gracefulでの切替と復旧を検査します。通常POST、セッション、ファイルアップロード、multipart件数、16MiBのPHP上限を使う合成OOM後の復旧も試験します。実攻撃や任意コード実行の試験ではありません。

このモードは稼働中のApacheを再読込みせず、設定を変更しません。専用の一時ファイル・Apacheプロセスを作成し、終了時に片付けます。既存画面へのGETは、通常のアクセスログやアプリのセッションを生成することがあります。同じホストの資源を使用するため、影響ゼロを保証するものではありません。18081番が別の用途で使用中の場合は停止します。

## 適用

```sh
sudo bash php2shellblock-install.sh --apply \
  --health-url http://127.0.0.1/login.php
```

`--apply`には事前検査も含まれます。検査成功後に元設定とモジュールを退避し、別配置のモジュールを選択してApacheをgracefulで再読込みします。親PIDと全ワーカーの読込み先、指定画面の本文、Asterisk・MariaDBが存在する場合はそのPIDが変わっていないことを確認します。

HTTP・HTTPSを両方確認する場合は、URLを複数指定します。

```sh
sudo bash php2shellblock-install.sh --apply \
  --health-url http://127.0.0.1/login.php \
  --health-url https://127.0.0.1:50443/login.php
```

名前によるVirtualHostがある場合は`--host-header example.com`も指定します。自己署名証明書の環境でも応答確認できるよう、HTTPSの証明書検証は省略します。この検査は証明書の信頼性やTLS/SNI構成全体を確認するものではありません。

同じ候補モジュールがすでに全Apacheプロセスで稼働していれば、再読込みをせず`already_applied_no_changes`で終了します。この場合は新しい退避を作成しません。別の方法で導入した環境では、その導入方法に対応する復旧手順を使用してください。

### 変更するもの

`/usr/local/lib64/php2shellblock/php54-2b343438ad94/libphp5.so`へモジュールを別配置し、`10-php.conf`のNTSモジュール参照と既存`include_path`の維持設定を変更します。`/var/lib/php2shellblock/`にroot専用の退避・適用記録を保存します。

元のPHP RPM、元の`libphp5.so`、`/usr/bin/php`、PHP-FPM、アプリのコード、DBデータ、Apache以外のサービス設定は変更しません。対象はWeb用mod_phpです。CLIや別SAPIへ対策を導入するものではありません。

## 状態確認

```sh
sudo bash php2shellblock-install.sh --status
```

`candidate_active: true`は、対象モジュールがApacheの親子プロセスで読み込まれていることを示します。両CVEの完全修正や、アプリの全機能の正常動作を証明する値ではありません。

## ロールバック

このインストーラーが直近に作成した退避へ戻す場合は、次を実行します。

```sh
sudo bash php2shellblock-install.sh --rollback latest
```

適用時には、次の形式のネットワーク不要な復旧コマンドも表示します。

```sh
sudo sh /var/lib/php2shellblock/実際の退避ディレクトリ/rollback.sh
```

`実際の退避ディレクトリ`は、表示された日時付きの名前に置き換えてください。自己展開シェルを削除した後も、この復旧スクリプトは残ります。元設定・元モジュール・現在の設定のハッシュを確認し、Apacheだけをgracefulで戻します。別の作業で設定や元RPMモジュールが更新されていた場合は、無条件に上書きせず停止します。

適用中の構文エラー、画面本文の不一致、中断などでは自動復旧を試みます。SIGKILL、電源断、ディスク故障、復旧自体のエラーでは完了を保証できません。表示された退避先とサービス状態を確認し、手動復旧してください。同じ候補が適用済みと判定した場合、新しい退避は作成されません。

## 自動検査の範囲

API・INI・合成fixture・指定した画面のGETが自動確認の範囲です。個別DBの読取りや、アプリの実パスワード認証、設定保存、業務ファイル保存、外部連携、負荷試験は自動実行しません。導入前後に、運用者が必要な業務操作を確認してください。

PHPのOOM時にワーカーを終了するため、該当リクエストのshutdown関数、デストラクタ、セッション保存、正常なエラーページ送信は完了しない場合があります。これも互換性確認の対象です。

## 配布物とソース

生成元は[`scripts/installer.sh.in`](../scripts/installer.sh.in)、処理本体は[`scripts/install-runtime.py`](../scripts/install-runtime.py)です。[`scripts/package-release.py`](../scripts/package-release.py)は検証済みSHA-256のバイナリーだけを受け付け、再現可能な時刻・並び順で配布物を生成します。

配布物を生成する開発用ツールにはPython 3.10以上が必要です。導入シェルは`python`、`python2.7`、`python3`の順に確認し、Python 2.7または3.6以上を選びます。OS標準のPythonを置き換える処理はありません。復旧スクリプトにも選択したインタープリターを記録します。

PHP本体の再ビルドは[`scripts/build-remi54.sh`](../scripts/build-remi54.sh)を使用します。署名を検証した元SRPMへ既存のRemiパッチと本プロジェクトのパッチを適用します。詳細は[ビルド手順](build.md)と[検証項目](validation.md)を参照してください。

## 実行時のエラー

### TarFileの__exit__エラー

`AttributeError: 'TarFile' object has no attribute '__exit__'`は、展開処理が使用している`TarFile`にcontext manager機能がない場合に発生します。`v0.1.1`ではこの機能に依存しない処理へ変更しています。導入シェルとチェックサムを両方取得し直してください。

使用できるPythonが見つからなければ、展開前に必要なバージョンと検出結果を表示して終了します。確認には次のコマンドを使用します。

```sh
python -V 2>&1
cat /etc/redhat-release
command -v python2.7 python3
```

Pythonだけを追加しても、別OSや別ライブラリの環境へ配布モジュールを適用できるわけではありません。CentOS 6やPython 2.6のみの構成に対し、OS標準のPythonを無条件に置き換えたり、対応条件を外して強制適用したりしないでください。

CentOS 6などの対応外OSは、Pythonの選択やアーカイブ展開より前に拒否します。`This binary release supports CentOS 7 x86_64 only`と表示された場合、この配布モジュールはその環境に適用できません。

### 確認URLのエラー

`Use an http(s)://127.0.0.1/... health URL`と表示されたら、確認先を同じサーバーのループバックアドレスへ変更してください。

```sh
sudo bash php2shellblock-install.sh --check \
  --health-url http://127.0.0.1/login.php \
  --host-header example.com
```

`example.com`は既存VirtualHostのHost名に置き換えます。名前による選択が不要なら`--host-header`は省略できます。接続拒否の場合は、既存Apacheの待受け設定を確認し、設定を無条件に変更しないでください。
