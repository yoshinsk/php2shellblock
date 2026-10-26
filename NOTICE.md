# ソースとライセンス

本プロジェクト独自の導入・検証用スクリプトと文書には[MIT License](LICENSE)を適用します。PHP/Zend由来のコード、PHP本体向けパッチ、同梱する修正後PHPソースとPHPバイナリーには、以下の元のライセンス条件が適用されます。PHPバイナリーをMITライセンスへ変更するものではありません。

PHP本体向けパッチはPHP 5.4.45と、PHPプロジェクトのPHP 7.4向け最小バックポートをもとにした派生変更です。元のPHPおよびZendの著作権表示・ライセンス条件を維持してください。

`php-5.4.45-remi-overflow-prep.patch`は、RemiのソースRPMに含まれる文字列長検査を、upstreamソースで再現するための準備パッチです。公開用モジュールの生成にはRemiのソースRPMを使用し、この準備パッチを重ねて適用しません。

- [PHP License 3.01](licenses/PHP-3.01.txt)
- [Zend Engine License 2.00](licenses/Zend-2.00.txt)
- [移植元の公式変更](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2)

本プロジェクトはPHPプロジェクトまたはRemiの公式配布物ではありません。これらの名称は移植元と検証対象の説明に使用しています。
