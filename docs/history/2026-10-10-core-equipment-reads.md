# 設備ReadのSQLAlchemy Core導入

## 変更と判断

PR #91 merge後のmain `1aef94b`から、設備取得get_equipment / get_equipment_stateの2本だけを移行する。API / Tool schema、対象権限、missing時のerror、Evidence、JSON返却項目、READ COMMITTED / READ ONLYは維持する。

SQLAlchemy 2.0系列の修正版2.0.54を固定する。Python 3.14.4コンテナで追加依存を解決し、greenlet 3.5.6と既存typing_extensions 4.16.0をruntime / dev lockへ反映する。

固定table / columnのquery-only宣言とselectで構築し、PostgreSQL psycopg dialectによるcompile結果のSQL本文・parameter辞書を別引数として既存psycopg接続へ渡す。UUIDはpsycopgがadaptし、結果は既存dict_rowが復号する。literal_binds・値補間・DDL生成・ORMは使用しない。

この段階でEngine / pool / autobeginを導入すると、既存接続所有権・transaction・dict_rowの変更を同時に伴うため、今回のUUID Read専用の橋渡しを選ぶ。汎用SQLAlchemy実行基盤とは扱わず、bind / result processorを要するJSON・custom type等や重要更新へそのまま展開しない。後続で接続管理や型処理が必要なら個別設計・回帰試験を行う。

参考: [SQLAlchemy公式compile・bindの説明](https://docs.sqlalchemy.org/en/20/faq/sqlexpressions.html)、[2.0.54配布情報](https://pypi.org/project/SQLAlchemy/2.0.54/)。デバッグ用の文字列補間例は実行経路へ採用しない。LogiScopeコードの再利用はない。

## 検証

Docker内の実PostgreSQLで既存Read / search / SQL Injection / READ_DSN / role拒否を回帰確認する。追加4ケースは2本それぞれについて、全返却値のDB一致、攻撃文字列・日本語の保存値をコード化しない再読込、native UUID / bool / timestamp、呼出元の未commit更新の可視性と接続継続、実行SQLとUUID bindの分離を確認する。

- 対象試験202件成功（追加4）、既存Starlette warning 1件。
- ruff check成功、format check 128 files成功。
- 全体回帰試験2251件成功、1件skip、既存Starlette warning 1件（153.96秒）。

NFR-04、AC-01・04、T-SQL01〜03の対象Read部分を回帰確認する。SQL policy全体の完了、Business Scenarioの完了とは扱わない。終了時の既存logging output failed表示は別のログ改善対象であり、この変更では原因や修正完了を断定しない。

## 残課題と再開地点

他6本の単件Read、4本のsearch、割当Read、Prepare / Approval / Execute、Graph / Outbox関連のDBアクセスは今回移行しない。既存の安全なRaw SQLを維持し、更新transaction・lock・Snapshot / hash・Outbox・Projectionの意味を変更しない。次は通常Readの残りから、検索ページング・観測時刻・型処理を維持できる単位で進める。DB role・GRANT・migration・業務要件の変更はない。
