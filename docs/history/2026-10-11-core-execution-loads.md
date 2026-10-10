# Execute / 失敗試行Auditの取得・lockのCore移行

## 判断と範囲

PR #104 merge後main `e425f26`から開始。Executeの要求lock・Approval lock・承認facts読込と、失敗試行Auditの親ID取得・要求status lock・Approval lockの計6箇所をCoreの固定SELECTへ移行する。既存は安全なparameterized Raw SQLであり、脆弱性修正とは扱わない。

要求 / Approvalのlockは固定関数を共有し、同じSQLを増やさない。core_proposalsのlock_replaced_approvalは置換専用でないlock_request_approvalへ改名する。要求はID / status、Execute承認factsは実際に使う5項目を明示取得し、SELECT *による暗黙取得を減らす。DB宣言は対象Columnだけのquery-onlyでDDLは生成しない。

## 維持する境界

Executeのcategory coordination lock → Request lock → Approval lock → 保存LOOKUP / hash検証 → 承認factsの順序を維持する。初期要求rowは存在判定だけに使用され、その後LOOKUPで上書きされるため、取得項目をID / statusに限定しても認可・再送・結果に影響しない。

承認factsはapprover_id / snapshot_hash / approved_at / expires_at / consumed_atを同じstatementで取得する。dict_row / UUID / aware datetimeのnative処理を維持し、clock読込・期限判定・role検証は既存serviceに残す。

失敗試行Auditは元のtransaction終了後の別transactionのまま。親IDは既存find_approval_parentを共有し、Request → Approval lock、未知対象の監査抑止、terminal stateの観測、Audit保存失敗fallbackと元のエラー維持を変更しない。置換のowner確認とretry再照合の順序も変更しない。

通常blocking FOR UPDATE・timeout・transaction終了までの保持を維持する。Core関数は接続 / lock順序 / 認可 / commit / rollbackを管理しない。DB schema / GRANT、API / Tool、Snapshot / hash、正本 / Outbox / Graph仕様は変更しない。LogiScope再利用はない。

## 検証

- Docker内の実PostgreSQLでExecute service / API / observability、Approval observability、proposal / retry / 置換、SQL Injection、DB rolesの184件成功（追加2、19.20秒）。
- 追加2件でExecute _load後、別接続の要求 / Approval更新がlock_timeoutになり、holder transaction終了後には更新できることを確認。Snapshot hashと承認factsの一致も確認。
- 既存の並行実行・再送、直前期限、version / role失効、失敗試行のterminal観測・未知対象・fallback / 秘匿・元エラー維持、置換の並行競合・rollbackを回帰確認。
- ruff check / format check成功（132 files）。
- Docker内の全体回帰試験2,323件成功、1 skipped、1 warning（165.44秒）。

NFR-04〜06、AC-05・10・11・13、T-SQL03〜05の対象部分の確認であり、重要更新全体の完了とは扱わない。既存Starlette warningは対象外。

## 残る工程

カテゴリ別正本・履歴 / Outbox、Graph / Outbox、管理処理には安全なRaw SQLが残る。固定JSONB LOOKUP、server clock、Approval消費CTEも維持する。通常DB操作はCoreを優先し、残すRaw SQLは可読性・PostgreSQL固有機能・transaction意味等の具体的理由で判断する。
