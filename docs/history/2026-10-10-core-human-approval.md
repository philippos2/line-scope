# Human Approveと対象競合失効のCore移行

## 範囲・事前確認

PR #97 merge後main `1fcb355`からHuman Approve成功時と対象競合失効時の状態UPDATEをCoreへ移行する。前回Rejectの限定的native write層へ専用関数を追加する。

既存のtrusted context・現在権限・Snapshot hash・状態判定・カテゴリscope・対象version / business invariant検証はservice側に維持する。UpdateRequest → Approval → 必要な業務行のlockと、Approval → UpdateRequest → Auditの書込順序を変更しない。主transactionはProposalStoreのREAD COMMITTEDで、失効はcommit後にVERSION_CONFLICT等を返す。失敗時の別transactionによるFAILURE Auditを維持する。

## 変更と型・移行リスク

Approveは既存と同じvolatile clock_timestamp CTEからapproved_atを一度だけ観測し、approved_at / updated_atを共用する。期限は固定timedelta(minutes=30)をPostgreSQL INTERVAL bindとして加え、approved_at / expires_atをRETURNINGする。Python時計から期限を計算せず、TTLを外部入力にしない。実行順はApproval UPDATE → UpdateRequest UPDATEで、同じ既存psycopg接続を使用する。

競合時はApproval / UpdateRequestをINVALIDATEDへ更新し、同じ主transactionのINVALIDATE Auditとcommit後の競合通知を維持する。共通のrequest更新補助はこの2状態だけを許可し、任意の状態を設定する公開APIにしない。

入力はUUID / text / 固定timedeltaで、native psycopg adaptationの範囲と実DBで確認する。RETURNINGは既存dict_rowでaware timestampを受け取る。部分Column宣言はquery-onlyでmigration 003を正とし、DDL・Engine / pool / autobegin / ORMを導入しない。

移行リスクはclockの複数評価、期限差、UPDATE順序、後続Audit失敗時のrollback。成功・失効の両経路で検証する。JSONB Audit・Snapshot / hash・Executeの業務version / 正本 / Outbox原子性・Graph / Projectionを変更しない。LogiScopeコードの再利用はない。

## 検証

- Docker内の実PostgreSQLでApproval service / API / observability・DB role・SQL Injection関連114件成功（追加5）。
- UpdateRequest更新時 / Audit保存時の失敗注入 × 成功 / 対象競合の4件で、Approval / UpdateRequestの全値・更新時刻・期限が更新前へrollbackし、成功 / 失効Auditがなく、別transactionのFAILURE Auditだけが残ることを確認する。
- 引用符・DROP文字列・日本語を含むtrusted actor IDの値保存とAudit、同一approved_at / updated_at、exact 30分、RETURNINGと保存値の一致を確認する（1件）。
- 既存の並行承認・再承認拒否・期限非延長・対象競合のcommit・認可・HTTP契約・role権限も回帰確認する。
- ruff check / format check成功（129 files）。
- 全体回帰2308件成功、1件skip、既存Starlette warning 1件（160.04秒）。

NFR-04〜06、AC-05〜08・11・13、T-SQL01・03〜05の対象Approval部分を確認する。Executeの30分境界受入や重要更新全体の完了とは扱わない。既存Starlette warningと終了時logging output failed表示は別のログ改善対象。

## 再開地点

Human Approve / Rejectの状態更新はCoreへ移行済み。lock / lookup・Audit JSONB・proposal保存・Execute・Graph / Outbox・管理処理は安全なRaw SQLを維持する。次はlock / lookupや型処理の契約を確認して適切なcheckpointを選ぶ。複雑さを増したりtransaction意味を隠す抽象化は導入しない。
