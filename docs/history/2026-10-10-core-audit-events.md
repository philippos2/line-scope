# 業務Audit INSERTのCore移行

## 判断と範囲

PR #99 merge後main `3e48db2`から開始する。Prepare・置換失効・Human Approve / Reject・Execute系状態遷移・失敗試行のupdate_audit_event INSERT 6箇所を確認した。すべて既存は安全なparameterized Raw SQLであり、脆弱性修正とは扱わない。

同じ11項目の位置引数とSQL文字列が重複しているため、固定Column参照とkeyword引数で対応付ける専用Core INSERTへまとめる利益がある。業務判断・action・前後status・イベントIDは呼出元に残し、汎用repository / executorや暗黙transactionを導入しない。DB constraint・API契約・認可・GRANT・Snapshot / hash・Graph / Outbox仕様は変更しない。LogiScopeコードの再利用はない。

## 型とtransactionの確認

core_auditはmigration 004を反映したquery-only宣言からINSERTを構築する。UUID / text / NULLはnative bind、detailsのみ既存psycopg Jsonb adapterを明示してJSONB bindへ渡す。compileした本文とparameter辞書を分離して既存psycopg connectionで実行する。この経路はSQLAlchemy bind processorを通らないので、dict直接bind・二重serialize・他のcustom typeへの一般化はしない。

occurred_atは既存どおりclock_timestamp。関数はconnectionを取得・終了せず、commit / rollback / lock / 状態遷移も行わない。Prepare / 置換 / Approval / Execute成功Auditは呼出元の更新と同じtransactionに留まり、保存失敗なら更新もrollback。Executeの履歴・Outbox・Approval消費・COMPLETEDの原子性を変えない。

失敗試行の監査は元のtransaction終了後のbest-effort別transactionを維持する。request / approvalの再取得とlockの安全なRaw SQLは今回移行せず、保存不能時の秘匿済み運用ログfallback・元のエラー維持も変更しない。

## 検証

- Docker内の実PostgreSQLでPrepare Audit、Approval / Execute observability、Approval / Execute、SQL Injection、DB rolesの113件成功（追加3）。
- 追加2件で日本語・入れ子JSON・JSON null / false / 0・SQL攻撃文字列・nullable approval / before_statusの保存再読込を確認。JSON objectのまま保存され、通常のproposalとequipmentテーブルも維持される。
- 追加1件で呼出元が例外rollbackした後にAuditが残らないことを確認。
- 既存のPrepare / 置換失効 / Approval / Execute成功Audit保存失敗時のrollback、失敗試行の別transaction、fallback・秘匿・terminal state・DB権限も回帰確認。
- ruff check / format check成功（130 files）。
- Docker内の全体回帰試験2,314件成功、1 skipped、1 warning（160.57秒）。

NFR-04〜06、AC-05・10・11・13、T-SQL01・03〜05の対象Audit部分の確認であり、SQL方針や重要更新全体の完了とは扱わない。既存Starlette warningは今回の修正対象外。

## 残る工程

保存Snapshot / JSONB集約、proposal保存、Executeの正本・履歴・Outboxと状態更新、Graph / Outbox、管理処理には安全なRaw SQLが残る。Core移行の利点とtransaction・lock・型処理のリスクを個別に評価し、PostgreSQL固有処理や複雑な集約を無理に抽象化しない。
