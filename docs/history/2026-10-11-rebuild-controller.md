# 初回・通常Rebuild controllerの接続

## 範囲と責務

transaction-design §11 / §17、operations §10 / §13、T-R12 / T-L07に従い、callerが取得済みの専用leader接続上で開始 → mutation lock → drain → 正本Snapshot → 新Graph構築・検証 → 公開 → lock解放を接続する。初回seed（Outboxなし）と既存generationの通常Rebuildが対象。worker停止／再開とleader取得はruntime callerの責務として残す。

- controllerがmutation Transactionを所有し、成功・失敗時に終了する。新generationは毎回新UUID。旧generationを削除しない。
- 公開には既存VerifiedGeneration結果だけでなくNeo4jの実marker再確認と全Outbox APPLIED確認を必要とする。検証I/O後とPG公開commit前にも取得済みlockを再確認する。
- leader取得後のrun開始から単一monotonic deadline（既定60000ms）を開始し、flag保存・lock待ち・drain・構築・検証・公開で共有する。期限後の結果を成功と返さない。同期I/Oの制御復帰は既存DB / driver timeoutにも依存し、残り予算のtimeout伝播はまだ後続。
- 各drain step前とSnapshot取得前に、flag / Rebuild ID / 旧generationを照合してcontrol.updated_atを短いTransactionで更新する。heartbeatでfatalを解除したり、公開／生存の証拠としたりしない。
- 失敗時はmutation Transactionを終了した後、元leaderを再確認して既存の固定REBUILD_FAILED保存を試みる。deadline後のfailure保存は期限guardではなく元leaderを使用し、DB timeoutで制限する。leader喪失時はreconnectせずflagを次controllerの復旧対象として残す。
- failure保存を確認できない場合、または公開済み／所有条件不一致でfailure更新できない場合はUNKNOWN。確定済み公開commitを巻き戻したと推測しない。元例外を伝播し、cleanup障害があればその安全な診断をログへ残す。
- 開始・完了・失敗ログは既存allowlistと内部request_idを使用する。失敗ログのgraph_generationは構築候補があればそのIDで、公開の証拠ではない。再開時はPG pointer / flag / rebuild_idとNeo4j markerを確認する。

## 検証と残課題

実PG / Neo4jで空初期化、既存Graphからdrain・新世代公開、旧Graph保持、DEAD中止、共通deadline、構築／検証障害、lock timeout、leader / lock喪失、cleanup保存失敗、公開commit後の未知結果、stale flag、heartbeat fenceを検証する。

Restore作業用generation、既存flagのcrash再開判定、孤立generation cleanup、残り予算のI/O timeout伝播、管理role / credential / CLI、通常worker停止・再開は後続。これだけでRebuild復旧受入全体を完了扱いしない。新規SQLはheartbeatの固定SQLAlchemy Coreのみ、migration・HTTP / Agent公開なし。LogiScopeコード再利用なし。
