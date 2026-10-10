# 単件Read全8本のCore移行

## 範囲と判断

PR #92 merge後main `27021bc`を起点に、設備・設備状態に続いて保全予定・工程・生産作業・製品・インフラ資源・依存関係の6本をSQLAlchemy Coreへ移行する。モジュール名をcore_equipment_readsからcore_readsへ変更し、固定Tool allow-listからquery-only table / keyを選択する。

対象はmigration 002のUUID・BIGINT・TEXT・BOOLEAN・TIMESTAMPTZだけで、依存関係のeffective_toはNULLもそのまま返す。入力は検証済みUUIDの単件キーだけであり、今回の範囲ではSQLAlchemy独自のbind/result processorを必要としない。PostgreSQL psycopg dialectのcompile結果とbind辞書を既存psycopg接続で分離実行する前回の方式を維持する。

Engine / pool / autobegin / ORM / DDL生成を導入しない。DB schema・権限・API / Tool契約・Evidence・readonly transaction・エラー変換は維持する。検索・割当Read・JSON / custom typeや重要更新への汎用展開は行わない。LogiScopeコードの再利用はない。

## 検証と受入範囲

- Docker内の実PostgreSQLで対象試験221件成功（パラメータ展開で追加19件）、既存Starlette warning 1件。
- 全8本でDB値との完全一致を確認し、既存の全role・missing・入力拒否・観測時刻・接続障害試験を維持する。
- 全8本のCore実行について呼出元の未commit version更新を読めること、接続を引き続き使えること、UUIDがSQL本文へ埋め込まれずbindで渡ることを確認する。
- readonly transactionで実際のUPDATE拒否を確認する試験を全8本へ拡張する。
- Injection / READ_DSN選択・role権限拒否・Outbox rollback関連試験も回帰確認する。
- ruff check / format check成功（128 files）。
- 全体回帰2270件成功、1件skip、既存Starlette warning 1件（156.23秒）。

NFR-04、AC-01・04、T-SQL01〜03の対象部分を確認する。SQL方針全体・業務受入全体の完了とは扱わない。既存Starlette warningと終了時logging output failed表示の原因調査・修正は今回の範囲に含めない。

## 次の工程

単件Read全8本はCoreへ移行済み。次はsearchの固定filter・literal substring・UUID keyset paging・cursor binding・empty時のobserved_atを維持する設計と試験を確認し、扱える単位で移行する。割当Read・Prepare / Approval / Execute・Graph / Outbox経路は引き続き安全な既存Raw SQLと明示的transactionを維持する。
