# Human Reject状態更新のCore移行

## 対象と事前確認

PR #96 merge後main `dec5438`からHuman Rejectの状態UPDATE 2本をCoreへ移行する。Approval層・ProposalStoreのtransactionと重要更新の境界を確認し、UUID / textだけを渡すこの部分を最初の小さなwrite checkpointに選ぶ。

| 確認項目 | 現行動作・今回の扱い |
|---|---|
| transaction | ProposalStore._transactionによるREAD COMMITTED。状態UPDATE 2本とREJECT Auditを同じtransactionでcommit。維持する |
| lock | approvalから親ID解決後、UpdateRequest → ApprovalのFOR UPDATEと保存Snapshot再読込。順序・保持期間を維持する |
| 認可・状態 | trusted context、validate_reject、カテゴリscopeを更新前に確認。終端・再Reject拒否を維持する |
| version | Rejectは業務正本を更新しない。Executeのexpected version検証・条件付き更新は今回変更しない |
| audit | REJECT成功Auditは主transaction内。失敗時は主transaction rollback後、別transactionのFAILURE auditを維持する |
| outbox | Rejectでは正本変更・Outbox生成をしない。Executeの原子性境界は変更しない |

## 変更と移行リスク

core_approval_updatesにmigration 003に一致する部分Column宣言とReject専用関数を置く。Approval UPDATE → UpdateRequest UPDATEの実行順とclock_timestampを維持し、Core compile結果のSQL本文とbind辞書を既存psycopg接続へ渡す。入力はUUID / textだけで、native adaptationの範囲と判断する。

関数自身は接続取得・lock・認可・commitを行わない。呼出元の認可済み・lock取得済みtransactionが前提であり、汎用のDB write executorや公開APIではない。Engine / pool / autobegin / ORM / DDL生成を導入しない。

変更リスクは状態UPDATEのbind・実行順・後続Audit失敗時のrollback。実DBで注入失敗を検証する。Snapshot / hash・Approval期限・業務version・Graph / Outbox / Projectionを変更しない。Auditの既存JSONB bindは今回維持し、JSON / custom type等への移行は型処理を別途評価する。LogiScopeコードの再利用はない。

## 検証

- Dockerの実PostgreSQLでApproval service / API / observability・DB role・SQL Injection関連109件成功（追加3）。
- UpdateRequest更新時・REJECT Audit保存時の注入失敗2件で、Approval / UpdateRequestの全値と更新時刻が更新前と一致し、成功Auditがなく、別transactionのFAILURE Auditが1件保存されることを確認する。
- 引用符・DROP文字列・日本語を含むtrusted actor IDがそのままapprover / Auditへ保存され、equipmentが維持されることを確認する。実際の認可はcallerのtrusted contextで行い、任意入力からroleを生成する経路は追加しない。
- 既存の終端・非owner・self approval・HTTP契約・期限・競合・監査失敗・role権限を回帰確認する。
- ruff check / format check成功（129 files）。
- 全体回帰2303件成功、1件skip、既存Starlette warning 1件（158.02秒）。

NFR-04〜06、AC-05・11・13、T-SQL01・03〜05の対象Reject部分を確認する。重要更新全体・Execute / Outbox受入全体の完了とは扱わない。既存Starlette warningと終了時logging output failed表示は別のログ改善対象。

## 再開地点

Human Rejectの状態UPDATE 2本のみCoreへ移行済み。Approve / invalidate・proposal保存・Execute・Audit JSONB・Graph / Outbox・管理処理は安全なRaw SQLを維持する。次のcheckpointはlock / clock / RETURNING / 型処理・既存rollback試験を確認した上で選ぶ。SQL構築を抽象化し、transactionの意味と副作用を隠さない。
