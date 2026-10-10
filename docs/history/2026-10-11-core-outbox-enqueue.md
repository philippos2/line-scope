# Graph Outbox登録境界のCore移行

## 判断と範囲

PR #108 merge後main `99f7663`から開始。enqueue_graph_targetの保存Target照合SELECTとイベントINSERTの2箇所をcore_outboxの固定Core statementへ移行する。既存SQLもparameterizedであり、脆弱性修正とは扱わない。query-only Columnはmigration 003 / 006に合わせ、DDL / ORM / Engine / poolを導入しない。LogiScope再利用はない。

## 維持する境界

active READ COMMITTED transactionの検証、要求UUID正規化、Target種別 / 形の検証、保存Targetとのcanonical一致確認、payload / outbox ID生成はenqueue_graph_targetに残す。要求ID / Target種別 / Target IDをすべてbindし、照合に使用する8項目を明示取得する。CREATEのbefore / expected_versionはSQL NULLのまま取得する。

INSERTは既存の8列を明示保存する。payloadはpsycopg Jsonb adaptationを使い、UUID / BIGINT / event_typeをbindする。status=PENDING、attempt_count=0、created_atとその他のNULL項目は従来のDB defaultを使う。ON CONFLICTや重複の黙殺は導入しない。

呼出元の接続 / transactionを使い、Graph mutation lock取得順序、正本 / 履歴 / Outbox / Approval消費 / 完了 / Auditの原子性を維持する。独立commit・retry・worker処理は関数に持たせない。DB schema / GRANT、API / Tool、Snapshot / hash、payload schema、Graph同期状態・rebuildの意味は変更しない。

## 検証

- Docker内の対象250件成功（追加なし、36.12秒）。
- Docker内の全体回帰試験2,336件成功、1 skipped、1 warning（167.35秒）。
- 既存の実PostgreSQL試験で保存Target改変 / 他要求拒否、autocommit拒否、完全payloadとPENDING defaults、重複制約、正本とイベントのrollback、commit前後のCURRENT → LAGGING境界を確認する。
- Dependency / Assignment ExecuteとAPIの段階別rollback・遅いOutbox失敗・並行実行・承認期限・確定結果再送を回帰確認する。
- SQL表記検出フックは追加せず、既存の関数境界・DB triggerによる失敗注入を使用する。検証済み仕様を重複する新規テストは追加しない。

- Docker内のruff check / format check成功（139 files）。

NFR-04〜06、AC-05・10〜13・18、T-SQL03〜05の対象部分とtest-plan §6のOutbox原子性等の確認であり、受入基準全体の完了とは扱わない。

## 残る工程

worker / controller / 管理処理、Prepare / Approval等の一部参照には安全なRaw SQLが残る。通常操作はCoreを優先し、PostgreSQL固有制御・固定JSONB集約は具体的理由に基づき維持する。
