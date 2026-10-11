# Rebuildの残り時間をNeo4j transactionへ伝播

仕様正本はtransaction-design §17・§20、operations §10。本記録は実装判断の履歴。

- Neo4jGenerationのbuild/検証情報観測/公開前検証、Neo4jProjectionのapplyで、BEGIN直前に通常timeoutと内部leader guardの残り予算の小さい方を指定する。通常leaderには残り予算がなく、既存設定を維持する。
- 純粋なtimeout変換をgraph/transaction_timeoutへ局所化し、adapterがRebuild controller/drainの具象をimportする依存を追加しない。内部guardのoptional remaining()を使う。設定やadapter instanceを書き換えず、各transactionで計算する。
- DeadlineLeadershipが入れ子の場合も親の早い期限を引き継ぐ。driverのsessionへ入る間に消費した時間をBEGIN直前の再計算で含める。
- Boltのtx_timeoutは整数millisecond、Python APIの0は無制限なので、millisecond単位に切り下げ、1ms未満・期限切れ・不正予算ではBEGINを拒否する。無制限timeoutへ丸めない。
- driver transaction所有権、bind、retry、marker version/hash、commit後leader確認、PG ACK/control更新の意味は維持する。期限を超えたGraphを公開しないチェックも維持する。
- これはNeo4jサーバtransactionの予算伝播。接続獲得・ネットワークI/O・PG statement/lock待ち・CPU処理・サーバの期限監視遅延を含む厳密なwall-clock上限の完成とは扱わない。残るI/O予算伝播、worker daemon/CLI、Graph欠損修復・cleanupは後続。

根拠:
- [Neo4j Python Driver API — begin_transaction timeout](https://neo4j.com/docs/api/python-driver/current/api.html)
- [Bolt message specification — BEGIN tx_timeout](https://neo4j.com/docs/bolt/current/bolt/message/)

純粋な予算境界、入れ子guard、実driverへ渡ったBEGIN値、session入口での期限消費を検証する。実Neo4jのmarker lock待ちを残り予算でtimeoutさせ、変更rollback・自動retryなしを確認する。controllerのbuild→公開前検証で共通予算が減る結合試験も行う。API・DB schema・正本文書を変更せず、LogiScopeコードは再利用していない。
