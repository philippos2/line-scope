# Graph時間打切りと部分結果の公開境界

正本はapi-tools §10・§17、transaction-design §16。Graphの公開Tool / Agent登録は引き続き後続。

- BFSへサーバ側の協調停止checkpointを追加する。未探索node・edgeの処理前に停止し、確認済みの距離・前駆だけをTIMEOUTの部分結果として保持する。TIMEOUTはNODE_COUNT / DEPTH / PATH_COUNTより優先する。ストア／整合性異常を空集合や部分成功へ変換しない。
- Application serviceはTool総期限内で終了確認向けの時間を確保する。既定は総timeoutの10%、サーバ内部のcompletion_reserve_msで調整可能。client / LLMからは設定させない。これは処理の配分であり、総期限を延長しない。
- 読取I/Oは既存driver・DB timeoutで制限し、協調停止で実行中queryを強制キャンセルしない。探索後の状態確認・Evidence構築・Neo4j read終了・PG CURRENT / generation再確認を総期限内に完了できた場合だけ返す。総期限到達はRESOURCE_BUSY、終了時Graph不正は既存Graph codeで拒否し、保持済み部分結果も破棄する。
- 返却経路以外のedge事実を公開せず、TIMEOUTを「影響なし」へ変換しない。直接／間接分類、状態観測時刻とversion、過去as_ofのスコープは既存serviceと同じ。
- 新規状態・業務ルール・DB schema・API契約・既存更新Transactionを変更しない。SQL / Cypherを追加せず、LogiScopeコードも再利用しない。開発原則／運用のdocs変更はstashのまま保留する。
