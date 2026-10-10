# Prepare置換lock・失効のCore移行

## 判断と範囲

PR #101 merge後main `bd7200c`から開始する。ProposalStore.saveの置換対象UpdateRequest / ApprovalのFOR UPDATE SELECT 2本、旧UpdateRequest / ApprovalのINVALIDATED UPDATE 2本を移行する。既存は安全なparameterized Raw SQLであり、脆弱性修正とは扱わない。

既存のquery-only core_proposals宣言へupdated_atを追加し、固定Column・UUID bind・clock_timestampで構築する。owner / retry / 旧状態の判断や失効順序を隠す抽象化は導入しない。Human Approvalの状態更新とは呼出順序が異なるため、そちらの複合更新関数を流用しない。

## 維持するtransaction境界

serviceにUpdateRequest lock → requester確認 → Approval lock → retry再照合 / 旧Snapshot検証 → 新要求 / Target / Approval保存 → 旧UpdateRequest失効 → 旧Approval失効 → 置換Audit / Prepare Auditを明示する。

通常blocking FOR UPDATE、既存lock_timeout、同一connection・transaction終了までのlock保持、READ COMMITTEDで待機後に勝者再照合する挙動を維持する。NOWAIT / SKIP LOCKED、独立接続・commit・暗黙状態更新は導入しない。

失効はstatus / updated_atだけを変更し、Snapshot text / hash・Target・approved_at / expires_atを保持する。新保存・旧失効・Auditは同一transactionで、Approval / Audit保存失敗ならすべてrollbackする。DB schema / GRANT、認可、API / Tool、承認期限、正本 / Outbox / Graph仕様は変更しない。固定JSONB集約LOOKUPは今回維持する。LogiScopeコード再利用はない。

## 検証

- Docker内の実PostgreSQLでproposal保存 / retry / 置換、Prepare Audit、SQL Injection、DB rolesの152件成功（14.35秒）。
- 既存のPENDING / APPROVED置換、旧Snapshot / Target / 承認時刻 / 期限維持、並行置換の勝者、same-key異入力、owner / role拒否、終端拒否、両rowのlock_timeoutを回帰確認する。
- 既存の新Approval / 旧Approval / 置換Audit失敗注入で、新保存と旧失効の全rollback・同key再試行を確認する。
- ruff check / format check成功（131 files）。
- Docker内の全体回帰試験2,319件成功、1 skipped、1 warning（166.14秒）。

今回は既存の実DB競合・rollback試験が変更境界を直接検証するため、同じassertionの新規テストは追加しない。NFR-04〜06、AC-05〜08・11・13、T-SQL03〜05の対象proposal部分の確認であり、重要更新全体の完了とは扱わない。既存Starlette warningは対象外。

## 残る工程

ProposalStoreの通常保存と置換のwrite / row lockはCoreへ移行済み。保存Snapshotの固定JSONB集約LOOKUP、失敗試行Auditの再取得・lock、Execute正本・履歴・Outbox / 状態更新、Graph / Outbox、管理処理は安全なRaw SQLが残る。利点と型・lock・transactionリスクを個別評価して次のcheckpointを選ぶ。
