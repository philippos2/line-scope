# Rebuild専用Outbox claim・lease回収

## 範囲と責務

保持済みleader / exclusive mutation transaction上で、Rebuild専用のclaim・期限切れPROCESSING回収を開始する内部部品を追加した。短いPG transactionだけでOutbox状態を保存し、Graph mutation lockを再取得しない。

controlのflag=true、rebuild_id、対象generationがticketと一致する場合だけ進む。全Outbox集合のDEADはclaim・回収前に停止する。全APPLIEDまたはイベントなしはDRAINED、未処理があって候補がまだdueでなければWAITINGとし、完了を推測しない。対象generationのない未処理はRestoreの作業用世代が必要として拒否し、attemptを消費しない。generationのNeo4j検証は後続の適用 / controllerが担当し、PG pointer存在を検証済みGraphの証拠とはしない。

期限切れPROCESSINGはRETRYABLEへ戻し、attemptは次のclaim時だけ増やす。上限候補は追加PROCESSINGを開始せずDEADをcommitする。DEAD結果はcontrollerが中止すべき状態であり、通常の完了ではない。既存fatal_errorは復旧対象として許容する。

## 共通化の判断

通常workerとRebuildでclaim / lease状態遷移を重複実装せず、同じCore statement builderを専用の固定gateから呼ぶ。通常workerのflag=false gateは変更しない。SQL identifierと条件はコード内の固定定義で、値はbind parameter。transaction所有者・取得順・attempt / lease / backoff仕様を変える抽象化ではない。

## 試験と後続

実PGで通常workerのfence、専用claim、全集合DEAD停止、期限切れ回収、将来retry / 有効lease待機、上限DEAD、APPLIED終端、初回empty、generation欠損、stale ticket、exclusive lock、leader喪失を検証する。

Neo4j適用とAPPLIED保存、失敗分類・ログ、drainループと全体hard timeout、Restore・crash復旧、管理role / CLIは後続。CLAIMEDはNeo4j適用成功やAPPLIEDを意味しない。本部品だけでRebuild全体完了とは扱わない。
