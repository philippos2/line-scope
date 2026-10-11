# Rebuild排他transactionのPostgreSQL予算伝播

仕様正本はtransaction-design §17・§20、operations §10。本記録は実装判断の履歴。

- controllerの排他transactionで、mutation lock取得前と正本Snapshot取得前にstatement_timeout/lock_timeoutを残り予算で短縮する。Restore作業用Snapshotと最終Snapshotに同じ処理を使う。
- graph/postgres_timeoutは期限とtransaction条件を確認し、Persistenceの固定Core queryを使う。pg_catalog.pg_settingsの現在値・単位を読んでから予算を再計算し、pg_catalog.set_config(..., true)でtransaction-localな上限を設定する。動的値はbindし、任意設定名を受け付けない。
- 現在の短い設定は延ばさない。0（未設定の上限）は正の予算へ制限する。1ms未満・期限切れ・不正予算は変更を拒否し、timeout無効化へ丸めない。
- commit/rollback・接続所有権・lock順・Snapshot・Outbox・公開条件は維持する。transaction終了後のsession設定を変更しない。期限後の失敗保存は既存の別transaction・元leaderによる手順を維持する。
- controllerの排他connectionだけが今回の範囲。control/queue/ACKの短いtransaction、leader照会・接続確立・ネットワーク・CPU、全statementを毎回残り時間へ短縮する制御は後続。厳密なwall-clock上限の完成とは扱わない。

根拠: [PostgreSQL設定とpg_settings](https://www.postgresql.org/docs/current/config-setting.html)、[statement_timeout / lock_timeout](https://www.postgresql.org/docs/18/runtime-config-client.html)。

実PGで既存上限保持、単位付き設定・無制限設定の扱い、transaction終了時の復元、無効予算拒否、statement timeoutによるrollbackを検証する。controllerの実lock待ちで予算による中断と失敗保存を確認し、drain後のSnapshotで上限を再計算する結合試験も行う。正本文書・API・DB schemaを変更せず、LogiScopeコードは再利用していない。
