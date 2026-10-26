# インストーラーの検証方法

公開用インストーラーは、入力検査、PHPの互換性、適用・復旧処理、配布ファイルの整合性を対象に検証しています。

## 検証条件

CentOS 7、Python 2.7、bash、root権限、umask 077で実行しています。適用・復旧の試験では、別の設定・PID・ログ・DocumentRootを持つループバック専用Apacheを使用します。

統合試験はサービス操作部分だけを専用Apacheへのシグナルに置き換え、切替、退避、ハッシュ照合、HTTP比較、自動復旧には配布用と同じ処理を使用します。

## 検査項目

|項目|確認内容|
|---|---|
|導入エンジンの単体試験10件|URL制限、対象設定、検査モード、適用、復旧、競合・退避改変の拒否、復旧用Pythonの維持|
|起動・展開の回帰試験12件|対応OS・CPUの判定、context managerなしのTarFile、ファイルの閉鎖、危険なアーカイブの拒否、利用可能なPythonの選択|
|シェル|`bash -n`による構文検査、Python 2.7・umask 077での自己展開|
|ファイルの整合性|外部チェックサム、埋込みアーカイブ、manifest内の各ファイルのハッシュ照合|
|破損ファイル|埋込みデータを変更したシェルを、導入処理の起動前に拒否|
|適用|元PHPから候補PHPへのgraceful切替とHTTP応答|
|再実行|同じ候補が稼働している場合に変更せず終了|
|手動復旧|元の設定・モジュール・HTTP応答への復旧|
|自動復旧|候補使用時だけ画面本文が変わるfixtureで、不一致検出後に復旧|
|PHPの互換性|拡張、内部関数、既存INI値が一致し、新規INIが想定した項目だけであること|
|生成の再現性|同じ入力から生成した配布ファイルが一致すること|

実行用スクリプトは[`tests/installer_unit.py`](../tests/installer_unit.py)、[`tests/installer_integration.py`](../tests/installer_integration.py)、[`tests/installer_bootstrap.py`](../tests/installer_bootstrap.py)です。統合試験には展開済みpayloadを指定します。

展開の回帰試験ではPython 3上で、`__enter__`・`__exit__`を持たないTarFileと読取りハンドルを再現します。Pythonの選択処理はPOSIX bash上で試験します。これはPython 2.6で導入エンジン全体が動作するという意味ではありません。

## 確認範囲

この検証は、実攻撃の再現や両CVEへの完全な有効性の立証を含みません。業務上の認証・保存・外部連携、負荷試験、SIGKILLや電源断からの自動復旧も対象外です。

PHP本体の機能試験は[検証項目と限界](validation.md)、導入時の確認範囲は[導入手順](install.md)を参照してください。
