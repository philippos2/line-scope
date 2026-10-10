# Human Approval lock SELECTのCore移行

## 範囲と事前確認

PR #98 merge後main `d6ea397`からHuman Approvalの親ID取得・UpdateRequest FOR UPDATE・親ID条件付きApproval FOR UPDATEの3本をCoreへ移行する。関数はそれぞれ固定SELECTを構築し、呼出順序をserviceの_locked_proposal内へ明示したままとする。

既存の親ID解決 → UpdateRequest → Approval → 保存Snapshot / Target再読込の順序を維持する。通常のblocking FOR UPDATEと既存lock_timeoutを使い、NOWAIT / SKIP LOCKEDは導入しない。承認判定・現在権限・Snapshot hash・target version確認・状態更新・Auditは元のtransactionに留める。

## 変更と移行リスク

query-only Approval宣言へupdate_request_idを追加し、移行済み状態UPDATEとともにcore_approval.pyへまとめる。旧core_approval_updates.pyは新モジュールへ改名する。SQL / UUID bindの分離、native adaptation、dict_rowを維持し、DDL・Engine / pool / autobegin / ORMは導入しない。

移行リスクはlock順序、親ID対応の再確認、保持期間、待機timeout。FOR UPDATEの結果は従来と同じ扱いとし、未知のApproval / 親ID不一致の拒否を変えない。LOOKUPの固定JSONB集約と保存Snapshot再構成は今回移行せず、安全なbind SQLを維持する。別接続取得やservice外でのcommitは行わない。

API / Tool契約、DB schema / GRANT、期限・Snapshot / hash、更新version・正本 / Audit / Outbox原子性、Graph / Projectionは変更しない。LogiScopeコードの再利用はない。

## 検証

- Docker内の実PostgreSQLでApproval service / API / observability・DB role・SQL Injection関連117件成功（追加3）。
- _locked_proposalの実行後、別接続からUpdateRequest / Approvalを更新するとlock_timeoutで拒否され、holder transaction終了後は更新できることを確認する（2件）。保存Snapshot hash一致も確認する。
- 親ID取得の一致と、Approval lock時に不一致のrequest IDでは行が返らないことを確認する（1件）。
- 既存の並行承認・lock timeout後の再試行・業務行lock待機後の承認時刻・終端拒否・rollback・HTTP契約・role権限も回帰確認する。
- ruff check / format check成功（129 files）。
- 全体回帰試験は実行中。確定後に追記する。

NFR-04〜06、AC-05〜08・11・13、T-SQL03〜05の対象Approval部分の確認であり、重要更新全体の完了とは扱わない。既存Starlette warningと終了時logging output failed表示は別のログ改善対象。

## 次の工程

Human Approvalの親ID / lock SELECTと状態UPDATEはCoreへ移行済み。保存Snapshot / JSONB集約、Audit JSONB、proposal保存、Execute、Graph / Outbox、管理処理には安全なRaw SQLが残る。次は型処理・transaction意味・可読性を評価して適切なcheckpointを選び、Core化を目的に無理な抽象化を導入しない。
