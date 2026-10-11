# RebuildControlの短いtransactionへの残り予算伝播

仕様正本はtransaction-design §17・§20、operations §10。本記録は実装判断の履歴。

- deadline guardが渡された開始・観測・heartbeat・Restore staging・復旧所有権引継ぎ・最終公開の短いtransactionで、既存のPostgreSQL timeout短縮処理を使う。接続確立後、control queryの前に残り予算を再計算する。
- deadlineを持たない通常leaderでの直接呼出しは既存設定を維持する。失敗保存は既存の別transaction・元leaderで行い、終了したRebuild期限を失敗保存へ転用しない。
- SQLAlchemy Core、bind、transaction-local設定、既存上限の非延長を維持する。transaction所有権、fence、lock順、generation検証・公開条件を変更しない。
- 実PGで短いtransactionへの設定伝播、control rowのlock競合によるrollback、期限不足時の無変更、build後の公開予算再計算を検証する。
- queue/ACK、leader照会、接続確立・ネットワーク・CPU、全statementごとの再設定は対象外。厳密なwall-clock上限の完成とは扱わない。正本文書・API・DB schemaは変更せず、LogiScopeコードは再利用していない。
