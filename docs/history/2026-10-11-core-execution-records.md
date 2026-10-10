# Execute履歴・完了結果のCore移行

## 判断と範囲

PR #102 merge後main `392d25b`から開始。Execute共通処理のbusiness_update_history INSERTとUpdateRequestのCOMPLETED / execution_result UPDATEの2本を移行する。既存は安全なparameterized Raw SQLであり、脆弱性修正ではない。

通常のINSERT / UPDATEは固定Columnとnamed値で型・保存項目の対応を明示できるためCoreを使う。Approval消費のMATERIALIZED CTEは単一clock観測・expires_atとの厳密な比較・RETURNINGがSQLで明確であり、このcheckpointでは安全なRaw SQLを維持する。Core化によるコード増加や期限意味の変更を避ける判断で、任意SQLを許可する意味ではない。

## transactionと型

query-only宣言はmigration 003 / 005の対象Columnだけを反映しDDL生成しない。履歴before / afterと完了resultは明示psycopg Jsonb adaptationでbindし、compile後にSQLAlchemy bind processorを通さない点を記録する。UUID / text / aware datetimeはnative bind。

履歴occurred_atは正本更新時のexecuted_at、要求updated_atはApproval消費CTEが返したconsumed_atを使う。これらを同一時刻と推測せず、新しいclockで置き換えない。確定したbefore / after / resultをそのまま保存し、後日のcurrent値と混同しない。

認可、Request → Approvalのlock、hash / version / business invariant / 承認期限の検証、正本・履歴・category Outbox・Approval消費・完了結果・Auditの順序と同一transactionを維持する。関数はconnection取得・commit / rollback・業務判断を行わない。失敗なら部分commitせず、退役判断・失敗試行Auditの別transactionも既存どおり。

DB schema / GRANT、API / Tool、業務要件、Snapshot / hash、Graph / Projection仕様は変更しない。LogiScopeコード再利用はない。

## 検証

- Docker内の実PostgreSQLでExecute service / API / observability、依存関係・生産割当・保全UPDATE / 記録CREATE / 複合、SQL Injection、DB rolesの205件成功（33.50秒）。
- 既存の実行・再送試験に、履歴JSONBと確定before / afterの一致、保存resultの一致、履歴時刻と実行時刻の一致、要求updated_atと消費時刻の一致、消費時刻が期限未満である確認を追加。
- 既存の並行再送・更新一回、正本 / 履歴 / Outbox / Approval / 完了 / Audit各段階の失敗rollback、直前期限境界、権限・version競合を回帰確認する。
- ruff check / format check成功（132 files）。
- Docker内の全体回帰試験2,319件成功、1 skipped、1 warning（167.51秒）。

NFR-04〜06、AC-05・10・11・13、T-SQL03〜05の対象Execute部分の確認であり、重要更新全体の完了とは扱わない。既存Starlette warningは対象外。

## 残る工程

Executeのload / lock、退役状態UPDATE、カテゴリ別正本・履歴 / Outbox、Graph / Outbox、管理処理に安全なRaw SQLが残る。固定JSONB LOOKUPとApproval消費CTEも理由を明記して維持する。利点と型・lock・transactionリスクを個別評価して次のcheckpointを選ぶ。
