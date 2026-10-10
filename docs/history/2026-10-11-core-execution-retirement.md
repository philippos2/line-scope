# Execute失効状態のCore移行

## 判断と範囲

PR #103 merge後main `54bc9b6`から開始。Execute失敗後の_retireで行うApproval / UpdateRequestの状態UPDATE 2本をCoreへ移行する。既存は安全なparameterized Raw SQLであり、脆弱性修正とは扱わない。

query-only core_executeへApprovalの対象Columnを追加し、UUID / status bindとclock_timestampによる固定UPDATEを構築する。EXPIRED / INVALIDATEDだけを許可する内部関数とし、失効理由の選択やtransaction管理を隠す抽象化は導入しない。

## 維持する境界

失敗したExecuteのtransaction終了後、別transactionでcategory coordination lock → Request / Approval lock → owner / scope / COMPLETED確認 → 承認・Target再検証を行う。実行済みなら保存resultを返し、APPROVED / APPROVEDだけを失効候補とする。期限切れをEXPIRED、その他の定義済み競合をINVALIDATEDとする判断はserviceに残す。

Approval → UpdateRequest → 成功失効Auditの順序・同一transactionを維持する。status / updated_at以外は変更せず、Snapshot・Target・承認時刻 / 期限・確定結果を保存したままにする。失効Audit保存失敗で両状態をrollbackし、後続の失敗試行AuditとAPIエラー秘匿は既存境界を維持する。

通常Executeの正本 / 履歴 / Outbox / 承認消費 / 完了保存、DB schema / GRANT、API / Tool、業務要件・version・Graph仕様は変更しない。Approval消費の安全なMATERIALIZED CTEは前checkpointの判断どおり維持する。LogiScope再利用はない。

## 検証

- Docker内の実PostgreSQLでExecute service / API / observability、依存関係・生産割当、SQL Injection、DB rolesの156件成功（追加2、25.08秒）。
- 追加2件で期限切れ / version競合の失効Auditに失敗を注入し、要求・承認の全項目が元のまま、履歴と成功失効Auditが未保存であることを確認。エラー本文を秘匿し、原因除去後の再試行で正しい失効状態とAudit 1件が保存される。
- 既存のrole失効・期限直前rollback・COMPLETED再送・並行実行・各段階の原子性・認可 / version境界を回帰確認。
- ruff check / format check成功（132 files）。
- Docker内の全体回帰試験2,321件成功、1 skipped、1 warning（163.98秒）。

NFR-04〜06、AC-05・10・11・13、T-SQL03〜05の対象Execute部分の確認であり、重要更新全体の完了とは扱わない。既存Starlette warningは対象外。

## 残る工程

Executeのload / lock、カテゴリ別正本・履歴 / Outbox、失敗試行Auditの再取得・lock、Graph / Outbox、管理処理に安全なRaw SQLが残る。固定JSONB LOOKUPとApproval消費CTEも維持する。利点と型・lock・transactionリスクを個別評価して次のcheckpointを選ぶ。
