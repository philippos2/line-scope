# 設備検索のSQLAlchemy Core移行

## 範囲と判断

PR #93 merge後main `b054cc5`からsearch_equipmentだけをCoreへ移行する。固定equipment_code等値・nameの大小文字非依存literal substring、UUID keyset境界、昇順、page_size+1件の取得を構造化SELECTで表す。名前検索は従来のstrpos(lower(name),lower(value))を維持し、% / _をwildcardとして扱わない。

単件Readと同じquery-only equipment宣言を利用する。新たなbindはtext・integer・UUIDだけでpsycopg native adaptationで扱える。Coreのcompile結果とparameter辞書は分離実行し、値補間・外部identifier・Engine / pool / autobegin / ORMは導入しない。JSON / custom type等や重要更新を扱う汎用実行基盤にはしない。

page CTEを一行のobservationへLEFT JOINし、空ページでもstatement_timestampを得る既存方式を維持する。返却行からitems / has_more / next_cursorを作る既存処理だけを共通メソッドへ分け、他3本の検索にも適用する。cursor署名・owner / role / Tool / filter binding・TTL検証は変更しない。

API / Tool契約、権限、READ COMMITTED / READ ONLY、Evidence、DB schema / GRANT、更新transaction / lock / Snapshot / hash / Outbox / Graphは変更しない。LogiScopeコードの再利用はない。

## 検証

Docker内の実PostgreSQLでRead / search / SQL Injection / READ_DSN / DB role関連231件成功（追加10件）。既存の大小文字・% / _・filter AND・inactive対象・空結果・複数ページ・最大件数・最新値・cursor binding / 改ざん拒否を回帰確認する。

追加試験はname / equipment_codeそれぞれの攻撃文字列と日本語 %_のbind分離・保存値再検索、未commit変更の可視性、全native返却値、page_size+1件と昇順、空結果と各行の観測時刻、readonly transactionの実UPDATE拒否を確認する。空結果fixtureも公開契約で許可された検索文字列を用いる。

- ruff check / format check成功（128 files）。
- 全体回帰2280件成功、1件skip、既存Starlette warning 1件（157.87秒）。

NFR-04、AC-01・04、T-SQL01〜03の対象Read部分の確認であり、SQL方針全体・業務受入全体の完了とは扱わない。既存Starlette warningと終了時logging output failed表示は別のログ改善対象として維持する。

## 次の工程

単件Read8本と設備検索はCoreへ移行済み。保全予定・保全実績・依存関係検索、割当Read、更新系は安全な既存Raw SQLのままとする。次は残り検索のnullable filter・多型endpointの固定allow-list・cursor semanticsを維持できる単位で進める。
